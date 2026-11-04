"""Turn one rough selection into an object: describe it, then let SAM find exactly that."""

import asyncio
import hashlib
import logging
import random
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from openai import APIError
from PIL import Image, ImageDraw
from pydantic import ValidationError

from services.gateway.extras import SceneObject, describe_selection
from services.gateway.media import extract_frame
from services.gateway.meta import FoundObject, MetaAdapter, NoObjectMatched
from services.gateway.models import Media, Selection, SelectionRequest
from services.gateway.repository import Repository
from services.gateway.selection import (
    audio_levels,
    clean_mask,
    concept_variants,
    rank_objects,
    window_within,
    write_cutout,
)

logger = logging.getLogger(__name__)
CARD_LONG_SIDE = 1024
CARD_PADDING = 0.08


def torn_edge(
    start: tuple[float, float], end: tuple[float, float], rng: random.Random, reach: float
) -> list[tuple[float, float]]:
    """Points along one side of a card: a slow wander with sharper nicks, like a hand tear."""
    length = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    steps = max(4, int(length / max(2.0, reach * 0.8)))
    normal = (-(end[1] - start[1]), end[0] - start[0])
    size = (normal[0] ** 2 + normal[1] ** 2) ** 0.5 or 1.0
    normal = (normal[0] / size, normal[1] / size)
    drift = 0.0
    wander = 0.0
    points = []
    for index in range(steps):
        share = index / steps
        wander = 0.96 * wander + rng.uniform(-reach, reach) * 0.28
        drift = 0.55 * drift + rng.uniform(-reach, reach) * 0.5 + wander
        if rng.random() < 0.06:
            drift -= rng.uniform(0.4, 1.1) * reach
        points.append(
            (
                start[0] + (end[0] - start[0]) * share + normal[0] * drift,
                start[1] + (end[1] - start[1]) * share + normal[1] * drift,
            )
        )
    return points


def torn_outline(
    box: tuple[float, float, float, float], rng: random.Random, reach: float
) -> list[tuple[float, float]]:
    left, top, right, bottom = box
    corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
    outline: list[tuple[float, float]] = []
    for index, corner in enumerate(corners):
        outline += torn_edge(corner, corners[(index + 1) % 4], rng, reach)
    return outline


def torn_card(
    frame_path: Path,
    mask_path: Path,
    bounds: tuple[int, int, int, int],
    target: Path,
    seed: str,
) -> None:
    """Only the selected object as it looks in the video, on a torn scrap of white paper."""
    with Image.open(frame_path) as image:
        picture = image.convert("RGB").crop(bounds)
    with Image.open(mask_path) as image:
        selected = image.convert("L").crop(bounds)
    picture.thumbnail((CARD_LONG_SIDE, CARD_LONG_SIDE))
    selected = selected.resize(picture.size, Image.Resampling.LANCZOS)
    rng = random.Random(seed)
    short = min(picture.size)
    margin = max(8, round(short * 0.07))
    reach = max(2.0, short * 0.016)
    width, height = picture.width + margin * 2, picture.height + margin * 2
    scale = 2
    outer = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(outer).polygon(
        [
            (x * scale, y * scale)
            for x, y in torn_outline(
                (reach, reach, width - reach, height - reach), rng, reach * 0.9
            )
        ],
        fill=255,
    )
    card = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    card.paste(picture, (margin, margin), selected)
    card.putalpha(outer.resize((width, height), Image.Resampling.LANCZOS))
    card.save(target, format="PNG")


