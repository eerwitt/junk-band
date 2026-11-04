"""Rigid paper-limb extraction from actual SAM masks, retaining source coordinates.

No limbs or hidden body pixels are invented. Invalid segmentation is an explicit
failure; callers keep the original complete character for review/retry.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Literal, cast

from PIL import Image, ImageChops, ImageDraw
from pydantic import Field

from services.gateway.meta import FoundObject, MetaAdapter
from services.gateway.models import StrictModel

PartName = Literal["left_arm", "right_arm", "left_leg", "right_leg"]
PARTS: tuple[PartName, ...] = ("left_arm", "right_arm", "left_leg", "right_leg")
# SAM answers short noun phrases and returns nothing for long descriptive ones. One request finds
# both limbs of a kind, and their positions say which is which.
LIMBS: dict[str, tuple[tuple[str, ...], PartName, PartName]] = {
    "arm": (("arm", "arms", "paper arm"), "left_arm", "right_arm"),
    "leg": (("leg", "legs"), "left_leg", "right_leg"),
}


class RigPart(StrictModel):
    name: PartName
    file: str
    pivot: tuple[float, float]
    bounds: tuple[int, int, int, int]
    max_angle: float = Field(gt=0, le=0.5)


class CharacterRig(StrictModel):
    version: Literal[1] = 1
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    body_file: str
    parts: list[RigPart] = Field(min_length=4, max_length=4)
    provenance: Literal["SAM limb masks + rigid paper joints"] = (
        "SAM limb masks + rigid paper joints"
    )


def _count(mask: Image.Image) -> float:
    return sum(value * count for value, count in enumerate(mask.histogram())) / 255


def _layer(rgba: Image.Image, alpha: Image.Image) -> Image.Image:
    # Do not encode the complete hidden print in every limb PNG. Preserve every
    # visible source color, including antialiasing, and clear only invisible RGB.
    visible = alpha.point([0] + [255] * 255)
    layer = Image.composite(rgba, Image.new("RGBA", rgba.size), visible)
    layer.putalpha(alpha)
    return layer


def _mask_area(found: FoundObject) -> int:
    return sum(found.alpha.point(lambda value: 1 if value >= 128 else 0).histogram()[1:])


def _save_limb_mask(found: FoundObject, size: tuple[int, int], target: Path) -> None:
    canvas = Image.new("L", size, 0)
    canvas.paste(found.alpha, (found.left, found.top))
    mask = Image.new("RGBA", size, (255, 255, 255, 0))
    mask.putalpha(canvas)
    temporary = target.with_suffix(".tmp")
    mask.save(temporary, format="PNG")
    temporary.replace(target)


def assemble_rig(
    source: Path, masks: dict[PartName, Path], output: Path, prefix: str
) -> CharacterRig:
    """Validate all masks before writing any part; store layers on one shared canvas."""
    if not re.fullmatch(r"[a-f0-9]{32}", prefix):
        raise ValueError("Rig prefix must be a source-derived 32-character hash")
    (output / f"{prefix}-rig.json").unlink(missing_ok=True)
    if set(masks) != set(PARTS):
        raise ValueError("A complete rig needs both arms and both legs")
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    area = _count(alpha)
    if area < 16:
        raise ValueError("Cannot rig an empty character")
    used = alpha.getbbox()
    assert used is not None
    left, top, right, bottom = used
    center_x = (left + right) * 0.5
    height = bottom - top
    union = Image.new("L", rgba.size)
    layers: list[tuple[RigPart, Image.Image]] = []
    for name in PARTS:
        with Image.open(masks[name]) as segmented:
            if segmented.size != rgba.size:
                raise ValueError(f"{name}: limb mask must retain the complete character canvas")
            mask = ImageChops.darker(alpha, segmented.convert("RGBA").getchannel("A"))
        bounds = mask.getbbox()
        mass = _count(mask)
        if bounds is None or not area * 0.002 <= mass <= area * 0.24:
            raise ValueError(f"{name}: segmentation did not isolate a plausible limb")
        if _count(ImageChops.darker(union, mask)) > mass * 0.08:
            raise ValueError(f"{name}: limb masks overlap; refusing duplicated body pieces")
        x0, y0, x1, y1 = bounds
        cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
        if (name.startswith("left") and cx >= center_x) or (
            name.startswith("right") and cx <= center_x
        ):
            raise ValueError(f"{name}: mask is on the wrong side of the image")
        leg = name.endswith("leg")
        if leg and cy < top + height * 0.57:
            raise ValueError(f"{name}: leg mask includes too much of the main body")
        if not leg and not top + height * 0.12 <= cy <= top + height * 0.85:
            raise ValueError(f"{name}: arm mask is outside the body attachment range")
        # The proximal end comes from opaque pixels, never an image-box corner.
        # Legs hinge at their upper end; arms hinge at the inner end nearest torso.
        points = [
            (x, y)
            for y in range(y0, y1)
            for x in range(x0, x1)
            if cast(int, mask.getpixel((x, y))) >= 128
        ]
        if not points:
            raise ValueError(f"{name}: no opaque pixels for a paper joint")
        points.sort(key=(lambda p: p[1]) if leg else (lambda p: abs(p[0] - center_x)))
        proximal = points[: max(1, len(points) // 12)]
        pivot = (
            sum(p[0] + 0.5 for p in proximal) / len(proximal),
            sum(p[1] + 0.5 for p in proximal) / len(proximal),
        )
        part = RigPart(
            name=name,
            file=f"{prefix}-{name.replace('_', '-')}.png",
            pivot=(pivot[0] / rgba.width, pivot[1] / rgba.height),
            bounds=bounds,
            max_angle=0.20 if leg else 0.32,
        )
        layers.append((part, mask))
        union = ImageChops.lighter(union, mask)
    body_alpha = ImageChops.subtract(alpha, union)
    # Preserve the original print beneath each fastener for subpixel seam coverage.
    joints = Image.new("L", rgba.size)
    draw = ImageDraw.Draw(joints)
    radius = max(1.5, min(rgba.size) * 0.006)
    for part, _ in layers:
        px, py = part.pivot[0] * rgba.width, part.pivot[1] * rgba.height
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=255)
    body_alpha = ImageChops.lighter(body_alpha, ImageChops.darker(alpha, joints))
    output.mkdir(parents=True, exist_ok=True)
    body = _layer(rgba, body_alpha)
    body_file = f"{prefix}-body.png"
    body.save(output / body_file)
    for part, mask in layers:
        layer = _layer(rgba, mask)
        layer.save(output / part.file)
    rig = CharacterRig(
        width=rgba.width,
        height=rgba.height,
        body_file=body_file,
        parts=[part for part, _ in layers],
    )
    # Manifest is the completion marker, written only after every validated layer.
    temporary = output / f"{prefix}-rig.tmp"
    temporary.write_text(json.dumps(rig.model_dump(), indent=2), encoding="utf-8")
    temporary.replace(output / f"{prefix}-rig.json")
    return rig


async def segment_rig(
    adapter: MetaAdapter, source: Path, output: Path, prefix: str
) -> CharacterRig:
    """Two real SAM requests, one per limb kind; cached masks survive a failed part retry."""
    if not re.fullmatch(r"[a-f0-9]{32}", prefix):
        raise ValueError("Rig prefix must be a source-derived 32-character hash")
    with Image.open(source) as original:
        if max(original.size) > 2048:
            raise ValueError("Rig source must fit within a 2048-pixel canvas")
        low, high = cast("tuple[int, int]", original.convert("RGBA").getchannel("A").getextrema())
        if low >= 128 or high < 128:
            raise ValueError("Rig source needs a usable alpha matte before limb segmentation")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{prefix}-rig.json").unlink(missing_ok=True)
    with Image.open(source) as original:
        size = original.size
    mask_path = {name: output / f"{prefix}-{name.replace('_', '-')}-mask.png" for name in PARTS}
    # Sequential calls bound account concurrency; no duplicate image-generation request.
    for prompts, left_name, right_name in LIMBS.values():
        if mask_path[left_name].exists() and mask_path[right_name].exists():
            continue
        found: list[FoundObject] = []
        for prompt in prompts:
            found = await adapter.find_objects(source, prompt)
            if len(found) >= 2:
                break
        if len(found) < 2:
            raise ValueError(f"{left_name}: SAM did not find both {prompts[0]}s on this character")
        pair = sorted(found, key=_mask_area, reverse=True)[:2]
        left, right = sorted(pair, key=lambda item: item.left + item.alpha.width / 2)
        _save_limb_mask(left, size, mask_path[left_name])
        _save_limb_mask(right, size, mask_path[right_name])
    masks: dict[PartName, Path] = mask_path
    try:
        return await asyncio.to_thread(assemble_rig, source, masks, output, prefix)
    except ValueError as error:
        # A provider can successfully return the wrong region. Do not trap a
        # retry behind that cached bad mask; retain the other successful parts.
        for name, target in masks.items():
            if str(error).startswith(f"{name}:"):
                target.unlink(missing_ok=True)
                break
        raise
