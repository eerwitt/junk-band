import base64
import io
from pathlib import Path

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
)
from PIL import Image
from pydantic import Field

from services.gateway.meta_costs import (
    SPARK,
    note_chat_cost,
)
from services.gateway.models import StrictModel


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
