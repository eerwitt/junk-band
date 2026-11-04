"""Clean, score and save masks, and choose the sound window inside a kept stretch."""

import logging
from array import array
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat

from services.gateway.media import execute
from services.gateway.meta import FoundObject

logger = logging.getLogger(__name__)
LEVEL_RATE = 50
MAX_WINDOW_S = 8.0
PAPER_TOLERANCE = 30.0
# Measured on real generated pictures: true gaps are about 2 from the paper with texture under 2,
# painted white about 17 with texture about 5.
GAP_MAX_DISTANCE = 4.0
GAP_MAX_TEXTURE = 2.5
FILLER_WORDS = {"a", "an", "the", "of", "on", "in", "with", "and"}
UNREPORTED_CONFIDENCE = 0.7


def concept_variants(concept: str) -> list[str]:
    """The phrase as written, then its words, with likely nouns first and actions after."""
    words = [word for word in concept.split() if word.lower() not in FILLER_WORDS]
    if len(words) < 2:
        return [concept]
    backwards = list(reversed(words))
    nouns = [word for word in backwards if not word.lower().endswith("ing")]
    actions = [word for word in backwards if word.lower().endswith("ing")]
    return list(dict.fromkeys([concept, *nouns, *actions]))[:5]


def audio_levels(source: Path) -> list[float]:
    """Loudness per 20 ms, from the source's own soundtrack."""
    raw = execute(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "8000"]
        + ["-f", "s16le", "-"]
    )
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    hop = 8000 // LEVEL_RATE
    return [
        (sum(value * value for value in samples[start : start + hop]) / hop) ** 0.5
        for start in range(0, len(samples) - hop + 1, hop)
    ]


def best_window(levels: list[float], duration_s: float) -> tuple[float, float]:
    """The stretch with the most distinct sound events: sudden rises count more than volume."""
    length_s = min(MAX_WINDOW_S, duration_s)
    length = int(length_s * LEVEL_RATE)
    if not levels or len(levels) <= length:
        return 0.0, round(length_s, 2)
    peak = max(levels) or 1.0
    scores = [
        level / peak + 4 * max(0.0, level - previous) / peak
        for previous, level in zip([levels[0], *levels[:-1]], levels, strict=True)
    ]
    current = sum(scores[:length])
    best, best_start = current, 0
    for start in range(1, len(scores) - length + 1):
        current += scores[start + length - 1] - scores[start - 1]
        if current > best:
            best, best_start = current, start
    start_s = min(best_start / LEVEL_RATE, duration_s - length_s, 18.0)
    return round(start_s, 2), round(start_s + length_s, 2)


def window_within(levels: list[float], start_s: float, end_s: float) -> tuple[float, float]:
    """The best sound window inside the stretch someone chose to keep."""
    first = int(start_s * LEVEL_RATE)
    last = min(len(levels), int(end_s * LEVEL_RATE))
    offset, length = best_window(levels[first:last], end_s - start_s)
    return round(start_s + offset, 2), round(start_s + length, 2)


def mask_area(found: FoundObject) -> int:
    return int((np.asarray(found.alpha) >= 128).sum())


