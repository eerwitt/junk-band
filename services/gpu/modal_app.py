import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import modal

from services.gateway.config import Settings
from services.gateway.environment import load_environment
from services.gateway.models import SeparateRequest, SoundStage
from services.gateway.volume_sync import VolumeSync
from services.gpu.config import WorkerSettings
from services.gpu.image_lock import GPU_PACKAGES

logger = logging.getLogger(__name__)
STUDIO_DIR = "/app/dist"
MEDIA_RETENTION_HOURS = 24
load_environment(Path(__file__).resolve().parents[2] / ".env")
worker_settings = WorkerSettings.from_environment()
APP_NAME = worker_settings.app
MODEL_ID = worker_settings.model
SAM_AUDIO_REVISION = worker_settings.source_revision
# A local gateway only needs the worker, so it can deploy without the hosted gateway's secrets.
HOSTED_GATEWAY = os.environ.get("JUNK_MODAL_GATEWAY", "true").strip().lower() != "false"
app = modal.App(APP_NAME)
weights = modal.Volume.from_name("junk-sam-audio-weights", create_if_missing=True)
media = modal.Volume.from_name(worker_settings.media_volume, create_if_missing=True)
volume = VolumeSync(media.commit, media.reload)
cpu_base = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install_from_pyproject("pyproject.toml")
    .env(worker_settings.image_environment())
)
cpu_image = cpu_base.add_local_python_source("services")
gpu_image = (
    modal.Image.from_registry("pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime")
    .apt_install("ffmpeg", "git", "libsndfile1", "build-essential")
    # Everything is pinned to the image verified on real recordings; see image_lock.py.
    .pip_install(*GPU_PACKAGES, extra_options="--no-deps")
    .pip_install(
        f"sam_audio @ git+https://github.com/facebookresearch/sam-audio.git@{SAM_AUDIO_REVISION}",
        extra_options="--no-deps",
    )
    # Fail the build, which runs once, rather than every container start, which retries.
    .run_commands(
        "pip check || true",
        'python -c "from google.protobuf.internal.enum_type_wrapper import EnumTypeWrapper as E; '
        'E.ValueType"',
        'python -c "from sam_audio import SAMAudio, SAMAudioProcessor"',
    )
    .env(worker_settings.image_environment())
    # The container re-imports this module, so it must register the same functions.
    .env({"JUNK_MODAL_GATEWAY": str(HOSTED_GATEWAY).lower()})
    # torch.compile's worker processes start during the snapshot, when there is no GPU, and fail
    # after every restore. Compiling inside the main process avoids them.
    .env({"TORCHINDUCTOR_COMPILE_THREADS": "1"})
    .add_local_python_source("services")
)


@app.function(
    image=gpu_image,
    volumes={"/weights": weights},
    secrets=[modal.Secret.from_name("hf-sam-audio")],
    cpu=8,
    memory=48000,
    timeout=1800,
)
def download_weights() -> str:
    # Runtime is imported as a module so research/GPU imports remain at its top level.
    runtime = import_module("services.gpu.runtime")
    snapshot = runtime.download_checkpoint(MODEL_ID)
    runtime.cache_dependencies(MODEL_ID)
    weights.commit()
    return snapshot


@app.cls(
    image=gpu_image,
    gpu=worker_settings.gpu,
    volumes={"/weights": weights, "/session-media": media},
    secrets=[modal.Secret.from_name("hf-sam-audio")],
    timeout=300,
    startup_timeout=600,
    min_containers=0,
    max_containers=1,
    scaledown_window=180,
    # Cold starts spent 71-283 s reading the model from the volume. A snapshot restores it loaded.
    enable_memory_snapshot=True,
)
class Separator:
    @modal.enter(snap=True)
    def load(self) -> None:
        runtime = import_module("services.gpu.runtime")
        self.runtime = runtime.SeparationRuntime(MODEL_ID)

    @modal.enter(snap=False)
    def attach_gpu(self) -> None:
        self.runtime.attach_gpu()

    @modal.method()
    def warm(self) -> None:
        """Nothing to do: reaching this means the model is loaded."""

    @modal.method()
    def separate(self, owner: str, job_id: str, request: dict[str, Any]) -> dict[str, Any]:
        media.reload()
        result = self.runtime.separate(owner, job_id, SeparateRequest.model_validate(request))
        media.commit()
        return result


async def submit(
    owner: str, job_id: str, request: SeparateRequest, on_stage: Callable[[SoundStage], None]
) -> dict[str, Any]:
    # Saved first so the worker can read the source. Its results are read back after it finishes.
    await asyncio.to_thread(volume.commit_now)
    on_stage("separating")
    call = await Separator().separate.spawn.aio(owner, job_id, request.model_dump())
    # Imported here because this module also loads in the GPU image, which lacks gateway packages.
    bridge = import_module("services.gateway.modal_bridge")
    asked_at = time.time()
    result: dict[str, Any] = await bridge.finish_within_limit(call)
    return bridge.note_gpu_wait(result, asked_at)


if HOSTED_GATEWAY:
    # The page and the API share one address, so the session cookie is an ordinary first-party one.
    gateway_image = (
        cpu_base.add_local_dir("dist", remote_path=STUDIO_DIR, copy=True)
        .run_commands(f"gzip -k -9 {STUDIO_DIR}/engine/*.wasm {STUDIO_DIR}/engine/*.pck")
        .env(
            {
                name: value
                for name in (
                    "JUNK_DAILY_REQUEST_LIMIT",
                    "JUNK_MODAL_MONTHLY_LIMIT",
                    "JUNK_META_MONTHLY_LIMIT",
                )
                if (value := os.environ.get(name))
            }
        )
        # Last, because Modal adds local source when a container starts, after any build steps.
        .add_local_python_source("services")
    )

    @app.function(
        image=gateway_image,
        volumes={"/session-media": media},
        secrets=[modal.Secret.from_name("meta-model-api"), modal.Secret.from_name("junk-gateway")],
        max_containers=1,
        min_containers=0,
        scaledown_window=300,
        timeout=1200,
    )
    @modal.concurrent(max_inputs=30)
    @modal.asgi_app()
    def gateway() -> Callable[..., Awaitable[None]]:
        gateway_module = import_module("services.gateway.app")
        files = import_module("services.gateway.studio_files")
        site = gateway_module.create_app(
            Settings(data_dir=Path("/session-media"), mode="live"),
            submit_job=submit,
            sync_read=volume.reload,
            sync_write=volume.flush,
        )
        site.mount("/", files.StudioFiles(directory=STUDIO_DIR, html=True), name="studio")
        return site

    @app.function(
        image=cpu_image,
        volumes={"/session-media": media},
        schedule=modal.Cron("0 4 * * *"),
        timeout=600,
    )
    def remove_expired_media() -> None:
        retention = import_module("services.gateway.retention")
        media.reload()
        removed = retention.remove_expired_sessions(Path("/session-media"), MEDIA_RETENTION_HOURS)
        media.commit()
        logger.info("Removed %s expired sessions", removed)


@app.local_entrypoint()
def main(download: bool = False) -> None:
    if download:
        download_weights.remote()
