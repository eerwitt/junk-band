"""Stage local media into the deployed GPU volume and retrieve real output files."""

import asyncio
import logging
import time
import wave
from collections.abc import Callable
from typing import Any

import modal

from services.gateway.config import WORKER_LIMIT_MESSAGE, WORKER_LIMIT_S, Settings
from services.gateway.meta import ModelDependencyError
from services.gateway.models import SeparateRequest, SoundStage
from services.gateway.repository import Repository

logger = logging.getLogger(__name__)
PROBE_INTERVAL_S = 30
PROBE_TIMEOUT_S = 5
ACCOUNT_ERRORS = (modal.exception.AuthError, modal.exception.PermissionDeniedError)


async def finish_within_limit(
    call: "modal.FunctionCall[dict[str, Any]]", limit_s: float = WORKER_LIMIT_S
) -> dict[str, Any]:
    """Await a spawned worker call, cancelling it at the limit so it cannot keep billing."""
    try:
        return await call.get.aio(timeout=limit_s)
    except (TimeoutError, modal.exception.TimeoutError) as error:
        await call.cancel.aio(terminate_containers=True)
        raise ModelDependencyError(WORKER_LIMIT_MESSAGE) from error


def note_gpu_wait(metrics: dict[str, Any], asked_at: float) -> dict[str, Any]:
    """How long this job waited for its container to start, if it had to."""
    started = metrics.pop("container_started_unix", None)
    if isinstance(started, (int, float)):
        metrics["waited_for_gpu_s"] = round(max(0.0, started - asked_at), 1)
    return metrics


class LocalModalSeparator:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.repository = repository
        self.app_name = settings.modal_app
        self.volume_name = settings.modal_volume
        self.volume = modal.Volume.from_name(settings.modal_volume)
        self.worker = modal.Cls.from_name(settings.modal_app, "Separator")()
        self._probed_at: float | None = None
        self._problem: str | None = None

    def _not_deployed(self) -> str:
        return (
            f"The Modal audio worker is not deployed: app '{self.app_name}' or volume "
            f"'{self.volume_name}' was not found. Raw trimming remains available."
        )

    def _account_problem(self) -> str:
        return "Modal rejected these credentials. Check the token; raw trimming remains available."

    def _probe(self) -> str | None:
        # Fresh handles, so a worker deployed while the gateway runs is noticed.
        try:
            modal.Volume.from_name(self.volume_name).hydrate()
            modal.Cls.from_name(self.app_name, "Separator").hydrate()
        except modal.exception.NotFoundError:
            return self._not_deployed()
        except ACCOUNT_ERRORS:
            return self._account_problem()
        return None

    async def unavailable_reason(self) -> str | None:
        """Why the deployed worker cannot be used, or None if it can or the check was inconclusive."""
        now = time.monotonic()
        if self._probed_at is not None and now - self._probed_at < PROBE_INTERVAL_S:
            return self._problem
        try:
            self._problem = await asyncio.wait_for(
                asyncio.to_thread(self._probe), timeout=PROBE_TIMEOUT_S
            )
        except (TimeoutError, modal.exception.Error, OSError) as error:
            # A network blip says nothing about the deployment; a job will report a real failure.
            logger.warning("Modal availability check inconclusive: %s", type(error).__name__)
            self._problem = None
        self._probed_at = now
        return self._problem

    async def warm(self) -> None:
        """Start a container early, so the wait is over before someone asks for the sound."""
        try:
            await self.worker.warm.spawn.aio()
        except modal.exception.Error as error:
            logger.warning("Worker warm-up skipped: %s", type(error).__name__)

    def _upload(self, owner: str, request: SeparateRequest) -> None:
        metadata = self.repository.read(owner, f"{request.media_id}.json")
        source = self.repository.path(owner, metadata["stored_name"])
        record = self.repository.path(owner, f"{request.media_id}.json")
        with self.volume.batch_upload(force=True) as batch:
            batch.put_file(source, f"/{owner}/{source.name}")
            batch.put_file(record, f"/{owner}/{record.name}")

    def _download(self, owner: str, job_id: str, request: SeparateRequest) -> None:
        for stem in ("target", "residual"):
            target = self.repository.path(owner, f"{job_id}-{stem}.wav")
            temporary = target.with_suffix(".tmp")
            try:
                size = 0
                with temporary.open("wb") as output:
                    for chunk in self.volume.read_file(f"/{owner}/{target.name}"):
                        size += len(chunk)
                        if size > 32 * 1024 * 1024:
                            raise ValueError("GPU output exceeds the supported audio size")
                        output.write(chunk)
                with wave.open(str(temporary), "rb") as audio:
                    duration = audio.getnframes() / audio.getframerate()
                    if (
                        audio.getnchannels() not in {1, 2}
                        or audio.getsampwidth() != 2
                        or abs(duration - (request.end_s - request.start_s)) > 0.1
                    ):
                        raise ValueError("GPU output has unexpected audio geometry")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)

    async def __call__(
        self,
        owner: str,
        job_id: str,
        request: SeparateRequest,
        on_stage: Callable[[SoundStage], None] = lambda _stage: None,
    ) -> dict[str, Any]:
        self.repository.validate_id(job_id)
        self.repository.validate_id(request.media_id)
        try:
            on_stage("sending")
            await asyncio.to_thread(self._upload, owner, request)
            on_stage("separating")
            asked_at = time.time()
            call = await self.worker.separate.spawn.aio(owner, job_id, request.model_dump())
            result: Any = await finish_within_limit(call)
            if isinstance(result, dict):
                result = note_gpu_wait(result, asked_at)
        except modal.exception.NotFoundError as error:
            raise ModelDependencyError(self._not_deployed()) from error
        except ACCOUNT_ERRORS as error:
            raise ModelDependencyError(self._account_problem()) from error
        if not isinstance(result, dict):
            raise ValueError("GPU worker returned invalid metrics")
        on_stage("collecting")
        await asyncio.to_thread(self._download, owner, job_id, request)
        return result

    def _remove_session(self, owner: str) -> None:
        # Modal reports a missing path as a generic InvalidError, so look before removing.
        try:
            entries = self.volume.listdir("/")
        except modal.exception.NotFoundError:
            return
        if any(entry.path.strip("/") == owner for entry in entries):
            self.volume.remove_file(f"/{owner}", recursive=True)

    async def clear_session(self, owner: str) -> None:
        self.repository.validate_id(owner)
        await asyncio.to_thread(self._remove_session, owner)
