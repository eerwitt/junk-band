import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops, ImageDraw

from services.gateway.meta import FoundObject, MetaAdapter
from services.gateway.models import SegmentRequest
from services.gateway.rigging import PartName, assemble_rig, segment_rig


def rig_fixture(root: Path) -> tuple[Path, dict[PartName, Path]]:
    """Technical layer fixture, never shown as generated character artwork."""
    source = Image.new("RGBA", (200, 240), (240, 225, 200, 0))
    painter = ImageDraw.Draw(source)
    painter.rectangle((60, 25, 140, 150), fill="orange")
    boxes: dict[PartName, tuple[int, int, int, int]] = {
        "left_arm": (35, 65, 65, 100),
        "right_arm": (135, 65, 165, 100),
        "left_leg": (70, 145, 85, 218),
        "right_leg": (115, 145, 130, 218),
    }
    masks: dict[PartName, Path] = {}
    for name, bounds in boxes.items():
        painter.rectangle(bounds, fill="tan")
        mask = Image.new("RGBA", source.size)
        ImageDraw.Draw(mask).rectangle(bounds, fill="white")
        masks[name] = root / f"{name}.png"
        mask.save(masks[name])
    path = root / "source.png"
    source.save(path)
    return path, masks


def test_rig_preserves_print_and_rest_pose_silhouette(tmp_path: Path) -> None:
    source, masks = rig_fixture(tmp_path)
    before = source.read_bytes()
    rig = assemble_rig(source, masks, tmp_path / "rig", "a" * 32)
    assert source.read_bytes() == before
    assert len(rig.parts) == 4 and (rig.width, rig.height) == (200, 240)
    original = Image.open(source).convert("RGBA")
    body = Image.open(tmp_path / "rig" / rig.body_file).convert("RGBA")
    union = body.getchannel("A")
    for part in rig.parts:
        layer = Image.open(tmp_path / "rig" / part.file).convert("RGBA")
        assert layer.size == original.size
        for point in [
            (x, y)
            for y in range(layer.height)
            for x in range(layer.width)
            if layer.getpixel((x, y))[3] > 0
        ]:
            assert layer.getpixel(point)[:3] == original.getpixel(point)[:3]
        assert 0 < part.pivot[0] < 1 and 0 < part.pivot[1] < 1
        if part.name.endswith("leg"):
            assert part.pivot[1] * rig.height < part.bounds[1] + 8
            assert part.max_angle <= 0.20
        union = ImageChops.lighter(union, layer.getchannel("A"))
    assert ImageChops.difference(union, original.getchannel("A")).getbbox() is None
    for point in [
        (x, y)
        for y in range(body.height)
        for x in range(body.width)
        if body.getpixel((x, y))[3] > 0
    ]:
        assert body.getpixel(point)[:3] == original.getpixel(point)[:3]
    assert body.getpixel((0, 0)) == (0, 0, 0, 0), "Invisible print must not bloat each layer PNG"
    assert (tmp_path / "rig" / ("a" * 32 + "-rig.json")).exists()


@pytest.mark.parametrize("problem", ["missing", "duplicate", "cropped", "empty", "wrong_side"])
def test_invalid_rig_masks_never_publish_completion(tmp_path: Path, problem: str) -> None:
    source, masks = rig_fixture(tmp_path)
    if problem == "missing":
        del masks["left_arm"]
    elif problem == "duplicate":
        masks["left_leg"] = masks["left_arm"]
    elif problem == "cropped":
        Image.new("RGBA", (10, 10), "white").save(masks["left_arm"])
    elif problem == "empty":
        Image.new("RGBA", (200, 240)).save(masks["left_arm"])
    else:
        masks["left_arm"], masks["right_arm"] = masks["right_arm"], masks["left_arm"]
    with pytest.raises(ValueError):
        assemble_rig(source, masks, tmp_path / "rig", "a" * 32)
    assert not list((tmp_path / "rig").glob("*-rig.json"))


def found_in(path: Path) -> FoundObject:
    with Image.open(path) as mask:
        alpha = mask.convert("RGBA").getchannel("A")
    bounds = alpha.getbbox()
    assert bounds is not None
    return FoundObject(bounds[0], bounds[1], alpha.crop(bounds), None)


