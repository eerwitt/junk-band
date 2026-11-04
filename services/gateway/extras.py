import base64
import io
import json
import uuid
from pathlib import Path
from typing import Literal

import httpx
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
)
from PIL import Image
from pydantic import Field

from services.gateway.media import execute
from services.gateway.meta_costs import (
    SPARK,
    TRANSCRIBE_PER_SECOND,
    note_chat_cost,
    note_meta_cost,
)
from services.gateway.models import StrictModel


class InterpretationRequest(StrictModel):
    description: str = Field(min_length=1, max_length=300)


class Interpretation(StrictModel):
    concept: str = Field(min_length=1, max_length=80)
    sound_description: str = Field(min_length=1, max_length=100)
    role: Literal["low", "backbeat", "melodic", "texture"]
    motion: Literal["still", "hop", "dance", "roll", "glide"]


async def interpret(key: str, request: InterpretationRequest) -> Interpretation:
    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1", timeout=60)
    response = await client.beta.chat.completions.parse(
        model="muse-spark-1.3",
        messages=[
            {
                "role": "system",
                "content": "Suggest a short object concept and lowercase sound description, musical role and simple rigid-puppet motion. You have no audio evidence; do not claim to hear anything.",
            },
            {"role": "user", "content": request.description},
        ],
        response_format=Interpretation,
    )
    note_chat_cost(response, SPARK)
    result = response.choices[0].message.parsed
    if result is None:
        raise ValueError("Spark did not return a valid interpretation")
    return result


class SceneObject(StrictModel):
    name: str = Field(min_length=1, max_length=40)
    sound: str = Field(min_length=1, max_length=100)


SELECTION_PROMPT = """The first image is a frame from a video. The second image is the area of it someone roughly selected, which may be untidy.
Name the main thing they selected, not the background.
name: one or two common lowercase words, such as drum, girl or beaded necklace, with no actions.
sound: a short lowercase phrase for the sound it most plausibly makes in this scene, such as drum hits or child laughing.
You have no audio, so do not claim to hear anything."""


def _image_url(image: Image.Image, longest: int) -> str:
    small = image.convert("RGB")
    small.thumbnail((longest, longest))
    stream = io.BytesIO()
    small.save(stream, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


async def describe_selection(key: str, frame: Path, box: tuple[int, int, int, int]) -> SceneObject:
    """Ask Muse Spark what a rough selection is, so SAM can then look for exactly that."""
    with Image.open(frame) as image:
        whole = image.convert("RGB")
    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1", timeout=75, max_retries=1)
    content: list[ChatCompletionContentPartParam] = [
        ChatCompletionContentPartImageParam(
            type="image_url", image_url={"url": _image_url(whole, 512)}
        ),
        ChatCompletionContentPartImageParam(
            type="image_url", image_url={"url": _image_url(whole.crop(box), 512)}
        ),
    ]
    response = await client.beta.chat.completions.parse(
        model="muse-spark-1.3",
        messages=[
            {"role": "system", "content": SELECTION_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format=SceneObject,
    )
    note_chat_cost(response, SPARK)
    result = response.choices[0].message.parsed
    if result is None:
        raise ValueError("Spark did not describe the selection")
    return result.model_copy(update={"name": result.name.strip().lower()})


async def transcribe(key: str, source: Path, output: Path) -> str:
    execute(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            "20",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(output),
        ]
    )
    settings = {
        "mode": "PUSH_TO_TALK",
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.meta.ai/v1/asr/transcribe",
            params={"sessionId": uuid.uuid4().hex},
            headers={"Authorization": f"Bearer {key}"},
            files={
                "request": (None, json.dumps(settings), "application/json"),
                "audio": ("command.wav", output.read_bytes(), "audio/wav"),
            },
        )
        response.raise_for_status()
        # 16-bit mono at 24 kHz, as converted above.
        note_meta_cost(output.stat().st_size / 48000 * TRANSCRIBE_PER_SECOND)
        text = response.json()["transcript"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No speech was recognized")
    return text[:500]
