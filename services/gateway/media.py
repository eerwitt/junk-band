import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from services.gateway.models import DURATION_SLACK_S, MAX_SOURCE_S, Media

logger = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = 16_000_000
ALLOWED_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# Past this, a filmstrip reads only keyframes, so long clips cannot run into the ffmpeg time limit.
FILMSTRIP_ALL_FRAMES_S = 20.0


def execute(args: list[str]) -> bytes:
    completed = subprocess.run(args, check=True, capture_output=True, timeout=60)
    return completed.stdout


def _rotation(video: dict[str, Any]) -> float:
    for item in video.get("side_data_list", []):
        if "rotation" in item:
            return float(item["rotation"])
    return float(video.get("tags", {}).get("rotate", 0))


def inspect_media(path: Path, media_id: str, filename: str) -> Media:
    if path.suffix in IMAGE_EXTENSIONS:
        with Image.open(path) as image:
            # PNG EXIF access may load/close its decoder; verify before that read.
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            orientation = image.getexif().get(274, 1)
        if orientation in {5, 6, 7, 8}:
            width, height = height, width
        if width > 4096 or height > 4096:
            raise ValueError("Images must be no larger than 4096 pixels per side")
        return Media(
            id=media_id,
            duration_s=0,
            width=width,
            height=height,
            audio_present=False,
            filename=filename,
        )
    info: dict[str, Any] = json.loads(
        execute(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
        )
    )
    duration = float(info["format"]["duration"])
    if not 2 <= duration <= MAX_SOURCE_S + DURATION_SLACK_S:
        raise ValueError(
            f"Media must be 2 to {MAX_SOURCE_S:.0f} seconds long. Trim it before importing."
        )
    streams = info["streams"]
    video: dict[str, Any] = next(
        (stream for stream in streams if stream["codec_type"] == "video"), {}
    )
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    # Phones store upright video sideways plus a rotation. Report the shape it displays at, which
    # is also what browsers show and what frame extraction produces.
    if abs(_rotation(video)) % 180 == 90:
        width, height = height, width
    # Downscale during frame extraction; audio and original timestamps stay unchanged.
    logger.info(
        "Inspected source id=%s duration=%.3f size=%sx%s", media_id, duration, width, height
    )
    return Media(
        id=media_id,
        duration_s=duration,
        width=width,
        height=height,
        audio_present=any(s["codec_type"] == "audio" for s in streams),
        filename=filename,
    )


def extract_audio(source: Path, target: Path, start: float, end: float) -> None:
    execute(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-t",
            str(end - start),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
    )


def extract_filmstrip(
    source: Path, target: Path, duration_s: float, count: int, start_s: float = 0
) -> None:
    """One image of evenly spaced frames side by side, decoded once. Rotation is applied.

    `duration_s` is the length of the stretch to show, beginning at `start_s`.
    """
    execute(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            *(["-skip_frame", "nokey"] if duration_s > FILMSTRIP_ALL_FRAMES_S else []),
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{duration_s:.3f}",
            "-i",
            str(source),
            "-vf",
            f"fps={count + 1}/{duration_s:.3f},scale=-2:120,tile={count}x1",
            "-frames:v",
            "1",
            "-q:v",
            "5",
            str(target),
        ]
    )


def extract_frame(source: Path, target: Path, frame_s: float) -> None:
    if source.suffix in IMAGE_EXTENSIONS:
        with Image.open(source) as image:
            ImageOps.exif_transpose(image).convert("RGBA").save(target)
    else:
        execute(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-ss",
                str(frame_s),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1280,iw)':-2",
                str(target),
            ]
        )
