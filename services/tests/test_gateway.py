import io
import math
import struct
import time
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.models import SeparateRequest
from services.gateway.repository import Repository, sign_session, verify_session


def test_decimal_trim_boundaries_accept_roundoff_without_widening_the_window() -> None:
    for end in (2.3, 8.3):
        request = SeparateRequest(media_id="a" * 32, start_s=0.3, end_s=end, description="can")
        assert request.end_s == end
    for end in (2.29, 8.31):
        with pytest.raises(ValueError, match="between 2 and 8"):
            SeparateRequest(media_id="a" * 32, start_s=0.3, end_s=end, description="can")


def recording(seconds: int = 4) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(
            b"".join(
                struct.pack("<h", int(math.sin(i * 2 * math.pi * 220 / 8000) * 10000))
                for i in range(seconds * 8000)
            )
        )
    return output.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def test_upload_raw_separate_and_session_isolation(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/media", files={"file": ("tin.wav", recording(), "audio/wav")})
    assert response.status_code == 200, response.text
    source = response.json()
    assert source["audio_present"] and source["duration_s"] == 4
    payload = {"media_id": source["id"], "start_s": 0, "end_s": 4, "description": "tin clanking"}
    response = client.post("/api/separate", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"ready", "failed"}:
            break
        time.sleep(0.1)
    assert job["status"] == "ready", job
    assert job["provenance"] == "mock raw copy"
    target = client.get(f"/api{job['target_url']}")
    assert target.status_code == 200
    with wave.open(io.BytesIO(target.content), "rb") as wav:
        assert wav.getnframes() / wav.getframerate() == 4
    residual = client.get(f"/api{job['residual_url']}")
    with wave.open(io.BytesIO(residual.content), "rb") as wav:
        assert set(wav.readframes(wav.getnframes())) == {0}
    assert client.post("/api/separate", json=payload).json()["id"] == job_id
    with TestClient(create_app(Settings(data_dir=tmp_path))) as other:
        assert other.get(f"/api{job['target_url']}").status_code == 404


def test_mock_crop_is_honest_and_geometry_is_validated(client: TestClient) -> None:
    image = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image, format="PNG")
    source = client.post(
        "/api/media", files={"file": ("object.png", image.getvalue(), "image/png")}
    ).json()
    payload = {"media_id": source["id"], "frame_s": 0, "concept": None, "box": [0.1, 0.1, 0.8, 0.9]}
    result = client.post("/api/segment", json=payload)
    assert result.status_code == 200, result.text
    assert "Mock rectangular" in result.json()["provenance"]
    cutout = client.get(f"/api{result.json()['cutout_url']}")
    with Image.open(io.BytesIO(cutout.content)) as crop:
        assert crop.size == (70, 64)
    payload["concept"] = "can"
    assert client.post("/api/segment", json=payload).status_code == 422


def test_rejects_unsafe_windows_and_sources(client: TestClient) -> None:
    assert (
        client.post(
            "/api/media", files={"file": ("script.py", b"print(1)", "text/plain")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/media", files={"file": ("too-long.wav", recording(61), "audio/wav")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/separate",
            json={"media_id": "../../secret", "start_s": 0, "end_s": 4, "description": "tin"},
        ).status_code
        == 422
    )
    with pytest.raises(ValueError):
        SeparateRequest(media_id="x", start_s=3, end_s=2, description="tin")
    assert client.get("/api/assets/1234-secret.json").status_code == 422


def test_wonder_returns_inspectable_allowlisted_actions(client: TestClient) -> None:
    response = client.post(
        "/api/wonder",
        json={
            "instruction": "make it playful",
            "performers": [
                {"id": "p-1", "name": "Tin", "steps": [0, 4], "motion": "dance", "gainDb": -12}
            ],
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["provenance"] == "mock rule"
    assert len(proposal["trace"]) == 2
    assert all(action["performerId"] == "p-1" for action in proposal["actions"])


def test_session_signature_and_path_boundaries(tmp_path: Path) -> None:
    identifier = "a" * 32
    cookie = sign_session(identifier, "secret")
    assert verify_session(cookie, "secret") == identifier
    assert verify_session(cookie, "wrong") is None
    assert verify_session("../escape.fake", "secret") is None
    repository = Repository(tmp_path)
    with pytest.raises(ValueError):
        repository.path(identifier, "../../private.key")
    with pytest.raises(ValueError):
        repository.folder("../escape")


def test_optional_model_endpoints_are_wired_and_honest(client: TestClient) -> None:
    result = client.post("/api/interpret", json={"description": "a glass bottle ringing"})
    assert result.status_code == 200, result.text
    assert result.json()["provenance"] == "mock rule"
    assert result.json()["role"] == "texture"
    voice = client.post(
        "/api/transcribe", files={"file": ("command.wav", recording(), "audio/wav")}
    )
    assert voice.status_code == 200
    assert "not recognized" in voice.json()["provenance"]
    assert "mock:sam-3.1" in client.get("/api/models").json()["models"]


def test_job_failure_keeps_original_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = client.post("/api/media", files={"file": ("tin.wav", recording(), "audio/wav")}).json()

    def unavailable(*_args: object) -> None:
        raise RuntimeError("Injected GPU outage")

    monkeypatch.setattr("services.gateway.app.extract_audio", unavailable)
    response = client.post(
        "/api/separate",
        json={"media_id": source["id"], "start_s": 0, "end_s": 4, "description": "tin"},
    )
    job_id = response.json()["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "failed":
            break
        time.sleep(0.1)
    assert job["status"] == "failed"
    assert "raw trimmed" in job["error"]
    monkeypatch.undo()
    raw = client.get(f"/api/media/{source['id']}/audio?start_s=0&end_s=4")
    assert raw.status_code == 200


def test_delete_session_removes_server_assets(client: TestClient) -> None:
    source = client.post("/api/media", files={"file": ("tin.wav", recording(), "audio/wav")}).json()
    assert client.delete("/api/session").json() == {"deleted": True}
    assert client.get(f"/api/media/{source['id']}/audio?start_s=0&end_s=4").status_code == 404