def card_bounds(
    size: tuple[int, int], bounds: tuple[int, int, int, int], padding: float = 0.0
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    pad_x, pad_y = (right - left) * padding, (bottom - top) * padding
    return (
        max(0, int(left - pad_x)),
        max(0, int(top - pad_y)),
        min(size[0], max(left + 1, int(right + pad_x))),
        min(size[1], max(top + 1, int(bottom + pad_y))),
    )


def overlap(found: FoundObject, box: tuple[int, int, int, int]) -> float:
    """How well a match agrees with the rough selection, from 0 to 1."""
    left, top = max(found.left, box[0]), max(found.top, box[1])
    right = min(found.left + found.alpha.width, box[2])
    bottom = min(found.top + found.alpha.height, box[3])
    shared = max(0, right - left) * max(0, bottom - top)
    area = found.alpha.width * found.alpha.height + (box[2] - box[0]) * (box[3] - box[1]) - shared
    return shared / area if area > 0 else 0.0


def choose(
    ranked: list[tuple[float, float, Path, FoundObject]],
    box: tuple[int, int, int, int] | None,
) -> FoundObject | None:
    usable = [item for item in ranked if item[0] > 0]
    if box is None:
        return max(usable, key=lambda item: item[0])[3] if usable else None
    near = [item for item in usable if overlap(item[3], box) > 0.05]
    return max(near, key=lambda item: overlap(item[3], box))[3] if near else None


async def pick(
    key: str,
    repository: Repository,
    owner: str,
    info: Media,
    source: Path,
    request: SelectionRequest,
    before_paid: Callable[[], Awaitable[None]] | None = None,
) -> Selection:
    """At most one description and two SAM requests per selection."""
    digest = hashlib.sha256(
        f"{request.model_dump_json()}:{bool(key)}:pick-v2".encode()
    ).hexdigest()[:32]
    record = repository.path(owner, f"{digest}-pick.json")
    if record.exists():
        return Selection.model_validate(repository.read(owner, record.name))
    if key and before_paid:
        await before_paid()
    frame = repository.path(owner, f"{digest}-frame.png")
    await asyncio.to_thread(extract_frame, source, frame, request.frame_s)
    with Image.open(frame) as image:
        size = image.size
    box = None
    if request.box:
        x0, y0, x1, y1 = request.box
        box = card_bounds(
            size, (int(x0 * size[0]), int(y0 * size[1]), int(x1 * size[0]), int(y1 * size[1]))
        )
    sound_start, sound_end = request.start_s, request.end_s
    if info.audio_present:
        levels = await asyncio.to_thread(audio_levels, source)
        sound_start, sound_end = window_within(levels, request.start_s, request.end_s)

    named = SceneObject(name=request.concept, sound=request.concept) if request.concept else None
    if named is None and key and box:
        try:
            named = await describe_selection(key, frame, box)
        except (APIError, httpx.HTTPError, ValidationError, ValueError) as error:
            logger.warning("Could not describe a selection: %s", type(error).__name__)
    found = None
    how = "Rough selection · no AI cutout"
    if key and named:
        adapter = MetaAdapter(key)
        ranked = await asyncio.to_thread(
            rank_objects, frame, request.frame_s, await adapter.find_objects(frame, named.name)
        )
        found = choose(ranked, box)
        if found is None and request.concept:
            for wording in concept_variants(named.name)[1:2]:
                ranked = await asyncio.to_thread(
                    rank_objects, frame, request.frame_s, await adapter.find_objects(frame, wording)
                )
                found = choose(ranked, box)
        if found is not None:
            how = f"SAM 3.1 alpha mask · found “{named.name}”"
    if found is None and key and box:
        # The name did not lead to this spot, so ask SAM about the box itself.
        try:
            pixels = await MetaAdapter(key).find_box(frame, box)
        except (NoObjectMatched, ValueError):
            pixels = None
        if pixels is not None:
            found = await asyncio.to_thread(clean_mask, pixels)
            how = "SAM 3.1 alpha mask · from the selected box"
    if found is None and box is None:
        raise ValueError(
            f"Nothing matched “{request.concept}” on this frame. Try another word, or drag a box."
        )
    if found is None and box is not None:
        found = FoundObject(
            left=box[0],
            top=box[1],
            alpha=Image.new("L", (box[2] - box[0], box[3] - box[1]), 255),
            confidence=None,
        )
    assert found is not None
    cutout = repository.path(owner, f"{digest}-cutout.png")
    mask = repository.path(owner, f"{digest}-mask.png")
    card = repository.path(owner, f"{digest}-card.png")
    await asyncio.to_thread(write_cutout, frame, found, cutout, mask)
    # The card fits what was selected, so no empty paper is left from a loose rough box.
    whole = (found.left, found.top, found.left + found.alpha.width, found.top + found.alpha.height)
    area = card_bounds(size, whole, CARD_PADDING)
    await asyncio.to_thread(torn_card, frame, mask, area, card, digest)
    name = named.name if named else "my object"
    selection = Selection(
        cutout_id=digest,
        cutout_url=f"/assets/{cutout.name}",
        mask_url=f"/assets/{mask.name}",
        card_url=f"/assets/{card.name}",
        frame_s=request.frame_s,
        name=name,
        sound=named.sound if named else "",
        sound_start_s=sound_start,
        sound_end_s=sound_end,
        provenance=how,
    )
    repository.write(owner, record.name, selection.model_dump())
    return selection
