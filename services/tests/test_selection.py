import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.media import inspect_media
from services.gateway.meta import FoundObject, MetaAdapter
from services.gateway.models import SeparateRequest
from services.gateway.selection import (
    LEVEL_RATE,
    best_window,
    clean_mask,
    concept_variants,
    paper_background_object,
    score_object,
)


def png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def picture() -> Image.Image:
    return Image.effect_noise((200, 200), 60).convert("RGB")


def square(left: int, top: int, size: int, confidence: float | None = 0.9) -> FoundObject:
    return FoundObject(left, top, Image.new("L", (size, size), 255), confidence)


def test_clean_mask_drops_stray_islands_but_keeps_real_parts() -> None:
    alpha = Image.new("L", (200, 100), 0)
    alpha.paste(255, (0, 0, 100, 100))  # The object.
    alpha.paste(255, (170, 80, 190, 100))  # A scrap of something else.
    cleaned = clean_mask(FoundObject(10, 20, alpha, 0.5))
    assert cleaned.alpha.size == (100, 100) and (cleaned.left, cleaned.top) == (10, 20)
    assert cleaned.confidence == 0.5
    two = Image.new("L", (200, 100), 0)
    two.paste(255, (0, 0, 90, 100))
    two.paste(255, (110, 0, 200, 100))  # Two real pieces of similar size both stay.
    assert clean_mask(FoundObject(0, 0, two, None)).alpha.size == (200, 100)
    solid = FoundObject(0, 0, Image.new("L", (50, 50), 255), None)
    assert clean_mask(solid) is solid


def test_paper_background_lifts_an_object_and_its_hole(tmp_path: Path) -> None:
    painted = Image.new("RGB", (400, 400), (245, 235, 215))
    draw = ImageDraw.Draw(painted)
    draw.ellipse((100, 100, 300, 300), fill=(150, 60, 30))
    draw.ellipse((170, 170, 230, 230), fill=(245, 235, 215))  # A ring's middle shows the paper.
    draw.point((130, 200), fill=(245, 235, 215))  # A speck of print stays with the object.
    path = tmp_path / "painted.png"
    painted.save(path)
    found = paper_background_object(path)
    assert found is not None
    assert (found.left, found.top) == pytest.approx((100, 100), abs=3)
    assert found.alpha.getpixel((100, 100)) == 0, "The ring's hole is transparent"
    assert found.alpha.getpixel((30, 100)) == 255, "The ring itself is kept"


def test_white_paint_in_a_character_is_not_treated_as_paper(tmp_path: Path) -> None:
    paper = (249, 245, 235)
    painted = Image.new("RGB", (400, 400), paper)
    draw = ImageDraw.Draw(painted)
    draw.ellipse((60, 60, 340, 340), fill=(40, 30, 30))
    # A painted white shirt, a little textured, and enclosed by the dark figure.
    for y in range(140, 260):
        for x in range(140, 260):
            shade = 232 + (x * 7 + y * 13) % 16
            draw.point((x, y), fill=(shade, shade, shade))
    # White with an open side, which the paper could leak into across an outline gap.
    draw.rectangle((180, 40, 220, 120), fill=(255, 255, 255))
    # A true gap showing the same flat paper.
    draw.ellipse((285, 190, 325, 230), fill=paper)
    path = tmp_path / "painted.png"
    painted.save(path)
    found = paper_background_object(path)
    assert found is not None
    alpha_at = lambda x, y: found.alpha.getpixel((x - found.left, y - found.top))  # noqa: E731
    assert alpha_at(200, 200) == 255, "The white shirt stays"
    assert alpha_at(200, 60) == 255, "White reaching the outside stays too"
    assert alpha_at(305, 210) == 0, "A real gap still shows through"
    assert alpha_at(100, 200) == 255, "The dark figure stays"


