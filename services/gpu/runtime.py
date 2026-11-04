import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import snapshot_download
from sam_audio import SAMAudio, SAMAudioProcessor

from services.gateway.media import extract_audio
from services.gateway.models import SeparateRequest
from services.gateway.repository import Repository
from services.gpu.config import WorkerSettings

logger = logging.getLogger(__name__)


def use_persistent_model_cache() -> None:
    # The ranking models download to a path relative to the working directory, which would
    # otherwise be lost and fetched again on every cold start.
    folder = Path("/weights/runtime")
    folder.mkdir(parents=True, exist_ok=True)
    os.chdir(folder)


def cache_dependencies(model_id: str) -> None:
    """Load once so every model the checkpoint depends on lands on the weights volume."""
    use_persistent_model_cache()
    SAMAudio.from_pretrained(str(checkpoint_path(model_id)))


def checkpoint_path(model_id: str) -> Path:
    return Path("/weights/checkpoints") / model_id.replace("/", "--")


def download_checkpoint(model_id: str) -> str:
    destination = checkpoint_path(model_id)
    revision = os.environ.get("SAM_AUDIO_MODEL_REVISION", "main")
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=str(destination),
        token=os.environ["HF_TOKEN"],
    )
    (destination / "junk-provenance.json").write_text(
        json.dumps({"model_id": model_id, "revision": revision}), encoding="utf-8"
    )
    logger.info(
        "Downloaded authorized checkpoint remotely model=%s revision=%s", model_id, revision
    )
    return str(destination)


class SeparationRuntime:
    def __init__(self, model_id: str) -> None:
        """Load onto the CPU only: this runs before a memory snapshot, which has no GPU."""
        started = time.perf_counter()
        self.settings = WorkerSettings.from_environment()
        use_persistent_model_cache()
        path = checkpoint_path(model_id)
        if not path.exists():
            raise FileNotFoundError("Run download_weights remotely before deploying inference")
        self.model = SAMAudio.from_pretrained(str(path)).eval()
        self.processor = SAMAudioProcessor.from_pretrained(str(path))
        self.model_id = model_id
        self.cpu_load_seconds = time.perf_counter() - started
        self.repository = Repository(Path("/session-media"))
        logger.info("Model loaded model=%s cpu_load_s=%.3f", model_id, self.cpu_load_seconds)

    def attach_gpu(self) -> None:
        """Runs in every container, after any snapshot restore, when the GPU exists."""
        started = time.perf_counter()
        self.container_started_unix = time.time()
        if not torch.cuda.is_available():
            raise RuntimeError("SAM Audio requires a remote CUDA GPU in this deployment")
        self.model = self.model.cuda()
        self.load_seconds = time.perf_counter() - started
        logger.info(
            "Model ready model=%s gpu_attach_s=%.3f gpu=%s",
            self.model_id,
            self.load_seconds,
            torch.cuda.get_device_name(),
        )

    def separate(self, owner: str, job_id: str, request: SeparateRequest) -> dict[str, Any]:
        self.repository.validate_id(job_id)
        self.repository.validate_id(request.media_id)
        metadata = self.repository.read(owner, f"{request.media_id}.json")
        source = self.repository.path(owner, metadata["stored_name"])
        cropped = self.repository.path(owner, f"{job_id}-input.wav")
        extract_audio(source, cropped, request.start_s, request.end_s)
        torch.cuda.reset_peak_memory_stats()
        batch = self.processor(
            audios=[str(cropped)], descriptions=[request.description.lower()]
        ).to("cuda")
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            output = self.model.separate(
                batch,
                predict_spans=self.settings.predict_spans,
                reranking_candidates=self.settings.reranking_candidates,
            )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        rate = int(self.processor.audio_sampling_rate)
        for name in ("target", "residual"):
            tensor = getattr(output, name)[0]
            samples = tensor.detach().float().cpu().numpy().reshape(-1)
            if not samples.size or not np.isfinite(samples).all():
                raise ValueError(f"Model returned invalid {name} waveform")
            expected = (request.end_s - request.start_s) * rate
            if abs(samples.size - expected) > rate * 0.1:
                raise ValueError(f"Unexpected {name} duration")
            if np.max(np.abs(samples)) > 1.5:
                raise ValueError(
                    f"Model returned excessive {name} amplitude; audition source instead"
                )
            sf.write(
                str(self.repository.path(owner, f"{job_id}-{name}.wav")),
                samples,
                rate,
                subtype="PCM_16",
            )
        metrics = {
            "model": self.model_id,
            "gpu": torch.cuda.get_device_name(),
            "load_s": self.load_seconds,
            "cpu_load_s": self.cpu_load_seconds,
            "inference_s": elapsed,
            "peak_allocated_gb": torch.cuda.max_memory_allocated() / 1e9,
            "peak_reserved_gb": torch.cuda.max_memory_reserved() / 1e9,
            "sample_rate": rate,
            "prompt_method": "text",
            "predict_spans": str(self.settings.predict_spans).lower(),
            "reranking_candidates": self.settings.reranking_candidates,
            "source_duration_s": request.end_s - request.start_s,
            "container_started_unix": self.container_started_unix,
        }
        self.repository.write(owner, f"{job_id}-metrics.json", metrics)
        logger.info("Inference completed job=%s metrics=%s", job_id, metrics)
        return metrics
