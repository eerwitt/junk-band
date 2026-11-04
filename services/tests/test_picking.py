import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.extras import SceneObject
from services.gateway.meta import FoundObject, MetaAdapter, NoObjectMatched
from services.gateway.modal_bridge import note_gpu_wait
from services.gateway.picking import card_bounds, overlap, torn_card
from services.gateway.selection import LEVEL_RATE, window_within


def png() -> bytes:
    stream = io.BytesIO()
    Image.effect_noise((200, 200), 60).convert("RGB").save(stream, format="PNG")
    return stream.getvalue()


def square(left: int, top: int, size: int) -> FoundObject:
    return FoundObject(left, top, Image.new("L", (size, size), 255), None)


def live(tmp_path: Path) -> Settings:
    return Settings(mode="live", data_dir=tmp_path, session_secret="x" * 40, meta_key="k")


def mock(tmp_path: Path) -> Settings:
    return Settings(
        mode="mock", data_dir=tmp_path, session_secret="x" * 40, meta_key="", modal_enabled=False
    )


def upload(client: TestClient) -> dict:
    return client.post("/api/media", files={"file": ("still.png", png(), "image/png")}).json()


BOX = [0.1, 0.1, 0.5, 0.5]


def select(client: TestClient, media: dict, **extra: object) -> object:
    body = {"media_id": media["id"], "frame_s": 0, "start_s": 0, "end_s": 0, "box": BOX, **extra}
    return client.post("/api/selections", json=body)


class Calls:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, found: dict[str, list[FoundObject]]
    ) -> None:
        self.described = 0
        self.searched: list[str] = []
        self.boxes = 0

        async def describe(_key: str, _frame: Path, _box: object) -> SceneObject:
            self.described += 1
            return SceneObject(name="hand drum", sound="drum hits")

        async def find(_self: MetaAdapter, _frame: Path, concept: str) -> list[FoundObject]:
            self.searched.append(concept)
            return found.get(concept, [])

        async def box(_self: MetaAdapter, _frame: Path, _box: object) -> FoundObject:
            self.boxes += 1
            raise NoObjectMatched("nothing")

        monkeypatch.setattr("services.gateway.picking.describe_selection", describe)
        monkeypatch.setattr(MetaAdapter, "find_objects", find)
        monkeypatch.setattr(MetaAdapter, "find_box", box)


def test_one_selection_costs_one_description_and_one_sam_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, {"hand drum": [square(30, 30, 60)]})
    with TestClient(create_app(live(tmp_path))) as client:
        media = upload(client)
        result = select(client, media).json()
        assert result["name"] == "hand drum" and result["sound"] == "drum hits"
        assert "“hand drum”" in result["provenance"]
        assert (calls.described, len(calls.searched), calls.boxes) == (1, 1, 0)
        for url in (result["cutout_url"], result["mask_url"], result["card_url"]):
            assert client.get("/api" + url).status_code == 200
        assert select(client, media).json() == result, "The same box is reused, not paid for again"
        assert (calls.described, len(calls.searched)) == (1, 1)


def test_the_match_nearest_the_box_wins_over_a_bigger_one_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Calls(monkeypatch, {"hand drum": [square(120, 120, 75), square(30, 30, 50)]})
    with TestClient(create_app(live(tmp_path))) as client:
        result = select(client, upload(client)).json()
        cutout = Image.open(io.BytesIO(client.get("/api" + result["cutout_url"]).content))
    assert cutout.size == (50, 50)


def test_a_box_with_no_match_falls_back_to_a_rough_selection_at_most_two_sam_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, {})
    with TestClient(create_app(live(tmp_path))) as client:
        result = select(client, upload(client)).json()
    assert len(calls.searched) + calls.boxes == 2
    assert "Rough selection" in result["provenance"], "Never a dead end, and labelled as what it is"


def test_describing_on_a_frame_uses_the_words_and_says_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, {"drum": [square(30, 30, 60)]})
    with TestClient(create_app(live(tmp_path))) as client:
        media = upload(client)
        found = select(client, media, box=None, concept="hand drum").json()
        assert calls.searched == ["hand drum", "drum"] and calls.described == 0
        assert found["name"] == "hand drum"
        missed = select(client, media, box=None, concept="unicorn")
    assert missed.status_code == 422 and "unicorn" in missed.json()["detail"]


def test_demo_selection_is_labelled_and_makes_no_ai_request(tmp_path: Path) -> None:
    with TestClient(create_app(mock(tmp_path))) as client:
        result = select(client, upload(client)).json()
    assert "Rough selection" in result["provenance"]


