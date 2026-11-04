import asyncio
import io
import time
import wave
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import modal
import pytest
from fastapi.testclient import TestClient

from services.gateway.app import create_app
from services.gateway.config import WORKER_LIMIT_S, Settings
from services.gateway.meta import ModelDependencyError
from services.gateway.modal_bridge import LocalModalSeparator, finish_within_limit
from services.gateway.models import SeparateRequest
from services.gateway.repository import Repository


def wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(bytes(8000 * 4 * 2))
    return buffer.getvalue()


class VolumeFixture:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def batch_upload(self, force: bool = False) -> "VolumeFixture":
        assert force
        return self

    def __enter__(self) -> "VolumeFixture":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def put_file(self, source: Path, target: str) -> None:
        self.files[target] = source.read_bytes()

    def read_file(self, path: str) -> list[bytes]:
        data = self.files[path]
        return [data[:60], data[60:]]


def test_local_modal_round_trip_stages_source_metadata_and_real_wave_files(tmp_path: Path) -> None:
    owner, media, job = "a" * 32, "b" * 32, "c" * 32
    repository = Repository(tmp_path)
    repository.path(owner, f"{media}.wav").write_bytes(wav())
    repository.write(
        owner, f"{media}.json", {"stored_name": f"{media}.wav", "media": {"id": media}}
    )
    volume = VolumeFixture()
    calls: list[dict] = []

    async def remote(actual_owner: str, actual_job: str, request: dict) -> dict:
        assert actual_owner == owner and actual_job == job
        assert volume.files[f"/{owner}/{media}.wav"] == wav()
        assert f"/{owner}/{media}.json" in volume.files
        calls.append(request)
        for stem in ("target", "residual"):
            volume.files[f"/{owner}/{job}-{stem}.wav"] = wav()
        return {"model": "SAM Audio fixture", "sample_rate": 8000}

    bridge = LocalModalSeparator.__new__(LocalModalSeparator)
    bridge.repository = repository
    bridge.volume = volume

    async def spawn(*args: object) -> SimpleNamespace:
        async def get(timeout: float) -> dict:
            assert timeout == WORKER_LIMIT_S
            return await remote(*args)

        return SimpleNamespace(get=SimpleNamespace(aio=get))

    bridge.worker = SimpleNamespace(separate=SimpleNamespace(spawn=SimpleNamespace(aio=spawn)))
    request = SeparateRequest(media_id=media, start_s=0, end_s=4, description="can clanking")
    stages: list[str] = []
    result = asyncio.run(bridge(owner, job, request, stages.append))
    assert stages == ["sending", "separating", "collecting"]
    assert calls == [request.model_dump()]
    assert result["sample_rate"] == 8000
    for stem in ("target", "residual"):
        assert repository.path(owner, f"{job}-{stem}.wav").read_bytes() == wav()
    assert not list(repository.folder(owner).glob("*.tmp"))


class SessionVolume:
    """Models the real volume: removing an absent path raises InvalidError, not NotFoundError."""

    def __init__(self, sessions: list[str], missing: bool = False) -> None:
        self.sessions = sessions
        self.missing = missing

    def listdir(self, _path: str) -> list[SimpleNamespace]:
        if self.missing:
            raise modal.exception.NotFoundError("Volume not found")
        return [SimpleNamespace(path=session) for session in self.sessions]

    def remove_file(self, path: str, recursive: bool = False) -> None:
        assert recursive
        if path.strip("/") not in self.sessions:
            raise modal.exception.InvalidError("No such file or directory.")
        self.sessions.remove(path.strip("/"))


def bridge_with(tmp_path: Path, volume: object) -> LocalModalSeparator:
    bridge = LocalModalSeparator.__new__(LocalModalSeparator)
    bridge.repository = Repository(tmp_path)
    bridge.volume = volume
    bridge.app_name = "fixture-app"
    bridge.volume_name = "fixture-volume"
    bridge._probed_at = None
    bridge._problem = None
    return bridge


