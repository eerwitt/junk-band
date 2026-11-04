"""SAM public-contract fixtures; these do not claim real model or parser inference."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.media import extract_frame, inspect_media
from services.gateway.meta import MetaAdapter, ModelResultError
from services.gateway.models import SegmentRequest


class FixtureStreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaskRecord:
    object_id: str
    revision: int
    mask: object
    bounds: object


def record(identifier: str = "1", revision: int = 1, x: float = 2.0) -> MaskRecord:
    return MaskRecord(
        identifier,
        revision,
        SimpleNamespace(width=4, height=5),
        SimpleNamespace(left=x, top=3.0, right=x + 4, bottom=8.0),
    )


def fixture_adapter(
    monkeypatch: pytest.MonkeyPatch,
    records: list[MaskRecord],
    status: str = "completed",
    diagnostic: str | None = None,
    terminal_error: BaseException | None = None,
) -> tuple[MetaAdapter, list[str]]:
    calls: list[str] = []

    async def create(**kwargs: object) -> object:
        assert kwargs["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
        calls.append("request")
        return object()

    async def final_result() -> SimpleNamespace:
        if terminal_error is not None:
            raise terminal_error
        return SimpleNamespace(
            records=records,
            diagnostics=[SimpleNamespace(severity=diagnostic)] if diagnostic else [],
            outcome=SimpleNamespace(status=status),
        )

    async def close() -> None:
        calls.append("closed")

    parser = SimpleNamespace(
        ResponsesStreamError=FixtureStreamError,
        SegmentationMaskRecord=MaskRecord,
        decode_mask_to_raster=lambda _: bytes([1] * 20),
        image_segmentation_format=lambda: object(),
        parse_responses_stream=lambda *_: SimpleNamespace(final_result=final_result, aclose=close),
        build_object_prompt=lambda **_: "explicit boxed object 1 fixture",
        PromptObject=lambda **kwargs: kwargs,
        FramePrompt=lambda **kwargs: kwargs,
        PromptBox=lambda *args: args,
    )
    monkeypatch.setattr("services.gateway.meta.import_module", lambda _: parser)
    adapter = object.__new__(MetaAdapter)
    adapter.client = SimpleNamespace(responses=SimpleNamespace(create=create))  # type: ignore[assignment]
    return adapter, calls


@pytest.mark.parametrize("cancelled", [False, True])
def test_parser_failure_closes_transport_and_cancellation_stays_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "orange").save(source)
    error = (
        asyncio.CancelledError() if cancelled else FixtureStreamError("synthetic provider failure")
    )
    adapter, calls = fixture_adapter(monkeypatch, [], terminal_error=error)
    with pytest.raises(asyncio.CancelledError if cancelled else ModelResultError):
        asyncio.run(adapter.segment_layer(source, tmp_path / "failed.png", "arm"))
    assert calls == ["request", "closed"]
    assert not (tmp_path / "failed.png").exists()


def test_latest_revision_wins_even_when_cumulative_records_arrive_out_of_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "orange").save(source)
    adapter, calls = fixture_adapter(monkeypatch, [record(revision=2, x=10), record(revision=1)])
    target = tmp_path / "layer.png"
    asyncio.run(adapter.segment_layer(source, target, "paper arm"))
    assert Image.open(target).getchannel("A").getbbox() == (10, 3, 14, 8)
    assert calls == ["request", "closed"]


@pytest.mark.parametrize("status,diagnostic", [("incomplete", None), ("completed", "error")])
def test_incomplete_or_dropped_data_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, diagnostic: str | None
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "orange").save(source)
    adapter, calls = fixture_adapter(monkeypatch, [record()], status, diagnostic)
    target = tmp_path / "layer.png"
    with pytest.raises(ModelResultError):
        asyncio.run(adapter.segment_layer(source, target, "paper arm"))
    assert not target.exists() and calls[-1] == "closed"


def test_box_selects_prompted_identity_and_ambiguous_concepts_need_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "orange").save(source)
    adapter, _ = fixture_adapter(monkeypatch, [record("0", x=12), record("1", x=2)])
    with pytest.raises(ValueError, match="More than one"):
        asyncio.run(adapter.segment_layer(source, tmp_path / "ambiguous.png", "can"))
    asyncio.run(
        adapter.segment(
            source,
            tmp_path / "boxed.png",
            SegmentRequest(media_id="fixture", frame_s=0, box=[0.1, 0.1, 0.7, 0.7]),
        )
    )
    assert Image.open(tmp_path / "boxed.png").size == (4, 5)
    # A box request must not silently use some other detected identity.
    adapter, _ = fixture_adapter(monkeypatch, [record("0")])
    with pytest.raises(ValueError, match="No object matched"):
        asyncio.run(
            adapter.segment(
                source,
                tmp_path / "wrong.png",
                SegmentRequest(media_id="fixture", frame_s=0, box=[0.1, 0.1, 0.7, 0.7]),
            )
        )


def test_warning_keeps_valid_mask_but_non_pixel_grid_bounds_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "orange").save(source)
    adapter, _ = fixture_adapter(monkeypatch, [record()], diagnostic="warning")
    asyncio.run(adapter.segment_layer(source, tmp_path / "valid.png", "arm"))
    assert (tmp_path / "valid.png").exists()
    adapter, _ = fixture_adapter(monkeypatch, [record(x=2.5)])
    with pytest.raises(ModelResultError, match="pixel grid"):
        asyncio.run(adapter.segment_layer(source, tmp_path / "invalid.png", "arm"))


def test_phone_photo_orientation_matches_preview_and_segmentation_canvas(tmp_path: Path) -> None:
    image = Image.new("RGB", (40, 20), "orange")
    # EXIF orientation 6 displays a 90-degree clockwise rotation.
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / "phone.jpg"
    image.save(source, exif=exif)
    media = inspect_media(source, "a" * 32, source.name)
    assert (media.width, media.height) == (20, 40)
    frame = tmp_path / "frame.png"
    extract_frame(source, frame, 0)
    with Image.open(frame) as rotated:
        assert rotated.size == (20, 40)
        assert rotated.getexif().get(274, 1) == 1, "Do not retain a second display rotation"


def test_unusable_provider_stream_is_reported_as_upstream_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def incomplete(
        _self: object, _source: Path, _target: Path, _request: SegmentRequest, _mask: object = None
    ) -> None:
        raise ModelResultError(
            "SAM segmentation ended before completion. Retry; no mock crop was substituted."
        )

    monkeypatch.setattr("services.gateway.meta.MetaAdapter.segment", incomplete)
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 20), "orange").save(source)
    settings = Settings(
        mode="live",
        meta_key="explicit-test-key",
        session_secret="x" * 40,
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        media = client.post(
            "/api/media", files={"file": (source.name, source.read_bytes(), "image/png")}
        )
        assert media.status_code == 200
        result = client.post(
            "/api/segment", json={"media_id": media.json()["id"], "frame_s": 0, "concept": "can"}
        )
        assert result.status_code == 502 and "before completion" in result.json()["detail"]
        assert not list(settings.data_dir.glob("*/*-cutout.png"))
