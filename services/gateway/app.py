import asyncio
import hashlib
import logging
import shutil
import subprocess
import time
import uuid
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from openai import APIError
from PIL import Image
from pydantic import ValidationError

from services.gateway.character_jobs import CharacterJobs
from services.gateway.config import WORKER_LIMIT_MESSAGE, WORKER_LIMIT_S, Settings
from services.gateway.environment import load_environment
from services.gateway.limits import (
    OUT_OF_META,
    SiteGuard,
    WorkQueue,
    is_out_of_credit,
)
from services.gateway.media import (
    ALLOWED_EXTENSIONS,
    extract_audio,
    extract_filmstrip,
    extract_frame,
    inspect_media,
)
from services.gateway.meta import (
    MetaAdapter,
    ModelDependencyError,
    ModelResultError,
    NoObjectMatched,
)
from services.gateway.meta_costs import set_meta_ledger
from services.gateway.models import (
    MAX_SOURCE_S,
    CharacterJob,
    CharacterRequest,
    Job,
    Media,
    SegmentRequest,
    Selection,
    SelectionRequest,
    SeparateRequest,
    SoundStage,
)
from services.gateway.picking import card_bounds, pick, torn_card
from services.gateway.repository import Repository, expired, sign_session, verify_session
from services.gateway.selection import concept_variants, cutout_from_mask

logger = logging.getLogger(__name__)
SubmitJob = Callable[
    [str, str, SeparateRequest, Callable[[SoundStage], None]], Awaitable[dict[str, Any]]
]
SAM_AUDIO_MODEL_PREFIX = "facebook/sam-audio"
# Backstop for the whole job: the worker limit, plus time to move media each way.
JOB_LIMIT_S = WORKER_LIMIT_S + 180
SOUNDS_AT_ONCE = 1
CUTS_AT_ONCE = 3
MAX_WAITING = 20
MAX_MASK_BYTES = 8 * 1024 * 1024


