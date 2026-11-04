"""Reference-guided Muse Image edits; the source cutout and source audio stay intact."""

import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from services.gateway.meta_costs import MUSE_IMAGE, note_meta_cost

logger = logging.getLogger(__name__)
STYLE_VERSION = "band-member-v4"
BAND_STYLE = Path(__file__).with_name("assets") / "band-style.png"
STYLE_PROMPT = """Make one bright, fun picture of the object named below, for a musical toy that kids love to play with. It should feel playful, loud and a little punk, full of rhythm and energy, like a member of a very silly band.
The first image is a rough cutout from real footage, often showing only part of the object. Use it for the object's colors, materials and patterns, pushed brighter and bolder, but paint the complete object in its most recognizable view, not the shape of the cutout's torn or cropped edges. Someone who has never seen the footage must be able to name it at a glance.
The second image shows the band members already in this game. Match how they are made, so the new one obviously belongs with them: the same hand-made print, ink line, texture and character. Do not copy what they are, and do not include them.
Keep it what it is, and never turn it into something else. A person or animal stays that person or animal, whole, with their own face, body and pose, as a paper version of them. It stays an object if it is an object, with no face, arms, legs, feet, hands or clothing added unless the direction below asks for them, and without anyone holding or wearing it.
This is one flat picture. No cast shadow, floor, scene, frame, lettering or duplicates. One object only, whole and centered with generous blank space, on a perfectly plain, very light background.
"""


def character_prompt(description: str, details: str) -> str:
    direction = f"\nAdditional direction: {details}" if details.strip() else ""
    return f"{STYLE_PROMPT}\nThe object: {description}{direction}"


def _data_url(path: Path) -> str:
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


async def paint_character(
    key: str, model: str, source: Path, target: Path, description: str, details: str
) -> None:
    # Meta documents the JSON images[] form; no model-generated alpha is assumed.
    images = [_data_url(source)]
    if BAND_STYLE.exists():
        images.append(_data_url(BAND_STYLE))
    else:
        logger.warning("Band style reference is missing: %s", BAND_STYLE)
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            "https://api.meta.ai/v1/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "prompt": character_prompt(description, details),
                "images": [{"image_url": image} for image in images],
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
        )
        response.raise_for_status()
        note_meta_cost(MUSE_IMAGE)
        payload = response.json()
    entries = payload.get("data")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("Muse Image returned no single character candidate")
    encoded = entries[0].get("b64_json")
    if not isinstance(encoded, str) or len(encoded) > 32 * 1024 * 1024:
        raise ValueError("Muse Image returned an unsupported image payload")
    raw = base64.b64decode(encoded, validate=True)
    temporary = target.with_suffix(".tmp")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("Muse Image candidate is too large")
            image.convert("RGBA").save(temporary, format="PNG")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