def test_rig_retry_reuses_successful_sam_masks(tmp_path: Path) -> None:
    source, masks = rig_fixture(tmp_path)
    calls: list[str] = []

    class FixtureAdapter:
        async def find_objects(self, _source: Path, concept: str) -> list[FoundObject]:
            calls.append(concept)
            if len(calls) == 2:
                raise RuntimeError("explicit fixture failure")
            return [found_in(masks[f"right_{concept}"]), found_in(masks[f"left_{concept}"])]  # type: ignore[index]

    adapter = FixtureAdapter()
    with pytest.raises(RuntimeError):
        asyncio.run(segment_rig(adapter, source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]
    assert not list((tmp_path / "rig").glob("*-rig.json"))
    rig = asyncio.run(segment_rig(adapter, source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]
    assert calls == ["arm", "leg", "leg"], "Found arms must survive a retry without a new request"
    assert len(rig.parts) == 4
    names = {part.name: part.bounds for part in rig.parts}
    assert names["left_arm"][0] < names["right_arm"][0], "Position decides which limb is which"


def test_semantically_bad_cached_mask_is_replaced_on_retry(tmp_path: Path) -> None:
    source, masks = rig_fixture(tmp_path)
    calls: list[str] = []

    class FixtureAdapter:
        async def find_objects(self, _source: Path, concept: str) -> list[FoundObject]:
            calls.append(concept)
            # First attempt at legs returns the arms: high on the body, so not plausibly legs.
            kind = "arm" if concept == "leg" and calls.count("leg") == 1 else concept
            return [found_in(masks[f"left_{kind}"]), found_in(masks[f"right_{kind}"])]  # type: ignore[index]

    adapter = FixtureAdapter()
    with pytest.raises(ValueError):
        asyncio.run(segment_rig(adapter, source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]
    rig = asyncio.run(segment_rig(adapter, source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]
    assert len(rig.parts) == 4 and calls.count("leg") == 2


def test_one_limb_found_tries_other_wordings_then_says_so(tmp_path: Path) -> None:
    source, masks = rig_fixture(tmp_path)
    calls: list[str] = []

    class FixtureAdapter:
        async def find_objects(self, _source: Path, concept: str) -> list[FoundObject]:
            calls.append(concept)
            return [found_in(masks["left_arm"])]

    with pytest.raises(ValueError, match="did not find both"):
        asyncio.run(segment_rig(FixtureAdapter(), source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]
    assert calls == ["arm", "arms", "paper arm"]


def test_rig_needs_alpha_before_any_provider_call(tmp_path: Path) -> None:
    source = tmp_path / "opaque.png"
    Image.new("RGB", (200, 240), "orange").save(source)
    # A non-adapter object ensures validation happens before any paid SAM call.
    with pytest.raises(ValueError, match="alpha matte"):
        asyncio.run(segment_rig(object(), source, tmp_path / "rig", "a" * 32))  # type: ignore[arg-type]


def test_sam_layer_keeps_source_coordinates_and_existing_alpha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Image.new("RGBA", (20, 20), "orange")
    original.putpixel((4, 3), (255, 100, 0, 0))
    source = tmp_path / "source.png"
    original.save(source)

    class Record:
        object_id = "1"
        revision = 1
        mask = SimpleNamespace(width=4, height=5)
        bounds = SimpleNamespace(left=3.0, top=2.0, right=7.0, bottom=7.0)

    async def final_result() -> SimpleNamespace:
        return SimpleNamespace(
            records=[Record()], diagnostics=[], outcome=SimpleNamespace(status="completed")
        )

    async def close() -> None:
        pass

    async def create(**_kwargs: object) -> object:
        return object()

    parser = SimpleNamespace(
        SegmentationMaskRecord=Record,
        decode_mask_to_raster=lambda _: [1] * 20,
        image_segmentation_format=lambda: object(),
        parse_responses_stream=lambda *_: SimpleNamespace(final_result=final_result, aclose=close),
    )
    monkeypatch.setattr("services.gateway.meta.import_module", lambda _: parser)
    adapter = object.__new__(MetaAdapter)
    adapter.client = SimpleNamespace(responses=SimpleNamespace(create=create))  # type: ignore[assignment]
    layer_path = tmp_path / "layer.tmp"
    asyncio.run(adapter.segment_layer(source, layer_path, "paper arm"))
    layer = Image.open(layer_path)
    assert layer.size == original.size and layer.format == "PNG"
    assert layer.getchannel("A").getbbox() == (3, 2, 7, 7)
    assert layer.getpixel((4, 3))[3] == 0, "SAM must not fill an existing transparent source hole"
    crop_path = tmp_path / "crop.png"
    asyncio.run(
        adapter.segment(
            source, crop_path, SegmentRequest(media_id="fixture", frame_s=0, concept="object")
        )
    )
    assert Image.open(crop_path).size == (4, 5), "Normal cutout behavior must stay cropped"
    assert Image.open(crop_path).getpixel((1, 1))[3] == 0, (
        "Normal cutouts must also retain source holes"
    )
