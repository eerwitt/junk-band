"""Non-secret worker configuration shared by local deployment and remote images."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    app: str = "junk-living-sampler"
    media_volume: str = "junk-session-media"
    model: str = "facebook/sam-audio-small-tv"
    source_revision: str = "bb4c6999d2677c7402360e426afc01ddfad6dce0"
    model_revision: str = "afc58d67609fee0086b9c032d91b7db8ebec1aa7"
    gpu: str = "L40S"
    predict_spans: bool = True
    reranking_candidates: int = 8

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        return cls(
            app=os.environ.get("JUNK_MODAL_APP", cls.app).strip(),
            media_volume=os.environ.get("JUNK_MODAL_VOLUME", cls.media_volume).strip(),
            model=os.environ.get("SAM_AUDIO_MODEL_ID", cls.model).strip(),
            source_revision=os.environ.get("SAM_AUDIO_REVISION", cls.source_revision).strip(),
            model_revision=os.environ.get("SAM_AUDIO_MODEL_REVISION", cls.model_revision).strip(),
            gpu=os.environ.get("SAM_AUDIO_GPU", cls.gpu).strip(),
            predict_spans=os.environ.get("SAM_AUDIO_PREDICT_SPANS", "true").strip().lower()
            != "false",
            reranking_candidates=int(
                os.environ.get("SAM_AUDIO_RERANKING_CANDIDATES", str(cls.reranking_candidates))
            ),
        )

    def image_environment(self) -> dict[str, str]:
        # Tokens belong in Modal Secrets. In particular, do not copy os.environ.
        return {
            "HF_HOME": "/weights/hf",
            "JUNK_MODAL_APP": self.app,
            "JUNK_MODAL_VOLUME": self.media_volume,
            "SAM_AUDIO_MODEL_ID": self.model,
            "SAM_AUDIO_REVISION": self.source_revision,
            "SAM_AUDIO_MODEL_REVISION": self.model_revision,
            "SAM_AUDIO_GPU": self.gpu,
            "SAM_AUDIO_PREDICT_SPANS": str(self.predict_spans).lower(),
            "SAM_AUDIO_RERANKING_CANDIDATES": str(self.reranking_candidates),
        }
