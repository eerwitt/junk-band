"""Explicit HTTP/provider fixtures exercise the smoke runner, never live inference."""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from scripts.smoke_pipeline import run_smoke

MEDIA, CUTOUT, CHARACTER, AUDIO = (digit * 32 for digit in "1234")


def image_bytes(color: str, opaque: bool = False) -> bytes:
    image = Image.new("RGBA", (40, 60), "ivory" if opaque else (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 8, 30, 52), fill=color)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def audio_bytes(duration: int = 2) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as sound:
        sound.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        sound.writeframes(b"\x00\x10" * 8000 * duration)
    return stream.getvalue()


def fixture_client(problem: str = "") -> tuple[httpx.Client, list[str]]:
    calls: list[str] = []
    source_png = image_bytes("orange", opaque=problem == "opaque")
    styled_png = (
        source_png
        if problem == "unchanged"
        else image_bytes("salmon", opaque=problem == "opaque_styled")
    )
    names = ["left_arm", "right_arm", "left_leg", "right_leg"]
    rig = {
        "width": 40,
        "height": 60,
        "body_url": f"/assets/{CHARACTER}-body.png",
        "parts": [
            {
                "name": name,
                "url": f"/assets/{CHARACTER}-{name.replace('_', '-')}.png",
                "pivot": [0.5, 0.7],
                "max_angle": 0.2,
            }
            for name in names
        ],
    }
    layer_bytes = {}
    for index, name in enumerate(["body", *names]):
        image = Image.new("RGBA", (40, 60))
        ImageDraw.Draw(image).rectangle((3 + index * 6, 10, 7 + index * 6, 40), fill="salmon")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        layer_bytes[f"/api/assets/{CHARACTER}-{name.replace('_', '-')}.png"] = stream.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path == "/api/health":
            return httpx.Response(
                200,
                json={
                    "mode": "mock" if problem == "demo" else "live",
                    "audio": True,
                    "sam": True,
                    "image": problem != "missing",
                },
                headers={"set-cookie": "session=fixture; Path=/api; HttpOnly"},
            )
        assert request.headers.get("cookie") == "session=fixture", "Session must survive every call"
        if path == "/api/media":
            return httpx.Response(
                200, json={"id": MEDIA, "audio_present": True, "width": 640, "duration_s": 4}
            )
        if path == "/api/segment":
            assert json.loads(request.content)["media_id"] == MEDIA
            return httpx.Response(
                200,
                json={
                    "cutout_id": CUTOUT,
                    "cutout_url": f"/assets/{CUTOUT}-cutout.png",
                    "provenance": "SAM 3.1 alpha mask",
                },
            )
        if path == "/api/characters":
            assert json.loads(request.content)["cutout_id"] == CUTOUT
            return httpx.Response(202, json={"id": CHARACTER, "status": "processing"})
        if path == f"/api/characters/{CHARACTER}":
            return httpx.Response(
                200,
                json={
                    "id": CHARACTER,
                    "status": "failed" if problem == "failed" else "ready",
                    "error": "fixture provider failure",
                    "character_url": f"/assets/{CHARACTER}-character.png",
                    "provenance": "Meta muse-image-1.0 + SAM 3.1 alpha mask",
                    "rig": rig,
                },
            )
        if path == "/api/separate":
            assert json.loads(request.content)["media_id"] == MEDIA
            return httpx.Response(
                202,
                json={
                    "id": AUDIO,
                    "status": "ready",
                    "provenance": "mock raw copy" if problem == "fake_audio" else "SAM Audio",
                    "target_url": f"/assets/{AUDIO}-target.wav",
                    "residual_url": f"/assets/{AUDIO}-residual.wav",
                },
            )
        if path == f"/api/assets/{CUTOUT}-cutout.png":
            return httpx.Response(200, content=source_png)
        if path == f"/api/assets/{CHARACTER}-character.png":
            return httpx.Response(200, content=styled_png)
        if path in layer_bytes:
            return httpx.Response(200, content=layer_bytes[path])
        if path.endswith(".wav"):
            return httpx.Response(200, content=audio_bytes(3 if problem == "duration" else 2))
        raise AssertionError(f"Unexpected fixture request: {request.method} {path}")

    return httpx.Client(
        base_url="https://fixture.invalid/api/", transport=httpx.MockTransport(handler)
    ), calls


def test_full_pipeline_saves_distinct_artifacts_and_measured_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.smoke_pipeline.time.sleep", lambda _: None)
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"explicit mocked video fixture, not actual media")
    client, calls = fixture_client()
    with client:
        report = run_smoke(client, source, tmp_path / "run", "tin clanking", end=2, character=True)
    artifacts = report["artifacts"]
    assert report["status"] == "ready"
    assert artifacts["original_cutout"]["sha256"] != artifacts["character"]["sha256"]
    assert artifacts["character"]["alpha_range"] == [0, 255]
    assert artifacts["target"]["duration_s"] == 2
    assert artifacts["target"]["rms"] == 0.125
    assert calls.count(f"/api/assets/{CUTOUT}-cutout.png") == 2
    assert calls.index("/api/characters") < calls.index("/api/separate")
    assert json.loads((tmp_path / "run/report.json").read_text()) == report
    assert len(list((tmp_path / "run").glob("*.png"))) == 2
    assert len(list((tmp_path / "run").glob("*.wav"))) == 2


@pytest.mark.parametrize(
    "problem",
    ["demo", "missing", "opaque", "opaque_styled", "unchanged", "failed", "fake_audio", "duration"],
)
def test_pipeline_rejects_invalid_or_fake_results_without_stale_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    monkeypatch.setattr("scripts.smoke_pipeline.time.sleep", lambda _: None)
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"fixture")
    output = tmp_path / "run"
    output.mkdir()
    (output / "report.json").write_text('{"status":"ready","mode":"live"}')
    client, calls = fixture_client(problem)
    with client, pytest.raises((RuntimeError, ValueError)):
        run_smoke(client, source, output, "tin clanking", end=2, character=True)
    assert json.loads((output / "report.json").read_text())["status"] == "failed"
    if problem in {"demo", "missing"}:
        assert calls == ["/api/health"], (
            "Reject missing/live prerequisites before uploading or charging"
        )
    if problem in {"opaque", "failed", "unchanged"}:
        assert "/api/separate" not in calls


def test_live_audio_never_accepts_mock_provenance_even_without_flag(tmp_path: Path) -> None:
    source = tmp_path / "fixture.wav"
    source.write_bytes(audio_bytes())
    client, _ = fixture_client("fake_audio")
    with client, pytest.raises(RuntimeError, match="mock output is not accepted"):
        run_smoke(client, source, tmp_path / "run", "can", end=2)