def create_app(
    settings: Settings | None = None,
    submit_job: SubmitJob | None = None,
    sync_read: Callable[[], None] | None = None,
    sync_write: Callable[[], None] | None = None,
) -> FastAPI:
    config = settings or Settings()
    config.validate()
    repository = Repository(config.data_dir)
    modal_bridge = None
    if submit_job is None and config.mode == "live" and config.modal_enabled:
        from services.gateway.modal_bridge import LocalModalSeparator

        modal_bridge = LocalModalSeparator(config, repository)
        submit_job = modal_bridge
    app = FastAPI(title="JUNK media gateway", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.browser_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    tasks: set[asyncio.Task[None]] = set()
    warmups: set[asyncio.Task[None]] = set()
    pending: set[tuple[str, str]] = set()
    # How a job ended when that could not be saved, so it is not mistaken for a restart.
    unsaved_jobs: dict[tuple[str, str], Job] = {}
    guard = SiteGuard(
        config.data_dir,
        config.daily_request_limit,
        config.modal_monthly_limit,
        lambda: flush(),
        enabled=config.mode == "live",
        uses_modal=submit_job is not None,
        meta_monthly_limit=config.meta_monthly_limit,
    )
    set_meta_ledger(guard.add_meta_spend if config.mode == "live" else None)
    # One GPU container, so sounds go one at a time and everyone else waits their turn.
    sound_queue = WorkQueue(SOUNDS_AT_ONCE, MAX_WAITING)
    cut_queue = WorkQueue(CUTS_AT_ONCE, MAX_WAITING)
    sound_tickets: dict[tuple[str, str], object] = {}

    @app.exception_handler(APIError)
    async def meta_error(_request: Request, error: APIError) -> JSONResponse:
        status = getattr(error, "status_code", None)
        if is_out_of_credit(error):
            guard.note_out_of_meta_credit()
            return JSONResponse(status_code=503, content={"detail": OUT_OF_META})
        detail = "Meta request failed. Check MODEL_API_KEY and model access, then retry. No mock output was substituted."
        return JSONResponse(status_code=429 if status == 429 else 502, content={"detail": detail})

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(_request: Request, _error: httpx.HTTPError) -> JSONResponse:
        if is_out_of_credit(_error):
            guard.note_out_of_meta_credit()
            return JSONResponse(status_code=503, content={"detail": OUT_OF_META})
        return JSONResponse(
            status_code=502,
            content={
                "detail": "The model service could not complete this request. Check provider access and retry; no mock output was substituted."
            },
        )

    @app.exception_handler(ModelDependencyError)
    async def dependency_error(_request: Request, error: ModelDependencyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(ModelResultError)
    async def result_error(_request: Request, error: ModelResultError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(FileNotFoundError)
    async def missing_error(_request: Request, _error: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Asset expired or not present in this session. Import the source again."
            },
        )

    @app.exception_handler(subprocess.CalledProcessError)
    async def media_error(_request: Request, error: subprocess.CalledProcessError) -> JSONResponse:
        logger.warning("Media subprocess failed code=%s", error.returncode)
        return JSONResponse(
            status_code=422,
            content={"detail": "Media could not be decoded. Use MP4 H.264/AAC, WebM or WAV."},
        )

    @app.exception_handler(ValidationError)
    async def model_error(_request: Request, _error: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "The model response failed validation. No changes were applied."},
        )

    def flush() -> None:
        if sync_write:
            sync_write()

    characters = CharacterJobs(config, repository, flush, guard)

    def require_meta() -> None:
        if not config.meta_key:
            raise HTTPException(
                503, "Set MODEL_API_KEY to enable Meta models. No mock output is used in live mode."
            )

    def session(request: Request, response: Response) -> str:
        origin = request.headers.get("origin")
        same_site = origin and urlparse(origin).netloc == request.headers.get("host")
        if config.mode == "live" and origin and not same_site and not config.allows_origin(origin):
            raise HTTPException(403, "Origin is not allowed")
        current = verify_session(request.cookies.get("junk_session"), config.session_secret)
        if current:
            return current
        current = uuid.uuid4().hex
        response.set_cookie(
            "junk_session",
            sign_session(current, config.session_secret),
            httponly=True,
            secure=config.mode == "live" and not config.local_origin,
            samesite="lax",
            max_age=86400,
        )
        return current

    Session = Annotated[str, Depends(session)]

    def read_media(owner: str, media_id: str) -> tuple[Media, Path]:
        repository.validate_id(media_id)
        info = repository.read(owner, f"{media_id}.json")
        path = repository.path(owner, info["stored_name"])
        if expired(path, config.ttl_hours):
            raise HTTPException(410, "Source expired. Import it again.")
        return Media.model_validate(info["media"]), path

    def job_path(owner: str, job_id: str) -> str:
        repository.validate_id(job_id)
        return f"{job_id}-job.json"

    def store_job(owner: str, job: Job) -> None:
        repository.write(owner, job_path(owner, job.id), job.model_dump())
        flush()

    async def process_in_turn(
        owner: str, job_id: str, data: SeparateRequest, ticket: object
    ) -> None:
        try:
            await sound_queue.wait(ticket)
            await process(owner, job_id, data)
        finally:
            sound_tickets.pop((owner, job_id), None)
            await sound_queue.leave(ticket)

    async def process(owner: str, job_id: str, data: SeparateRequest) -> None:
        store_job(
            owner,
            Job(
                id=job_id,
                status="processing",
                provenance="SAM Audio" if config.mode == "live" else "mock raw copy",
            ),
        )
        started = time.perf_counter()
        if config.mode == "live":
            if not submit_job:
                raise RuntimeError("Live GPU adapter is not configured")

            def report_stage(stage: SoundStage) -> None:
                store_job(
                    owner,
                    Job(id=job_id, status="processing", stage=stage, provenance="SAM Audio"),
                )

            try:
                result = await asyncio.wait_for(
                    submit_job(owner, job_id, data, report_stage), timeout=JOB_LIMIT_S
                )
            except TimeoutError as error:
                raise ModelDependencyError(WORKER_LIMIT_MESSAGE) from error
            if sync_read:
                await asyncio.to_thread(sync_read)
            metrics = result
            # "SAM Audio" is shown to people and saved in projects: the worker must claim it.
            if not str(metrics.get("model", "")).startswith(SAM_AUDIO_MODEL_PREFIX):
                for stem in ("target", "residual"):
                    repository.path(owner, f"{job_id}-{stem}.wav").unlink(missing_ok=True)
                raise ModelResultError(
                    "The audio worker did not identify itself as SAM Audio, so its output was discarded."
                )
        else:
            _, source = read_media(owner, data.media_id)
            target = repository.path(owner, f"{job_id}-target.wav")
            residual = repository.path(owner, f"{job_id}-residual.wav")
            await asyncio.to_thread(extract_audio, source, target, data.start_s, data.end_s)
            with (
                wave.open(str(target), "rb") as original,
                wave.open(str(residual), "wb") as silence,
            ):
                silence.setparams(original.getparams())
                silence.writeframes(
                    bytes(original.getnframes() * original.getnchannels() * original.getsampwidth())
                )
            await asyncio.sleep(0.6)
            metrics = {
                "inference_s": 0,
                "processing_s": time.perf_counter() - started,
                "model": "mock: no model inference",
            }
        store_job(
            owner,
            Job(
                id=job_id,
                status="ready",
                provenance="SAM Audio" if config.mode == "live" else "mock raw copy",
                target_url=f"/assets/{job_id}-target.wav",
                residual_url=f"/assets/{job_id}-residual.wav",
                metrics=metrics,
            ),
        )

    def settle_failed(owner: str, job: Job) -> None:
        try:
            store_job(owner, job)
        except OSError as error:
            logger.error("Could not save failed job=%s: %s", job.id, error)
            unsaved_jobs[(owner, job.id)] = job

    def finish(task: asyncio.Task[None], owner: str, job_id: str) -> None:
        tasks.discard(task)
        pending.discard((owner, job_id))
        if task.cancelled():
            settle_failed(
                owner,
                Job(
                    id=job_id,
                    status="failed",
                    provenance=config.mode,
                    error="Worker cancelled. Your original is retained; retry or use raw audio.",
                ),
            )
        elif (error := task.exception()) is not None:
            logger.error(
                "Extraction failed job=%s",
                job_id,
                exc_info=(type(error), error, error.__traceback__),
            )
            settle_failed(
                owner,
                Job(
                    id=job_id,
                    status="failed",
                    provenance=config.mode,
                    error=str(error)
                    if isinstance(error, (ModelDependencyError, ModelResultError))
                    else "Extraction failed. Edit the prompt, retry, or use raw trimmed audio.",
                ),
            )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        modal_problem = await modal_bridge.unavailable_reason() if modal_bridge else None
        return {
            "mode": config.mode,
            "sam": config.mode == "mock"
            or bool(config.meta_key)
            and MetaAdapter.segmentation_available(),
            "audio": config.mode == "mock" or (submit_job is not None and modal_problem is None),
            "image": config.mode == "live"
            and bool(config.meta_key)
            and MetaAdapter.segmentation_available(),
            "configuration": {
                "meta_configured": bool(config.meta_key),
                "sam_parser_installed": MetaAdapter.segmentation_available(),
                "modal_configured": submit_job is not None,
                "modal_problem": modal_problem,
            },
            "limits": await guard.status(),
        }

    @app.get("/api/models")
    async def models() -> dict[str, list[str]]:
        if config.mode == "mock":
            return {
                "models": [
                    "mock:sam-3.1",
                    "mock:sam-audio",
                    "mock:muse-spark-1.3",
                ]
            }
        require_meta()
        return {"models": await MetaAdapter(config.meta_key).models()}

    @app.post("/api/media")
    async def upload(owner: Session, file: Annotated[UploadFile, File()]) -> Media:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                415, "Unsupported file type. Use MP4, WebM, WAV, MP3, OGG, FLAC or a still image."
            )
        media_id = uuid.uuid4().hex
        name = f"{media_id}{suffix}"
        target = repository.path(owner, name)
        size = 0
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.max_upload:
                    handle.close()
                    target.unlink()
                    raise HTTPException(413, f"Keep media under {config.max_upload // 2**20} MB")
                handle.write(chunk)
        metadata = await asyncio.to_thread(
            inspect_media, target, media_id, Path(file.filename or name).name[:120]
        )
        repository.write(
            owner, f"{media_id}.json", {"media": metadata.model_dump(), "stored_name": name}
        )
        flush()
        return metadata

    @app.get("/api/media/{media_id}/frame")
    async def source_frame(media_id: str, owner: Session, frame_s: float = 0) -> FileResponse:
        # Decode the user's source independently of browser codec support. The
        # resulting PNG uses the same orientation/scale as SAM's input frame.
        request = SegmentRequest(media_id=media_id, frame_s=frame_s, concept="preview")
        info, source = read_media(owner, media_id)
        if not info.width:
            raise HTTPException(422, "This recording has no picture")
        if info.duration_s and request.frame_s >= info.duration_s:
            raise HTTPException(422, "Choose a frame inside the source duration")
        key = hashlib.sha256(f"{media_id}:{request.frame_s:.3f}:preview-v1".encode()).hexdigest()[
            :32
        ]
        target = repository.path(owner, f"{key}-preview.png")
        if not target.exists():
            temporary = target.with_name(f"{key}-{uuid.uuid4().hex}.tmp.png")
            try:
                await asyncio.to_thread(extract_frame, source, temporary, request.frame_s)
                temporary.replace(target)
                flush()
            finally:
                temporary.unlink(missing_ok=True)
        return FileResponse(
            target, media_type="image/png", headers={"Cache-Control": "private, no-store"}
        )

    @app.post("/api/segment")
    async def segment(data: SegmentRequest, owner: Session) -> dict[str, str]:
        info, source = read_media(owner, data.media_id)
        if not info.width:
            raise HTTPException(422, "This source has no picture. Use a video or still image.")
        if info.duration_s and data.frame_s >= info.duration_s:
            raise HTTPException(422, "Choose a frame inside the source duration")
        key = hashlib.sha256(f"{data.model_dump_json()}:{config.mode}".encode()).hexdigest()[:32]
        frame = repository.path(owner, f"{key}-frame.png")
        target = repository.path(owner, f"{key}-cutout.png")
        mask = repository.path(owner, f"{key}-mask.png")
        if not target.exists():
            await asyncio.to_thread(extract_frame, source, frame, data.frame_s)
            if config.mode == "live":
                if not config.meta_key:
                    raise HTTPException(
                        503,
                        "Set MODEL_API_KEY to segment pictures with Meta SAM. No mock crop is used in live mode.",
                    )
                await guard.admit()
                adapter = MetaAdapter(config.meta_key)
                wordings = concept_variants(data.concept) if data.concept else [None]
                for index, wording in enumerate(wordings):
                    try:
                        await adapter.segment(
                            frame, target, data.model_copy(update={"concept": wording}), mask
                        )
                        break
                    except NoObjectMatched:
                        if index == len(wordings) - 1:
                            raise
            else:
                with Image.open(frame) as original:
                    width, height = original.size
                    box = data.box or [0.15, 0.1, 0.85, 0.95]
                    original.convert("RGBA").crop(
                        (
                            int(box[0] * width),
                            int(box[1] * height),
                            int(box[2] * width),
                            int(box[3] * height),
                        )
                    ).save(target)
                    canvas = Image.new("L", (width, height), 0)
                    canvas.paste(
                        255,
                        (
                            int(box[0] * width),
                            int(box[1] * height),
                            int(box[2] * width),
                            int(box[3] * height),
                        ),
                    )
                    canvas.save(mask)
            flush()
        return {
            "cutout_id": key,
            "cutout_url": f"/assets/{key}-cutout.png",
            **({"mask_url": f"/assets/{mask.name}"} if mask.exists() else {}),
            "provenance": "SAM 3.1 alpha mask"
            if config.mode == "live"
            else "Mock rectangular crop · no SAM segmentation",
        }

    @app.post("/api/selections")
    async def selection(data: SelectionRequest, owner: Session) -> Selection:
        info, source = read_media(owner, data.media_id)
        if not info.width:
            raise HTTPException(422, "This recording has no picture to select from.")
        if info.duration_s and data.frame_s >= info.duration_s:
            raise HTTPException(422, "Choose a frame inside the source duration")

        async def before_paid() -> None:
            await guard.admit()
            if modal_bridge is not None and info.audio_present:
                warming = asyncio.create_task(modal_bridge.warm())
                warmups.add(warming)
                warming.add_done_callback(warmups.discard)

        key = config.meta_key if config.mode == "live" else ""
        async with cut_queue.slot():
            picked = await pick(key, repository, owner, info, source, data, before_paid)
        flush()
        return picked

    @app.get("/api/media/{media_id}/filmstrip")
    async def filmstrip(
        media_id: str,
        owner: Session,
        count: int = 12,
        start_s: float = 0,
        end_s: float | None = None,
    ) -> FileResponse:
        if not 2 <= count <= 40:
            raise HTTPException(422, "Ask for between 2 and 40 frames.")
        info, source = read_media(owner, media_id)
        if not info.width or not info.duration_s:
            raise HTTPException(422, "Only video has a filmstrip.")
        end = info.duration_s if end_s is None else min(end_s, info.duration_s)
        if not 0 <= start_s < end:
            raise HTTPException(422, "Choose a stretch inside the video.")
        key = hashlib.sha256(
            f"{media_id}:{count}:{start_s:.2f}:{end:.2f}:strip-v2".encode()
        ).hexdigest()[:32]
        target = repository.path(owner, f"{key}-filmstrip.jpg")
        if not target.exists():
            await asyncio.to_thread(
                extract_filmstrip, source, target, end - start_s, count, start_s
            )
            flush()
        return FileResponse(
            target, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )

    @app.post("/api/media/{media_id}/mask")
    async def painted_mask(
        media_id: str,
        owner: Session,
        file: Annotated[UploadFile, File()],
        frame_s: Annotated[float, Form(ge=0, le=MAX_SOURCE_S)] = 0,
        base_cutout_id: Annotated[str | None, Form()] = None,
    ) -> dict[str, str]:
        info, source = read_media(owner, media_id)
        if not info.width:
            raise HTTPException(422, "This source has no picture to mask.")
        if info.duration_s and frame_s >= info.duration_s:
            raise HTTPException(422, "Choose a frame inside the source duration")
        painted = await file.read(MAX_MASK_BYTES + 1)
        if len(painted) > MAX_MASK_BYTES:
            raise HTTPException(413, "That mask is too large.")
        edited = False
        if base_cutout_id:
            repository.validate_id(base_cutout_id)
            edited = repository.path(owner, f"{base_cutout_id}-cutout.png").exists()
        key = hashlib.sha256(painted + f"{media_id}:{frame_s:.3f}".encode()).hexdigest()[:32]
        frame = repository.path(owner, f"{key}-frame.png")
        upload_path = repository.path(owner, f"{key}-painted.png")
        cutout = repository.path(owner, f"{key}-cutout.png")
        mask = repository.path(owner, f"{key}-mask.png")
        await asyncio.to_thread(extract_frame, source, frame, frame_s)
        upload_path.write_bytes(painted)
        try:
            await asyncio.to_thread(cutout_from_mask, frame, upload_path, cutout, mask)
        except OSError as error:
            raise HTTPException(422, "That mask could not be read. Paint it again.") from error
        flush()
        if not edited:
            provenance = "Hand-drawn mask"
        elif config.mode == "live":
            provenance = "SAM 3.1 alpha mask + hand edit"
        else:
            provenance = "Mock rectangular crop + hand edit"
        card = repository.path(owner, f"{key}-card.png")
        with Image.open(frame) as image, Image.open(mask) as painted_mask:
            size = image.size
            bounds = painted_mask.getbbox()
        if bounds:
            await asyncio.to_thread(
                torn_card, frame, mask, card_bounds(size, bounds, 0.08), card, key
            )
        return {
            "cutout_id": key,
            "cutout_url": f"/assets/{cutout.name}",
            "mask_url": f"/assets/{mask.name}",
            "card_url": f"/assets/{card.name}",
            "provenance": provenance,
        }

    @app.post("/api/characters", status_code=202)
    async def character(data: CharacterRequest, owner: Session) -> CharacterJob:
        return await characters.submit(owner, data)

    @app.get("/api/characters/{job_id}")
    async def character_status(job_id: str, owner: Session) -> CharacterJob:
        return characters.get(owner, job_id)

    @app.get("/api/media/{media_id}/audio")
    async def raw_audio(
        media_id: str, owner: Session, start_s: float = 0, end_s: float = 4
    ) -> FileResponse:
        window = SeparateRequest(media_id=media_id, start_s=start_s, end_s=end_s, description="raw")
        info, source = read_media(owner, media_id)
        if not info.audio_present or window.end_s > info.duration_s + 0.01:
            raise HTTPException(422, "No audio in that source window")
        key = hashlib.sha256(f"{media_id}:{start_s}:{end_s}".encode()).hexdigest()[:32]
        output = repository.path(owner, f"{key}-raw.wav")
        if not output.exists():
            await asyncio.to_thread(extract_audio, source, output, start_s, end_s)
            flush()
        return FileResponse(output, media_type="audio/wav")

    @app.post("/api/separate", status_code=202)
    async def separate(data: SeparateRequest, owner: Session) -> Job:
        if config.mode == "live" and submit_job is None:
            raise HTTPException(
                503,
                "The Modal audio worker is not configured. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET for the deployed app, or connect to the deployed gateway. Raw trimming remains available.",
            )
        info, _ = read_media(owner, data.media_id)
        if not info.audio_present or data.end_s > info.duration_s + 0.01:
            raise HTTPException(422, "Source has no audio in that window")
        job_id = hashlib.sha256(
            f"{owner}:{data.model_dump_json()}:{config.mode}".encode()
        ).hexdigest()[:32]
        path = repository.path(owner, job_path(owner, job_id))
        if path.exists():
            existing = Job.model_validate(repository.read(owner, path.name))
            if existing.status == "ready" or (owner, job_id) in pending:
                return existing
        if sum(s == owner for s, _ in pending) >= 2:
            raise HTTPException(429, "Two sound jobs are already running. Wait for one to finish.")
        ticket = sound_queue.join()
        try:
            await guard.admit()
        except BaseException:
            # Including a dropped request, or this place would block the line for good.
            await asyncio.shield(sound_queue.leave(ticket))
            raise
        sound_tickets[(owner, job_id)] = ticket
        job = Job(
            id=job_id,
            status="queued",
            provenance="SAM Audio" if config.mode == "live" else "mock raw copy",
            queue_position=sound_queue.ahead_of(ticket),
        )
        store_job(owner, job)
        pending.add((owner, job_id))
        task = asyncio.create_task(process_in_turn(owner, job_id, data, ticket))
        tasks.add(task)
        task.add_done_callback(lambda done: finish(done, owner, job_id))
        return job

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str, owner: Session) -> Job:
        path = job_path(owner, job_id)
        if (owner, job_id) in unsaved_jobs:
            return unsaved_jobs[(owner, job_id)]
        job = Job.model_validate(repository.read(owner, path))
        if job.status in {"queued", "processing"} and (owner, job_id) not in pending:
            job = job.model_copy(
                update={
                    "status": "failed",
                    "error": "Gateway restarted during extraction. Retry the job; your original is retained.",
                }
            )
            store_job(owner, job)
        ticket = sound_tickets.get((owner, job_id))
        if ticket is not None and job.status == "queued":
            return job.model_copy(update={"queue_position": sound_queue.ahead_of(ticket)})
        return job

    @app.get("/api/assets/{filename}")
    async def asset(filename: str, owner: Session) -> FileResponse:
        path = repository.path(owner, filename)
        if path.suffix not in {".png", ".wav"}:
            raise HTTPException(403, "This file is not a downloadable asset")
        if not path.exists() or expired(path, config.ttl_hours):
            raise HTTPException(404, "Asset expired or not present in this session")
        return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "audio/wav")

    @app.delete("/api/session")
    async def delete_session(owner: Session) -> dict[str, bool]:
        if any(s == owner for s, _ in pending) or any(s == owner for s, _ in characters.pending):
            raise HTTPException(
                409, "Wait for running sound and character jobs before removing server media"
            )
        if modal_bridge is not None:
            await modal_bridge.clear_session(owner)
        shutil.rmtree(repository.folder(owner))
        flush()
        return {"deleted": True}

    return app


load_environment()
app = create_app()