def test_clearing_a_session_with_nothing_on_the_volume_succeeds(tmp_path: Path) -> None:
    owner, other = "a" * 32, "b" * 32
    volume = SessionVolume([owner, other])
    bridge = bridge_with(tmp_path, volume)
    asyncio.run(bridge.clear_session(owner))
    assert volume.sessions == [other], "Only this session's files are removed"
    asyncio.run(bridge.clear_session(owner))
    asyncio.run(bridge_with(tmp_path, SessionVolume([], missing=True)).clear_session(owner))


def test_undeployed_worker_is_reported_as_setup_not_as_a_bad_prompt(tmp_path: Path) -> None:
    class Missing:
        def batch_upload(self, force: bool = False) -> None:
            raise modal.exception.NotFoundError("Volume not found")

    owner, media = "a" * 32, "b" * 32
    bridge = bridge_with(tmp_path, Missing())
    bridge.repository.path(owner, f"{media}.wav").write_bytes(wav())
    bridge.repository.write(owner, f"{media}.json", {"stored_name": f"{media}.wav"})
    request = SeparateRequest(media_id=media, start_s=0, end_s=4, description="tin")
    with pytest.raises(
        ModelDependencyError, match="fixture-app.*not deployed|not deployed.*fixture-app"
    ):
        asyncio.run(bridge(owner, "c" * 32, request))


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (modal.exception.NotFoundError("gone"), "not deployed"),
        (modal.exception.AuthError("bad token"), "credentials"),
        (modal.exception.ConnectionError("blip"), None),
    ],
)
def test_availability_only_blames_setup_for_definite_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: str | None
) -> None:
    calls: list[str] = []

    def from_name(name: str) -> None:
        calls.append(name)
        raise raised

    monkeypatch.setattr(modal.Volume, "from_name", from_name)
    bridge = bridge_with(tmp_path, object())

    async def twice() -> tuple[str | None, str | None]:
        return await bridge.unavailable_reason(), await bridge.unavailable_reason()

    first, second = asyncio.run(twice())
    assert first == second
    assert (first is None) if expected is None else (expected in first)
    assert len(calls) == 1, "Health polling must not call Modal every time"


@pytest.mark.parametrize("raised", [TimeoutError(), modal.exception.TimeoutError("late")])
def test_worker_limit_cancels_the_call_and_its_containers(raised: Exception) -> None:
    cancelled: list[bool] = []

    async def get(timeout: float) -> dict:
        raise raised

    async def cancel(terminate_containers: bool = False) -> None:
        cancelled.append(terminate_containers)

    call = SimpleNamespace(get=SimpleNamespace(aio=get), cancel=SimpleNamespace(aio=cancel))
    with pytest.raises(ModelDependencyError, match="did not finish"):
        asyncio.run(finish_within_limit(call))
    assert cancelled == [True], "Giving up must also stop the billing"


def test_job_limit_ends_a_stuck_job_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StuckWorker(WorkerFixture):
        async def __call__(self, *_args: object) -> dict:
            await asyncio.sleep(60)
            return {}

    monkeypatch.setattr("services.gateway.app.JOB_LIMIT_S", 0.05)
    job, outputs = finished_job(tmp_path, StuckWorker(tmp_path))
    assert job["status"] == "failed" and "did not finish" in job["error"]
    assert outputs == []


class WorkerFixture:
    def __init__(
        self, tmp_path: Path, metrics: dict | None = None, error: Exception | None = None
    ) -> None:
        self.repository = Repository(tmp_path)
        self.metrics = metrics
        self.error = error

    async def __call__(
        self, owner: str, job_id: str, _request: SeparateRequest, on_stage: Callable
    ) -> dict:
        on_stage("separating")
        self.stage_seen = self.repository.read(owner, f"{job_id}-job.json")["stage"]
        if self.error:
            raise self.error
        for stem in ("target", "residual"):
            self.repository.path(owner, f"{job_id}-{stem}.wav").write_bytes(wav())
        return self.metrics or {}