def test_torn_card_shows_only_the_selection_on_white_with_an_uneven_edge(tmp_path: Path) -> None:
    frame, mask, card = tmp_path / "frame.png", tmp_path / "mask.png", tmp_path / "card.png"
    Image.new("RGB", (400, 300), (10, 120, 200)).save(frame)
    selected = Image.new("L", (400, 300), 0)
    selected.paste(255, (150, 100, 250, 200))
    selected.save(mask)
    torn_card(frame, mask, (50, 50, 350, 250), card, "seed")
    with Image.open(card) as image:
        rgba = image.convert("RGBA")
    assert rgba.width > 300 and rgba.height > 200, "A paper rim surrounds the picture"
    assert rgba.getpixel((0, 0))[3] == 0, "Corners are torn away"
    middle = rgba.getpixel((rgba.width // 2, rgba.height // 2))
    assert middle == (10, 120, 200, 255), "The selection keeps its real colours"
    beside = rgba.getpixel((rgba.width // 2 - 80, rgba.height // 2))
    assert beside == (255, 255, 255, 255), "Everything else in the frame is gone, leaving white"
    top_edge = [
        next(y for y in range(rgba.height) if rgba.getpixel((x, y))[3] > 128)
        for x in range(40, rgba.width - 40, 8)
    ]
    assert len(set(top_edge)) > 2, "The edge wanders rather than running straight"
    first = card.read_bytes()
    torn_card(frame, mask, (50, 50, 350, 250), card, "seed")
    assert card.read_bytes() == first, "The same selection tears the same way"


def test_box_helpers() -> None:
    assert overlap(square(0, 0, 10), (0, 0, 10, 10)) == 1
    assert overlap(square(0, 0, 10), (50, 50, 60, 60)) == 0
    assert card_bounds((100, 100), (10, 10, 20, 20), 0.5) == (5, 5, 25, 25)
    assert card_bounds((100, 100), (0, 0, 100, 100), 0.5) == (0, 0, 100, 100)


def test_selecting_warms_the_worker_only_when_there_is_sound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warmed: list[bool] = []

    class Bridge:
        def __init__(self, *_args: object) -> None:
            pass

        async def warm(self) -> None:
            warmed.append(True)

        async def unavailable_reason(self) -> None:
            return None

    Calls(monkeypatch, {"hand drum": [square(30, 30, 60)]})
    monkeypatch.setattr("services.gateway.modal_bridge.LocalModalSeparator", Bridge)
    settings = Settings(
        mode="live", data_dir=tmp_path, session_secret="x" * 40, meta_key="k", modal_enabled=True
    )
    with TestClient(create_app(settings)) as client:
        select(client, upload(client))
    assert warmed == [], "A still image has no sound, so nothing needs waking"
    metrics = note_gpu_wait({"container_started_unix": 130.04, "model": "m"}, 100.0)
    assert metrics == {"model": "m", "waited_for_gpu_s": 30.0}
    assert note_gpu_wait({"container_started_unix": 90.0}, 100.0) == {"waited_for_gpu_s": 0.0}


def test_the_sound_window_stays_inside_the_kept_stretch() -> None:
    levels = [0.1] * (LEVEL_RATE * 20)
    for second in range(1, 8):
        levels[second * LEVEL_RATE] = 1.0  # The busiest part is before the stretch.
    assert window_within(levels, 10, 16) == (10, 16), "A short stretch is used whole"
    start, end = window_within(levels, 9, 20)
    assert 9 <= start and end <= 20 and end - start == 8
    assert window_within([], 3, 9) == (3, 9)


def test_filmstrip_is_a_single_cached_private_image(tmp_path: Path) -> None:
    source = Path("public/demo-source.mp4")
    with TestClient(create_app(mock(tmp_path))) as client:
        media = client.post(
            "/api/media", files={"file": ("demo.mp4", source.read_bytes(), "video/mp4")}
        ).json()
        strip = client.get(f"/api/media/{media['id']}/filmstrip", params={"count": 6})
        assert strip.status_code == 200, strip.text
        assert "no-store" in strip.headers["cache-control"]
        with Image.open(io.BytesIO(strip.content)) as image:
            assert image.width > image.height * 3, "Six frames side by side"
        over = client.get(f"/api/media/{media['id']}/filmstrip", params={"count": 999})
        assert over.status_code == 422
        part = client.get(
            f"/api/media/{media['id']}/filmstrip",
            params={"count": 6, "start_s": 1, "end_s": 2},
        )
        assert part.status_code == 200, part.text
        assert part.content != strip.content, "A stretch shows its own frames"
        outside = client.get(
            f"/api/media/{media['id']}/filmstrip",
            params={"count": 6, "start_s": 5000},
        )
        assert outside.status_code == 422
