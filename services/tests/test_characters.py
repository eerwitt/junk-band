import asyncio
import base64
import io
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.gateway.app import create_app
from services.gateway.characters import paint_character
from services.gateway.config import Settings
from services.gateway.meta import FoundObject
from services.gateway.models import SegmentRequest


@pytest.fixture(autouse=True)
def available_sam_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.gateway.meta.MetaAdapter.segmentation_available", staticmethod(lambda: True)
    )

    async def find_objects(_self: object, _source: Path, _concept: str) -> list[FoundObject]:
        return [painted_object()]

    monkeypatch.setattr("services.gateway.meta.MetaAdapter.find_objects", find_objects)


def painted_object() -> FoundObject:
    # Explicit geometry fixture for the 48x64 test image, not model evidence.
    alpha = Image.new("L", (32, 55), 255)
    ImageDraw.Draw(alpha).rectangle((0, 0, 4, 4), fill=0)
    return FoundObject(8, 4, alpha, None)


def png(alpha: bool = True) -> bytes:
    image = Image.new("RGBA", (48, 64), (0, 0, 0, 0) if alpha else "ivory")
    ImageDraw.Draw(image).rectangle((8, 4, 40, 59), fill="orange")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def wait_character(client: TestClient, identifier: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get(f"/api/characters/{identifier}")
        assert result.status_code == 200, result.text
        job = result.json()
        if job["status"] in {"ready", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Character job did not finish")


def test_character_pipeline_preserves_source_and_caches_paid_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bytes]] = []

    async def segment(
        _self: object, frame: Path, target: Path, request: SegmentRequest, _mask: object = None
    ) -> None:
        calls.append(("segment", frame.read_bytes()))
        target.write_bytes(png())

    async def paint(
        _key: str, _model: str, source: Path, target: Path, _description: str, _details: str
    ) -> None:
        calls.append(("paint", source.read_bytes()))
        target.write_bytes(png(False))

    async def find(_self: object, frame: Path, _concept: str) -> list[FoundObject]:
        calls.append(("segment", frame.read_bytes()))
        return [painted_object()]

    monkeypatch.setattr("services.gateway.meta.MetaAdapter.segment", segment)
    monkeypatch.setattr("services.gateway.meta.MetaAdapter.find_objects", find)
    monkeypatch.setattr("services.gateway.character_jobs.paint_character", paint)
    settings = Settings(
        mode="live", data_dir=tmp_path, meta_key="test-key", session_secret="x" * 40
    )
    with TestClient(create_app(settings)) as client:
        media = client.post(
            "/api/media", files={"file": ("object.png", png(False), "image/png")}
        ).json()
        cutout = client.post(
            "/api/segment", json={"media_id": media["id"], "frame_s": 0, "concept": "can"}
        ).json()
        original = client.get("/api" + cutout["cutout_url"]).content
        payload = {
            "cutout_id": cutout["cutout_id"],
            "description": "a tin can clanking",
            "details": "little paper arms and boots",
        }
        result = client.post("/api/characters", json=payload)
        assert result.status_code == 202, result.text
        job = wait_character(client, result.json()["id"])
        assert job["status"] == "ready", job
        assert job["rig"] is None and job["stage"] == "ready", "A single image, with no limbs"
        assert job["provenance"] == "Meta muse-image-1.0 + paper background removed"
        assert [kind for kind, _ in calls] == ["segment", "paint"], "Plain paper needs no SAM call"
        assert calls[1][1] == original
        assert client.get("/api" + cutout["cutout_url"]).content == original
        output = client.get("/api" + job["character_url"])
        assert output.status_code == 200
        with Image.open(io.BytesIO(output.content)) as character:
            assert character.getchannel("A").getextrema()[1] == 255
        assert client.post("/api/characters", json=payload).json()["id"] == job["id"]
        assert len(calls) == 2, (
            "Reviewing an identical candidate must not cause another paid generation"
        )
        with TestClient(create_app(settings)) as stranger:
            assert stranger.get("/api" + job["character_url"]).status_code == 404
            assert stranger.get(f"/api/characters/{job['id']}").status_code == 404