def finished_job(tmp_path: Path, worker: WorkerFixture) -> tuple[dict, list[Path]]:
    settings = Settings(
        mode="live", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=False
    )
    with TestClient(create_app(settings, submit_job=worker)) as client:
        media = client.post("/api/media", files={"file": ("source.wav", wav(), "audio/wav")}).json()
        job = client.post(
            "/api/separate",
            json={"media_id": media["id"], "start_s": 0, "end_s": 4, "description": "tin"},
        ).json()
        for _ in range(200):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] in {"ready", "failed"}:
                break
            time.sleep(0.01)
    return job, list(tmp_path.rglob(f"{job['id']}-*.wav"))


def test_sam_audio_label_requires_the_worker_to_report_sam_audio(tmp_path: Path) -> None:
    claimed = {"model": "facebook/sam-audio-large-tv", "sample_rate": 8000}
    worker = WorkerFixture(tmp_path / "real", claimed)
    job, outputs = finished_job(tmp_path / "real", worker)
    assert job["status"] == "ready" and job["provenance"] == "SAM Audio"
    assert len(outputs) == 2
    assert worker.stage_seen == "separating", "Reported stages reach the stored job while running"
    assert job["stage"] is None, "A finished job has no running stage"

    stub = {"model": "CPU STUB", "sample_rate": 8000}
    job, outputs = finished_job(tmp_path / "stub", WorkerFixture(tmp_path / "stub", stub))
    assert job["status"] == "failed" and "SAM Audio" in job["error"]
    assert outputs == [], "Unattributed audio must not stay downloadable"


def test_setup_failures_reach_the_job_but_other_errors_stay_generic(tmp_path: Path) -> None:
    setup = WorkerFixture(tmp_path / "a", error=ModelDependencyError("worker is not deployed"))
    assert finished_job(tmp_path / "a", setup)[0]["error"] == "worker is not deployed"
    internal = WorkerFixture(tmp_path / "b", error=RuntimeError("private /weights/path detail"))
    assert "private" not in finished_job(tmp_path / "b", internal)[0]["error"]


def test_health_and_delete_with_an_undeployed_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Undeployed:
        def __init__(self, *_args: object) -> None:
            self.cleared: list[str] = []

        async def unavailable_reason(self) -> str:
            return "The Modal audio worker is not deployed"

        async def clear_session(self, owner: str) -> None:
            self.cleared.append(owner)

    monkeypatch.setattr("services.gateway.modal_bridge.LocalModalSeparator", Undeployed)
    settings = Settings(
        mode="live", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=True
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["audio"] is False
        assert health["configuration"]["modal_configured"] is True
        assert "not deployed" in health["configuration"]["modal_problem"]
        assert (
            client.post(
                "/api/media", files={"file": ("source.wav", wav(), "audio/wav")}
            ).status_code
            == 200
        )
        assert list(tmp_path.rglob("*.wav"))
        assert client.delete("/api/session").json() == {"deleted": True}
        assert not list(tmp_path.rglob("*.wav")), "Local media is removed"


def test_invalid_modal_output_is_not_published_as_a_ready_wave(tmp_path: Path) -> None:
    owner, job, media = "a" * 32, "b" * 32, "c" * 32
    volume = VolumeFixture()
    volume.files[f"/{owner}/{job}-target.wav"] = b"not a WAV"
    bridge = LocalModalSeparator.__new__(LocalModalSeparator)
    bridge.repository = Repository(tmp_path)
    bridge.volume = volume
    with pytest.raises((wave.Error, EOFError)):
        bridge._download(
            owner, job, SeparateRequest(media_id=media, start_s=0, end_s=4, description="tin")
        )
    assert not bridge.repository.path(owner, f"{job}-target.wav").exists()
    assert not list(bridge.repository.folder(owner).glob("*.tmp"))
