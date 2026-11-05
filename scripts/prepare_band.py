"""Make the base band's shipped sounds and pictures. Run by hand; the results are committed.

Sounds come from VCSL and Kenney, both CC0, downloaded beforehand into --source:
  <source>/vcsl/<name>.wav  <source>/kenney/digital/*.mp3  <source>/kenney/interface/*.wav

Pictures need MODEL_API_KEY and cost $0.01 each. Existing pictures are kept unless --repaint.
"""

import argparse
import asyncio
import base64
import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.gateway.selection import paper_background_object, write_cutout  # noqa: E402

logger = logging.getLogger("junk.band")
ROOT = Path(__file__).resolve().parents[1]
SOUNDS = ROOT / "public" / "sounds"
PICTURES = ROOT / "public" / "band"
BAND_STYLE = ROOT / "services" / "gateway" / "assets" / "band-style.png"
LONGEST_SIDE = 512
SAMPLE_RATE = 44100
PEAK_DB = -3.0
FADE_S = 0.04

# name: (source file, seconds kept)
SOUND_FILES = {
    "kick": ("vcsl/kick.wav", 0.6),
    "snare": ("vcsl/snare.wav", 0.5),
    "hat": ("vcsl/hat.wav", 0.2),
    "clap": ("vcsl/clap.wav", 0.4),
    "bass": ("vcsl/bass.wav", 1.2),
    "keys": ("vcsl/keys.wav", 1.6),
    "marimba": ("vcsl/marimba.wav", 1.0),
    "glock": ("vcsl/glock.wav", 1.4),
    "sub": ("vcsl/sub.wav", 1.4),
    "organ": ("vcsl/organ.wav", 2.4),
    "didge": ("vcsl/didge.wav", 0.5),
    "flute": ("vcsl/flute.wav", 1.1),
    "laser": ("kenney/digital/laser4.mp3", 0.5),
    "powerup": ("kenney/digital/powerUp7.mp3", 0.8),
    "buzzer": ("kenney/interface/error_004.wav", 0.6),
}
PICTURE_SUBJECTS = {
    "kick": "a big round bass drum, seen from the front",
    "snare": "a snare drum",
    "hat": "a pair of hi-hat cymbals on a stand",
    "clap": "a pair of big paper hands in the middle of a clap",
    "bass": "a chunky electric bass guitar, standing upright",
    "keys": "a small retro synthesizer keyboard, tilted up",
    "marimba": "a small wooden marimba",
    "glock": "a glockenspiel with rainbow coloured bars",
    "sub": "a huge boxy subwoofer speaker cabinet with one giant speaker cone",
    "organ": "a row of tall church organ pipes, tallest in the middle",
    "didge": "a long painted wooden didgeridoo, standing upright",
    "flute": "a silver concert flute, standing upright",
    "laser": "a retro toy ray gun",
    "powerup": "a shiny golden arcade power-up star",
    "buzzer": "a big red arcade game-over buzzer button",
}
PROMPT = """Make one bright, fun picture of the object named below, for a musical toy that kids love to play with. It should feel playful, loud and a little punk, like a member of a very silly band.
The image shows the band members already in this game. Match how they are made, so the new one obviously belongs with them: the same hand-made print, ink line, texture and character, standing on the same kind of two small legs and feet. Do not copy what they are, and do not include them.
Someone must be able to name the object at a glance. No face and no arms.
This is one flat picture. No cast shadow, floor, scene, frame, lettering or duplicates. One object only, whole and centered with generous blank space, on a perfectly plain, very light background.

The object: {subject}"""


def make_sound(source_root: Path, name: str, relative: str, seconds: float) -> None:
    SOUNDS.mkdir(parents=True, exist_ok=True)
    target = SOUNDS / f"{name}.wav"
    # Starts on the attack, ends in a short fade, and every sound peaks at the same level.
    filters = (
        "silenceremove=start_periods=1:start_threshold=-50dB,"
        f"atrim=0:{seconds},afade=t=out:st={max(0, seconds - FADE_S)}:d={FADE_S},"
        f"loudnorm=print_format=none:linear=true:tp={PEAK_DB}:i=-16,"
    ).removesuffix(",")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source_root / relative)]
        + ["-af", filters, "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le"]
        + ["-map_metadata", "-1", str(target)],
        check=True,
    )
    logger.info("%s %.0f KB", target.name, target.stat().st_size / 1024)


async def paint(client: httpx.AsyncClient, key: str, name: str, subject: str) -> None:
    style = base64.b64encode(BAND_STYLE.read_bytes()).decode("ascii")
    response = await client.post(
        "https://api.meta.ai/v1/images/edits",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "muse-image-1.0",
            "prompt": PROMPT.format(subject=subject),
            "images": [{"image_url": f"data:image/png;base64,{style}"}],
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
            "output_format": "png",
            "tool_enablement": {
                "enable_image_search": False,
                "enable_web_search": False,
                "enable_shell": False,
            },
        },
        timeout=180.0,
    )
    response.raise_for_status()
    raw = base64.b64decode(response.json()["data"][0]["b64_json"], validate=True)
    painted = PICTURES / f".{name}-painted.png"
    painted.write_bytes(raw)
    found = paper_background_object(painted)
    if found is None:
        raise ValueError(f"{name}: the background was not plain, so it could not be lifted off")
    cutout = PICTURES / f".{name}-cutout.png"
    mask = PICTURES / f".{name}-mask.png"
    write_cutout(painted, found, cutout, mask)
    with Image.open(cutout) as image:
        small = image.convert("RGBA")
    small.thumbnail((LONGEST_SIDE, LONGEST_SIDE))
    target = PICTURES / f"{name}.png"
    stream = io.BytesIO()
    small.save(stream, format="PNG", optimize=True)
    target.write_bytes(stream.getvalue())
    for leftover in (painted, cutout, mask):
        leftover.unlink(missing_ok=True)
    logger.info("%s %dx%d %.0f KB", target.name, *small.size, target.stat().st_size / 1024)


async def paint_all(key: str, names: list[str]) -> list[str]:
    PICTURES.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(3)
    failed: list[str] = []

    async def one(client: httpx.AsyncClient, name: str) -> None:
        async with limit:
            try:
                await paint(client, key, name, PICTURE_SUBJECTS[name])
            except (httpx.HTTPError, ValueError, KeyError) as error:
                logger.warning("%s failed: %s", name, type(error).__name__)
                logger.warning("%s", str(error)[:160])
                failed.append(name)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(one(client, name) for name in names))
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--repaint", nargs="*", help="Paint these again, or all if none are named")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.source:
        for name, (relative, seconds) in SOUND_FILES.items():
            make_sound(args.source, name, relative, seconds)
    key = os.environ.get("MODEL_API_KEY", "").strip()
    wanted = [
        name
        for name in PICTURE_SUBJECTS
        if not (PICTURES / f"{name}.png").exists()
        or (args.repaint is not None and (not args.repaint or name in args.repaint))
    ]
    if wanted and not key:
        raise SystemExit(f"Set MODEL_API_KEY to paint: {', '.join(wanted)}")
    if wanted:
        failed = asyncio.run(paint_all(key, wanted))
        if failed:
            raise SystemExit(
                f"Could not paint: {', '.join(failed)}. Run again to retry just those."
            )


if __name__ == "__main__":
    main()
