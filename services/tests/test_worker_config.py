import os
from pathlib import Path

import pytest

from services.gateway.config import Settings
from services.gateway.environment import load_environment
from services.gpu.config import WorkerSettings


def test_deployment_and_local_bridge_share_names_and_forward_checkpoint_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "JUNK_MODAL_APP": " custom-band ",
        "JUNK_MODAL_VOLUME": " custom-media ",
        "SAM_AUDIO_MODEL_ID": "facebook/sam-audio-base-tv",
        "SAM_AUDIO_REVISION": "a" * 40,
        "SAM_AUDIO_MODEL_REVISION": "b" * 40,
        "SAM_AUDIO_GPU": "A100-80GB",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    gateway = Settings(mode="mock", meta_key="", modal_enabled=False)
    worker = WorkerSettings.from_environment()
    assert gateway.modal_app == worker.app == "custom-band"
    assert gateway.modal_volume == worker.media_volume == "custom-media"
    image = worker.image_environment()
    assert image["SAM_AUDIO_MODEL_REVISION"] == "b" * 40, (
        "The remote download must not silently revert to main"
    )
    assert image["SAM_AUDIO_REVISION"] == "a" * 40
    assert image["SAM_AUDIO_MODEL_ID"] == values["SAM_AUDIO_MODEL_ID"]


def test_image_environment_never_embeds_api_or_download_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HF_TOKEN",
        "MODEL_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "JUNK_API_SESSION_SECRET",
    ):
        monkeypatch.setenv(name, "explicit-test-secret")
    environment = WorkerSettings.from_environment().image_environment()
    assert "explicit-test-secret" not in environment.values()
    assert set(environment) == {
        "HF_HOME",
        "JUNK_MODAL_APP",
        "JUNK_MODAL_VOLUME",
        "SAM_AUDIO_MODEL_ID",
        "SAM_AUDIO_REVISION",
        "SAM_AUDIO_MODEL_REVISION",
        "SAM_AUDIO_GPU",
        "SAM_AUDIO_PREDICT_SPANS",
        "SAM_AUDIO_RERANKING_CANDIDATES",
    }


def test_separation_quality_settings_reach_the_worker_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SAM_AUDIO_GPU", "SAM_AUDIO_PREDICT_SPANS", "SAM_AUDIO_RERANKING_CANDIDATES"):
        monkeypatch.delenv(name, raising=False)
    chosen = WorkerSettings.from_environment()
    assert (chosen.gpu, chosen.predict_spans, chosen.reranking_candidates) == ("L40S", True, 8)
    monkeypatch.setenv("SAM_AUDIO_PREDICT_SPANS", "False")
    monkeypatch.setenv("SAM_AUDIO_RERANKING_CANDIDATES", "1")
    image = WorkerSettings.from_environment().image_environment()
    assert image["SAM_AUDIO_PREDICT_SPANS"] == "false"
    assert image["SAM_AUDIO_RERANKING_CANDIDATES"] == "1"


def test_env_file_worker_settings_honor_shell_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("JUNK_MODAL_APP", "JUNK_MODAL_VOLUME", "SAM_AUDIO_MODEL_REVISION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SAM_AUDIO_MODEL_REVISION", "c" * 40)
    path = tmp_path / ".env"
    path.write_text(
        "JUNK_MODAL_APP=env-band\nJUNK_MODAL_VOLUME=env-media\nSAM_AUDIO_MODEL_REVISION=main\n"
    )
    # Register keys with monkeypatch so the loader's writes are restored too.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    load_environment(path)
    worker = WorkerSettings.from_environment()
    assert worker.app == "env-band" and worker.media_volume == "env-media"
    assert worker.model_revision == "c" * 40