def test_character_retry_reuses_painted_image_and_never_fakes_alpha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Busy paper sends the cut to SAM.
    monkeypatch.setattr("services.gateway.character_jobs.paper_background_object", lambda _: None)
    painted: list[bool] = []
    failed = [False]

    async def segment(
        _self: object, frame: Path, target: Path, request: SegmentRequest, _mask: object = None
    ) -> None:
        target.write_bytes(png())

    async def find(_self: object, _frame: Path, _concept: str) -> list[FoundObject]:
        if not failed[0]:
            failed[0] = True
            raise ValueError("Injected SAM failure")
        return [painted_object()]

    async def paint(*args: object) -> None:
        target = args[3]
        assert isinstance(target, Path)
        painted.append(True)
        target.write_bytes(png(False))

    monkeypatch.setattr("services.gateway.meta.MetaAdapter.segment", segment)
    monkeypatch.setattr("services.gateway.meta.MetaAdapter.find_objects", find)
    monkeypatch.setattr("services.gateway.character_jobs.paint_character", paint)
    settings = Settings(
        mode="live", data_dir=tmp_path, meta_key="test-key", session_secret="x" * 40
    )
    with TestClient(create_app(settings)) as client:
        media = client.post(
            "/api/media", files={"file": ("object.png", png(False), "image/png")}
        ).json()
        cutout = client.post(
            "/api/segment", json={"media_id": media["id"], "frame_s": 0, "concept": "can"}
        ).json()
        payload = {"cutout_id": cutout["cutout_id"], "description": "can"}
        job_id = client.post("/api/characters", json=payload).json()["id"]
        failed_job = wait_character(client, job_id)
        assert failed_job["status"] == "failed" and failed_job["character_url"] is None
        assert "unchanged" in failed_job["error"]
        assert client.post("/api/characters", json=payload).status_code == 202
        ready = wait_character(client, job_id)
        assert ready["status"] == "ready" and ready["provenance"].endswith("SAM 3.1 alpha mask")
        assert len(painted) == 1


def test_painted_object_is_lifted_off_paper_without_asking_sam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def segment(
        _self: object, _frame: Path, target: Path, _request: SegmentRequest, _mask: object = None
    ) -> None:
        target.write_bytes(png())

    async def paint(*args: object) -> None:
        target = args[3]
        assert isinstance(target, Path)
        target.write_bytes(png(False))

    async def nothing(_self: object, _frame: Path, _concept: str) -> list[FoundObject]:
        raise AssertionError("Plain paper must not need a SAM request")

    monkeypatch.setattr("services.gateway.meta.MetaAdapter.segment", segment)
    monkeypatch.setattr("services.gateway.meta.MetaAdapter.find_objects", nothing)
    monkeypatch.setattr("services.gateway.character_jobs.paint_character", paint)
    settings = Settings(
        mode="live", data_dir=tmp_path, meta_key="test-key", session_secret="x" * 40
    )
    with TestClient(create_app(settings)) as client:
        media = client.post(
            "/api/media", files={"file": ("object.png", png(False), "image/png")}
        ).json()
        cutout = client.post(
            "/api/segment", json={"media_id": media["id"], "frame_s": 0, "concept": "can"}
        ).json()
        result = client.post(
            "/api/characters", json={"cutout_id": cutout["cutout_id"], "description": "can"}
        )
        job = wait_character(client, result.json()["id"])
    assert job["status"] == "ready", job


def test_demo_mode_does_not_fake_generated_characters(tmp_path: Path) -> None:
    with TestClient(
        create_app(Settings(mode="mock", data_dir=tmp_path, meta_key="", modal_enabled=False))
    ) as client:
        result = client.post("/api/characters", json={"cutout_id": "a" * 32, "description": "can"})
        assert result.status_code == 503
        assert "MODEL_API_KEY" in result.json()["detail"]


def test_muse_request_uses_reference_and_documented_meta_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "source.png", tmp_path / "painted.png"
    source.write_bytes(png())
    response_image = png(False)

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.meta.ai/v1/images/edits"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "muse-image-1.0"
        assert body["n"] == 1 and body["output_format"] == "png"
        assert (
            base64.b64decode(body["images"][0]["image_url"].split(",", 1)[1]) == source.read_bytes()
        )
        assert len(body["images"]) == 2, "The game's own band is the style reference"
        assert base64.b64decode(body["images"][1]["image_url"].split(",", 1)[1]).startswith(
            b"\x89PNG"
        )
        prompt = body["prompt"].lower()
        assert "cardboard" not in prompt
        assert all(word in prompt for word in ("fun", "musical", "punk", "bright", "kids"))
        assert "A person or animal stays" in body["prompt"]
        assert "It stays an object if it is an object" in body["prompt"]
        assert "no face, arms, legs" in body["prompt"]
        assert "The object: tin can" in body["prompt"] and "warm colors" in body["prompt"]
        return httpx.Response(
            200,
            json={
                "data": [{"b64_json": base64.b64encode(response_image).decode()}],
                "background": "opaque",
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "services.gateway.characters.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    asyncio.run(
        paint_character("test-key", "muse-image-1.0", source, target, "tin can", "warm colors")
    )
    with Image.open(target) as result:
        assert result.size == (48, 64)
    assert source.read_bytes() == png()