def _components(solid: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Label connected regions, returning the label map and each region's size."""
    labels = np.zeros(solid.shape, dtype=np.int32)
    sizes: list[int] = []
    height, width = solid.shape
    for row, column in zip(*np.nonzero(solid), strict=True):
        if labels[row, column]:
            continue
        sizes.append(0)
        current = len(sizes)
        labels[row, column] = current
        stack = [(int(row), int(column))]
        while stack:
            y, x = stack.pop()
            sizes[current - 1] += 1
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width and solid[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = current
                    stack.append((ny, nx))
    return labels, sizes


def paper_background_object(path: Path) -> FoundObject | None:
    """Lift a painted object off its plain paper, with no model. None if the paper is not plain."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    scale = min(1.0, 512 / max(rgb.size))
    small = rgb.resize((max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))))
    pixels = np.asarray(small).astype(np.float32)
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    paper = np.median(border, axis=0)
    spread = np.linalg.norm(border - paper, axis=1)
    if np.percentile(spread, 90) > PAPER_TOLERANCE:
        return None
    # Generated paper is very flat, so a tight match stops the cut leaking into pale paint.
    distance = np.linalg.norm(pixels - paper, axis=2)
    tolerance = float(np.clip(np.percentile(spread, 99) * 1.5, 12, PAPER_TOLERANCE))
    labels, sizes = _components(distance < tolerance)
    edges = {int(v) for v in np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])}
    enough = distance.size * 0.003

    # Paper reaches the edge of the picture, or shows through a real gap such as the middle of a
    # ring. An enclosed area only counts as a gap if it is that same flat paper: white paint, like
    # a shirt or a stripe, differs slightly and has some texture, and stays part of the object.
    def is_gap(label: int) -> bool:
        region = labels == label
        return bool(
            distance[region].mean() <= GAP_MAX_DISTANCE
            and pixels[region].std(axis=0).mean() <= GAP_MAX_TEXTURE
        )

    background = [
        index + 1
        for index, size in enumerate(sizes)
        if index + 1 in edges or (size >= enough and is_gap(index + 1))
    ]
    object_share = 1 - float(np.isin(labels, background).mean())
    if not 0.02 <= object_share <= 0.95:
        return None
    alpha = Image.fromarray(((~np.isin(labels, background)) * 255).astype(np.uint8))
    alpha = alpha.resize(rgb.size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(1))
    bounds = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None:
        return None
    return clean_mask(FoundObject(bounds[0], bounds[1], alpha.crop(bounds), None))


def clean_mask(found: FoundObject, keep_share: float = 0.3) -> FoundObject:
    """Drop stray islands far smaller than the main shape, such as a scrap of a nearby leg."""
    factor = max(1, max(found.alpha.size) // 128)
    small = found.alpha.resize(
        (max(1, found.alpha.width // factor), max(1, found.alpha.height // factor)),
        Image.Resampling.BILINEAR,
    )
    labels, sizes = _components(np.asarray(small) >= 128)
    if len(sizes) < 2:
        return found
    largest = max(sizes)
    kept = [index + 1 for index, size in enumerate(sizes) if size >= largest * keep_share]
    keep = Image.fromarray((np.isin(labels, kept) * 255).astype(np.uint8))
    # Grown slightly so scaling back up cannot shave the edge of what stays.
    keep = keep.resize(found.alpha.size, Image.Resampling.NEAREST).filter(ImageFilter.MaxFilter(5))
    alpha = ImageChops.darker(found.alpha, keep)
    bounds = alpha.getbbox()
    if bounds is None:
        return found
    return FoundObject(
        left=found.left + bounds[0],
        top=found.top + bounds[1],
        alpha=alpha.crop(bounds),
        confidence=found.confidence,
    )


def score_object(frame: Image.Image, found: FoundObject) -> float:
    """Prefer a confident, whole, usefully sized and sharp view of the object."""
    width, height = frame.size
    box = found.alpha.point(lambda value: 255 if value >= 128 else 0)
    bounds = box.getbbox()
    if bounds is None:
        return 0.0
    covered = ImageStat.Stat(box).mean[0] / 255 * box.width * box.height / (width * height)
    if covered < 0.005:
        size = 0.0
    elif covered < 0.03:
        size = (covered - 0.005) / 0.025
    elif covered <= 0.45:
        size = 1.0
    else:
        size = max(0.2, 1 - (covered - 0.45) / 0.55)
    left, top, right, bottom = (
        found.left + bounds[0],
        found.top + bounds[1],
        found.left + bounds[2],
        found.top + bounds[3],
    )
    # An object cut off by the edge of the picture is a poor portrait of it.
    cut_off = (left <= 1) + (top <= 1) + (right >= width - 1) + (bottom >= height - 1)
    whole = 1 - 0.2 * cut_off
    crop = frame.convert("L").crop(
        (found.left, found.top, found.left + box.width, found.top + box.height)
    )
    edges = ImageStat.Stat(crop.filter(ImageFilter.FIND_EDGES), box).mean[0]
    sharp = 0.6 + 0.4 * min(1.0, edges / 25)
    confidence = UNREPORTED_CONFIDENCE if found.confidence is None else found.confidence
    return confidence * size * whole * sharp


def rank_objects(
    frame: Path, time_s: float, found: list[FoundObject]
) -> list[tuple[float, float, Path, FoundObject]]:
    """Clean and score what was found in one frame. Slow, so run it off the event loop."""
    with Image.open(frame) as image:
        picture = image.convert("RGB")
    cleaned = [clean_mask(item) for item in found]
    return [(score_object(picture, item), time_s, frame, item) for item in cleaned]


def write_cutout(frame_path: Path, found: FoundObject, cutout: Path, mask: Path) -> None:
    """Save the cropped cutout, and the same mask on the whole canvas for later editing."""
    with Image.open(frame_path) as original:
        rgba = original.convert("RGBA")
    right, bottom = found.left + found.alpha.width, found.top + found.alpha.height
    cropped = rgba.crop((found.left, found.top, right, bottom))
    cropped.putalpha(ImageChops.darker(cropped.getchannel("A"), found.alpha))
    cropped.save(cutout, format="PNG")
    canvas = Image.new("L", rgba.size, 0)
    canvas.paste(found.alpha, (found.left, found.top))
    canvas.save(mask, format="PNG")


def mock_object(frame_path: Path) -> FoundObject:
    """Demo mode: an explicitly labelled rectangle, with no model involved."""
    with Image.open(frame_path) as image:
        width, height = image.size
    left, top = int(width * 0.15), int(height * 0.1)
    size = (int(width * 0.85) - left, int(height * 0.95) - top)
    return FoundObject(left=left, top=top, alpha=Image.new("L", size, 255), confidence=None)


def cutout_from_mask(frame_path: Path, mask_bytes: Path, cutout: Path, mask: Path) -> None:
    """Build a cutout from a mask painted in the browser, on the frame it was painted over."""
    with Image.open(frame_path) as image:
        size = image.size
    with Image.open(mask_bytes) as painted:
        ratio = (painted.width / painted.height) / (size[0] / size[1])
        if not 0.98 <= ratio <= 1.02:
            raise ValueError("That mask does not match this frame. Paint it again on this frame.")
        alpha = (
            painted.convert("RGBA").getchannel("A")
            if "A" in painted.getbands()
            else painted.convert("L")
        )
    alpha = alpha.resize(size, Image.Resampling.BILINEAR)
    bounds = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None or bounds[2] - bounds[0] < 8 or bounds[3] - bounds[1] < 8:
        raise ValueError("Paint over the object first. The mask is empty or too small to use.")
    write_cutout(
        frame_path,
        FoundObject(left=bounds[0], top=bounds[1], alpha=alpha.crop(bounds), confidence=None),
        cutout,
        mask,
    )