def test_a_busy_or_blank_picture_is_not_treated_as_plain_paper(tmp_path: Path) -> None:
    busy, blank = tmp_path / "busy.png", tmp_path / "blank.png"
    Image.effect_noise((200, 200), 120).convert("RGB").save(busy)
    Image.new("RGB", (200, 200), (245, 235, 215)).save(blank)
    assert paper_background_object(busy) is None
    assert paper_background_object(blank) is None


def test_best_window_finds_the_sound_events_not_just_steady_volume() -> None:
    hum = [0.5] * (LEVEL_RATE * 20)
    for second in range(12, 19):
        hum[second * LEVEL_RATE] = 1.0  # A sharp hit every second, late in the clip.
    start, end = best_window(hum, 20)
    assert end - start == 8
    assert start <= 12 and end >= 18


def test_best_window_handles_short_and_silent_sources() -> None:
    assert best_window([], 5) == (0.0, 5)
    assert best_window([0.0] * (LEVEL_RATE * 3), 3) == (0.0, 3)
    start, end = best_window([0.0] * (LEVEL_RATE * 20), 20)
    assert end - start == 8


def test_scoring_prefers_a_whole_sensibly_sized_confident_object() -> None:
    frame = picture()
    good = score_object(frame, square(50, 50, 80))
    assert good > score_object(frame, square(50, 50, 80, confidence=0.3)), "Confidence counts"
    assert good > score_object(frame, square(0, 0, 80)), "Cut off by the frame edge"
    assert good > score_object(frame, square(50, 50, 8)), "Too small to use"
    assert good > score_object(frame, square(0, 0, 200)), "The whole picture is not an object"
    assert score_object(frame, square(50, 50, 80, confidence=None)) > 0, "Confidence is optional"


@pytest.mark.parametrize(
    ("duration", "accepted"),
    [("1.9", False), ("2", True), ("60", True), ("60.04", True), ("61", False)],
)
def test_source_clips_may_run_up_to_one_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duration: str, accepted: bool
) -> None:
    payload = {"format": {"duration": duration}, "streams": []}
    monkeypatch.setattr(
        "services.gateway.media.execute", lambda _args: json.dumps(payload).encode()
    )
    clip = tmp_path / "clip.mp4"
    if accepted:
        assert inspect_media(clip, "a", "clip.mp4").duration_s == float(duration)
    else:
        with pytest.raises(ValueError, match="2 to 60 seconds"):
            inspect_media(clip, "a", "clip.mp4")


def test_a_sound_window_late_in_a_long_clip_is_allowed_but_stays_short() -> None:
    SeparateRequest(media_id="a", start_s=52, end_s=60, description="drum")
    with pytest.raises(ValueError, match="between 2 and 8"):
        SeparateRequest(media_id="a", start_s=40, end_s=60, description="drum")
    with pytest.raises(ValueError):
        SeparateRequest(media_id="a", start_s=55, end_s=61, description="drum")


def test_rotated_phone_video_reports_the_shape_it_displays_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def probe(rotation: dict) -> None:
        video = {"codec_type": "video", "width": 1920, "height": 1080, **rotation}
        payload = {"format": {"duration": "14"}, "streams": [video]}
        monkeypatch.setattr(
            "services.gateway.media.execute", lambda _args: json.dumps(payload).encode()
        )

    clip = tmp_path / "clip.mp4"
    probe({"side_data_list": [{"rotation": -90}]})
    tall = inspect_media(clip, "a", "clip.mp4")
    assert (tall.width, tall.height) == (1080, 1920)
    probe({"tags": {"rotate": "270"}})
    tall = inspect_media(clip, "a", "clip.mp4")
    assert (tall.width, tall.height) == (1080, 1920)
    probe({"side_data_list": [{"rotation": 180}]})
    wide = inspect_media(clip, "a", "clip.mp4")
    assert (wide.width, wide.height) == (1920, 1080)
    probe({})
    wide = inspect_media(clip, "a", "clip.mp4")
    assert (wide.width, wide.height) == (1920, 1080)


