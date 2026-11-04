import asyncio
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

from fastapi import HTTPException
from PIL import Image

from services.gateway.characters import STYLE_VERSION, paint_character
from services.gateway.config import Settings
from services.gateway.limits import SiteGuard, WorkQueue, is_out_of_credit
from services.gateway.meta import MetaAdapter
from services.gateway.models import CharacterJob, CharacterRequest
from services.gateway.repository import Repository, expired
from services.gateway.selection import (
    clean_mask,
    concept_variants,
    mask_area,
    paper_background_object,
    write_cutout,
)

logger = logging.getLogger(__name__)
# SAM answers short noun phrases, so the description is tried in pieces before these.
FALLBACK_CONCEPTS = ("object", "illustration", "character")
PAINTING_AT_ONCE = 2
MAX_WAITING = 20


# Part of the cache key, so a selection cut by older rules is not handed back unchanged.
CUT_VERSION = "paper-v2"


class CharacterJobs:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        flush: Callable[[], None],
        guard: SiteGuard | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.flush = flush
        self.guard = guard
        self.pending: dict[tuple[str, str], asyncio.Task[None]] = {}
        self.queue = WorkQueue(PAINTING_AT_ONCE, MAX_WAITING)
        self.tickets: dict[tuple[str, str], object] = {}
        # How a job ended when that could not be saved, so it is not mistaken for a restart.
        self.unsaved: dict[tuple[str, str], CharacterJob] = {}

    def _store(self, owner: str, job: CharacterJob) -> None:
        self.repository.write(owner, f"{job.id}-character.json", job.model_dump())
        self.flush()

    def get(self, owner: str, job_id: str) -> CharacterJob:
        self.repository.validate_id(job_id)
        if (owner, job_id) in self.unsaved:
            return self.unsaved[(owner, job_id)]
        job = CharacterJob.model_validate(self.repository.read(owner, f"{job_id}-character.json"))
        if job.status in {"queued", "processing"} and (owner, job_id) not in self.pending:
            job = job.model_copy(
                update={
                    "status": "failed",
                    "error": "The gateway restarted during character creation. Retry; your source cutout is retained.",
                }
            )
            self._store(owner, job)
        ticket = self.tickets.get((owner, job_id))
        if ticket is not None and job.status == "queued":
            return job.model_copy(update={"queue_position": self.queue.ahead_of(ticket)})
        return job

    async def submit(self, owner: str, request: CharacterRequest) -> CharacterJob:
        if self.settings.mode != "live" or not self.settings.meta_key:
            raise HTTPException(
                503,
                "Set MODEL_API_KEY to make a cardboard character with Meta Muse Image. No generated character is faked in demo mode.",
            )
        if not MetaAdapter.segmentation_available():
            raise HTTPException(
                503,
                "Meta SAM support must be installed before making characters. Run uv sync --extra dev on the gateway; no image-generation request was sent.",
            )
        source = self.repository.path(owner, f"{request.cutout_id}-cutout.png")
        if not source.exists() or expired(source, self.settings.ttl_hours):
            raise HTTPException(404, "The source cutout expired. Cut out the object again first.")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        job_id = hashlib.sha256(
            f"{request.model_dump_json()}:{digest}:{self.settings.image_model}:{STYLE_VERSION}:{CUT_VERSION}".encode()
        ).hexdigest()[:32]
        record = self.repository.path(owner, f"{job_id}-character.json")
        if record.exists():
            existing = self.get(owner, job_id)
            target = self.repository.path(owner, f"{job_id}-character.png")
            if (owner, job_id) in self.pending or (
                existing.status == "ready"
                and target.exists()
                and not expired(target, self.settings.ttl_hours)
            ):
                return existing
        if any(session == owner for session, _ in self.pending):
            raise HTTPException(
                429, "One character is already being made. Let it finish before starting another."
            )
        ticket = self.queue.join()
        try:
            if self.guard:
                await self.guard.admit()
        except BaseException:
            # Including a dropped request, or this place would block the line for good.
            await asyncio.shield(self.queue.leave(ticket))
            raise
        self.tickets[(owner, job_id)] = ticket
        job = CharacterJob(
            id=job_id,
            status="queued",
            source_cutout_url=f"/assets/{request.cutout_id}-cutout.png",
            queue_position=self.queue.ahead_of(ticket),
        )
        self._store(owner, job)
        task = asyncio.create_task(self._render_in_turn(owner, job, request, ticket))
        self.pending[(owner, job_id)] = task
        task.add_done_callback(lambda done: self._finish(owner, job, done))
        return job

    async def _render_in_turn(
        self, owner: str, job: CharacterJob, request: CharacterRequest, ticket: object
    ) -> None:
        try:
            await self.queue.wait(ticket)
            await self._render(owner, job.model_copy(update={"queue_position": 0}), request)
        finally:
            self.tickets.pop((owner, job.id), None)
            await self.queue.leave(ticket)

    async def _render(self, owner: str, job: CharacterJob, request: CharacterRequest) -> None:
        painted = self.repository.path(owner, f"{job.id}-painted.png")
        character = self.repository.path(owner, f"{job.id}-character.png")
        self._store(owner, job.model_copy(update={"status": "processing", "stage": "painting"}))
        if not painted.exists():
            await paint_character(
                self.settings.meta_key,
                self.settings.image_model,
                self.repository.path(owner, f"{request.cutout_id}-cutout.png"),
                painted,
                request.description,
                request.details,
            )
            self.flush()
        self._store(owner, job.model_copy(update={"status": "processing", "stage": "cutting"}))
        # Muse Image returns opaque pictures. SAM must make a genuine alpha matte
        # of the new whole figure, including added limbs, instead of reusing the old mask.
        cut_by = "cutout"
        if not character.exists():
            cut_by = await self._cut_character(
                owner, painted, character, job.id, request.description
            )
        with Image.open(character) as result:
            alpha = result.convert("RGBA").getchannel("A")
            minimum, maximum = cast("tuple[int, int]", alpha.getextrema())
        if maximum < 128 or minimum >= 128:
            character.unlink(missing_ok=True)
            raise ValueError("The character did not have a usable alpha matte")
        self._store(
            owner,
            job.model_copy(
                update={
                    "status": "ready",
                    "stage": "ready",
                    "character_url": f"/assets/{job.id}-character.png",
                    "provenance": f"Meta {self.settings.image_model} + {cut_by}",
                }
            ),
        )

    async def _cut_character(
        self, owner: str, painted: Path, character: Path, job_id: str, description: str
    ) -> str:
        """Cut out the painted object and return how, for its provenance.

        Lifting it off plain paper comes first. It costs nothing and keeps every part of the object,
        where SAM has returned a few scattered pieces of a painted necklace and passed every check.
        """
        mask = self.repository.path(owner, f"{job_id}-matte.png")
        lifted = await asyncio.to_thread(paper_background_object, painted)
        if lifted is not None:
            await asyncio.to_thread(write_cutout, painted, lifted, character, mask)
            return "paper background removed"
        adapter = MetaAdapter(self.settings.meta_key)
        wordings = [*concept_variants(description), *FALLBACK_CONCEPTS]
        for concept in dict.fromkeys(wordings):
            found = await adapter.find_objects(painted, concept)
            if found:
                main = await asyncio.to_thread(clean_mask, max(found, key=mask_area))
                await asyncio.to_thread(write_cutout, painted, main, character, mask)
                return "SAM 3.1 alpha mask"
        raise ValueError("The painted paper is not plain, and SAM could not find the object")

    def _finish(self, owner: str, job: CharacterJob, task: asyncio.Task[None]) -> None:
        self.pending.pop((owner, job.id), None)
        error = None if task.cancelled() else task.exception()
        if error is not None and self.guard and is_out_of_credit(error):
            self.guard.note_out_of_meta_credit()
        if task.cancelled() or error is not None:
            logger.warning(
                "Character job failed id=%s error_type=%s reason=%s",
                job.id,
                type(error).__name__,
                error,
            )
            failed = job.model_copy(
                update={
                    "status": "failed",
                    "error": "Character creation could not finish. Check Meta image/SAM access and retry. Your original cutout and sound are unchanged; no mock image was substituted.",
                }
            )
            try:
                self._store(owner, failed)
            except OSError as save_error:
                logger.error("Could not save failed job id=%s: %s", job.id, save_error)
                self.unsaved[(owner, job.id)] = failed