def source_image(client: TestClient) -> dict:
    response = client.post(
        "/api/media", files={"file": ("source.png", png(picture()), "image/png")}
    )
    assert response.status_code == 200
    return response.json()


def test_concept_variants() -> None:
    assert concept_variants("hand drum") == ["hand drum", "drum", "hand"]
    assert concept_variants("the beaded necklace") == ["the beaded necklace", "necklace", "beaded"]
    assert concept_variants("drum") == ["drum"]
    assert concept_variants("kid running laughing")[:2] == ["kid running laughing", "kid"]


def test_small_sam_masks_are_scaled_up_but_mismatched_ones_refused() -> None:
    sam = SimpleNamespace(decode_mask_to_raster=lambda mask: bytes(mask.width * mask.height))

    def record(mask: tuple[int, int], box: tuple[int, int, int, int]) -> SimpleNamespace:
        left, top, right, bottom = box
        return SimpleNamespace(
            mask=SimpleNamespace(width=mask[0], height=mask[1]),
            bounds=SimpleNamespace(left=left, top=top, right=right, bottom=bottom),
            confidence=0.5,
        )

    # SAM caps the long side at 1024 on big images: the same shape, smaller raster.
    found = MetaAdapter._positioned(sam, record((685, 1024), (61, 108, 1227, 1851)), (1280, 1920))
    assert found.alpha.size == (1166, 1743) and found.left == 61 and found.confidence == 0.5
    with pytest.raises(ValueError, match="geometry"):
        MetaAdapter._positioned(sam, record((500, 1024), (61, 108, 1227, 1851)), (1280, 1920))


def painted(size: tuple[int, int], box: tuple[int, int, int, int] | None) -> bytes:
    image = Image.new("RGBA", size, (255, 255, 255, 0))
    if box:
        image.paste((255, 255, 255, 255), box)
    return png(image)


def test_painted_mask_makes_a_cutout_and_records_how(tmp_path: Path) -> None:
    settings = Settings(
        mode="mock", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=False
    )
    with TestClient(create_app(settings)) as client:
        media = source_image(client)
        route = f"/api/media/{media['id']}/mask"
        # Painted at half the frame's resolution, as a capped browser canvas would be.
        fresh = client.post(
            route, files={"file": ("mask.png", painted((100, 100), (10, 20, 60, 70)), "image/png")}
        ).json()
        assert fresh["provenance"] == "Hand-drawn mask"
        cutout = Image.open(io.BytesIO(client.get(f"/api{fresh['cutout_url']}").content))
        assert cutout.size == (100, 100) and cutout.mode == "RGBA"
        edited = client.post(
            route,
            data={"base_cutout_id": fresh["cutout_id"]},
            files={"file": ("mask.png", painted((100, 100), (10, 20, 50, 60)), "image/png")},
        ).json()
        assert "hand edit" in edited["provenance"] and edited["cutout_id"] != fresh["cutout_id"]


@pytest.mark.parametrize(
    ("mask", "message"),
    [
        (painted((100, 100), None), "Paint over the object"),
        (painted((100, 100), (10, 10, 12, 12)), "Paint over the object"),
        (painted((100, 50), (10, 10, 60, 40)), "does not match this frame"),
    ],
)
def test_unusable_masks_are_refused_with_a_way_forward(
    tmp_path: Path, mask: bytes, message: str
) -> None:
    settings = Settings(
        mode="mock", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=False
    )
    with TestClient(create_app(settings)) as client:
        media = source_image(client)
        response = client.post(
            f"/api/media/{media['id']}/mask", files={"file": ("mask.png", mask, "image/png")}
        )
        assert response.status_code == 422 and message in response.json()["detail"]


def test_a_mask_for_a_picture_free_source_is_refused(tmp_path: Path) -> None:
    settings = Settings(
        mode="mock", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=False
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/media/{'a' * 32}/mask",
            files={"file": ("mask.png", painted((10, 10), None), "image/png")},
        )
        assert response.status_code in {404, 422}
