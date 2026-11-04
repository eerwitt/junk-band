import base64
import json
import logging
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from PIL import Image, ImageChops

from services.gateway.meta_costs import SAM_IMAGE, WONDER, note_chat_cost, note_meta_cost
from services.gateway.models import Action, Proposal, SegmentRequest, WonderRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FoundObject:
    """A mask positioned on its source frame, in source pixels."""

    left: int
    top: int
    alpha: Image.Image
    confidence: float | None


class ModelDependencyError(RuntimeError):
    pass


class ModelResultError(RuntimeError):
    """Unusable provider output; never substitute a demo artifact."""


class NoObjectMatched(ValueError):
    """SAM understood the request and found nothing, so another wording may still succeed."""


class MetaAdapter:
    @staticmethod
    def segmentation_available() -> bool:
        return find_spec("meta_sam_parser") is not None

    def __init__(self, key: str) -> None:
        self.client = AsyncOpenAI(
            api_key=key, base_url="https://api.meta.ai/v1", timeout=90, max_retries=1
        )

    async def models(self) -> list[str]:
        return [model.id for model in (await self.client.models.list()).data]

    async def segment(
        self, frame: Path, target: Path, request: SegmentRequest, mask_target: Path | None = None
    ) -> None:
        await self._segment(frame, target, request, preserve_canvas=False, mask_target=mask_target)

    async def find_objects(self, frame: Path, concept: str) -> list[FoundObject]:
        """Every object matching a concept, with confidence, instead of insisting on just one."""
        sam = self._parser()
        records = await self._latest_records(sam, frame, concept)
        with Image.open(frame) as image:
            size = image.size
        return [self._positioned(sam, record, size) for record in records]

    async def segment_layer(self, frame: Path, target: Path, concept: str) -> None:
        """Keep source coordinates for a rigid limb layer instead of cropping it."""
        await self._segment(
            frame,
            target,
            SegmentRequest(media_id="character-layer", frame_s=0, concept=concept),
            preserve_canvas=True,
        )

    async def find_box(self, frame: Path, box: tuple[int, int, int, int]) -> FoundObject:
        """What SAM makes of a box alone: reliable on a tight box, not on a loose one."""
        sam = self._parser()
        with Image.open(frame) as image:
            size = image.size
        prompt = sam.build_object_prompt(
            size=size,
            objects=[
                sam.PromptObject(id=1, prompts=[sam.FramePrompt(frame=0, box=sam.PromptBox(*box))])
            ],
        )
        records = [
            record
            for record in await self._latest_records(sam, frame, prompt)
            if record.object_id == "1"
        ]
        if not records:
            raise NoObjectMatched("No object matched this box.")
        return self._positioned(sam, records[0], size)

    async def _segment(
        self,
        frame: Path,
        target: Path,
        request: SegmentRequest,
        *,
        preserve_canvas: bool,
        mask_target: Path | None = None,
    ) -> None:
        sam = self._parser()
        with Image.open(frame) as image:
            size = image.size
        prompt = request.concept or ""
        if request.box:
            x1, y1, x2, y2 = request.box
            prompt = sam.build_object_prompt(
                size=size,
                objects=[
                    sam.PromptObject(
                        id=1,
                        prompts=[
                            sam.FramePrompt(
                                frame=0,
                                box=sam.PromptBox(
                                    int(x1 * size[0]),
                                    int(y1 * size[1]),
                                    min(size[0], max(int(x1 * size[0]) + 1, int(x2 * size[0]))),
                                    min(size[1], max(int(y1 * size[1]) + 1, int(y2 * size[1]))),
                                ),
                            )
                        ],
                    )
                ],
            )
        records = await self._latest_records(sam, frame, prompt)
        if request.box:
            records = [record for record in records if record.object_id == "1"]
        if not records:
            raise NoObjectMatched("No object matched. Select a tighter box or another frame.")
        if len(records) != 1:
            raise ValueError(
                "More than one object matched. Draw a tighter box around the object you want."
            )
        found = self._positioned(sam, records[0], size)
        left, top, alpha = found.left, found.top, found.alpha
        with Image.open(frame) as original:
            rgba = original.convert("RGBA")
            cropped = rgba.crop((left, top, left + alpha.width, top + alpha.height))
            if preserve_canvas:
                canvas_alpha = Image.new("L", size, 0)
                canvas_alpha.paste(alpha, (left, top))
                # The input may already be a cutout; SAM cannot restore its background.
                rgba.putalpha(ImageChops.darker(rgba.getchannel("A"), canvas_alpha))
                rgba.save(target, format="PNG")
            else:
                cropped.putalpha(ImageChops.darker(cropped.getchannel("A"), alpha))
                cropped.save(target, format="PNG")
            if mask_target is not None:
                canvas = Image.new("L", size, 0)
                canvas.paste(alpha, (left, top))
                canvas.save(mask_target, format="PNG")
        logger.info("SAM cutout completed size=%s", alpha.size)

    @staticmethod
    def _parser() -> Any:  # noqa: ANN401
        try:
            return import_module("meta_sam_parser")
        except ImportError as error:
            raise ModelDependencyError(
                "Meta SAM support is not installed on this gateway. Run uv sync --extra dev in the server environment before testing live cutouts."
            ) from error

    @staticmethod
    def _positioned(sam: Any, record: Any, size: tuple[int, int]) -> FoundObject:  # noqa: ANN401
        mask = record.mask
        raster = sam.decode_mask_to_raster(mask)
        alpha = Image.frombytes(
            "L", (mask.width, mask.height), bytes(value * 255 for value in raster)
        )
        bounds = record.bounds
        coordinates = (bounds.left, bounds.top, bounds.right, bounds.bottom)
        if not all(float(value).is_integer() for value in coordinates):
            raise ModelResultError(
                "SAM returned a mask outside the source pixel grid. Retry the cutout."
            )
        left, top, right, bottom = (int(value) for value in coordinates)
        if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
            raise ModelResultError("SAM mask bounds fall outside the source canvas")
        box = (right - left, bottom - top)
        if box != alpha.size:
            # SAM caps a mask's long side at 1024 pixels, so large images return a smaller raster
            # of the same shape. Any other difference means the mask does not fit its box.
            if abs(box[0] / box[1] - alpha.width / alpha.height) > 0.02 * box[0] / box[1]:
                raise ValueError(
                    "Mask geometry differs from the source crop; refusing a misaligned cutout"
                )
            alpha = alpha.resize(box, Image.Resampling.BILINEAR)
        return FoundObject(
            left=left, top=top, alpha=alpha, confidence=getattr(record, "confidence", None)
        )

    async def _latest_records(self, sam: Any, frame: Path, prompt: str) -> list[Any]:  # noqa: ANN401
        encoded = base64.b64encode(frame.read_bytes()).decode()
        note_meta_cost(SAM_IMAGE)
        stream = await self.client.responses.create(
            model="sam-3.1",
            stream=True,
            metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{encoded}",
                            "detail": "auto",
                        },
                    ],
                }
            ],
        )
        parsed = sam.parse_responses_stream(stream, sam.image_segmentation_format())
        try:
            try:
                result = await parsed.final_result()
            finally:
                await parsed.aclose()
        except sam.ResponsesStreamError as error:
            logger.warning("SAM stream failed error_type=%s", type(error).__name__)
            raise ModelResultError(
                "SAM could not complete its segmentation stream. Retry; no mock crop was substituted."
            ) from error
        if result.outcome.status != "completed":
            raise ModelResultError(
                "SAM segmentation ended before completion. Retry; no mock crop was substituted."
            )
        if any(diagnostic.severity == "error" for diagnostic in result.diagnostics):
            raise ModelResultError(
                "SAM returned malformed segmentation data. Retry with another frame or a tighter selection."
            )
        # Cumulative records retain draft masks. Resolve revisions before choosing
        # the prompted object; a concept matching several objects needs selection.
        latest: dict[Any, Any] = {}
        for record in result.records:
            if isinstance(record, sam.SegmentationMaskRecord):
                previous = latest.get(record.object_id)
                if previous is None or record.revision > previous.revision:
                    latest[record.object_id] = record
        return list(latest.values())

    async def wonder(self, request: WonderRequest) -> Proposal:
        snapshot = json.dumps([p.model_dump() for p in request.performers])
        tools: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": "list_performers",
                    "description": "Inspect the current performers before proposing a change.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "preview_changes",
                    "description": "Dry-run up to five bounded musical or motion actions.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "actions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "performerId": {"type": "string"},
                                        "kind": {
                                            "type": "string",
                                            "enum": [
                                                "set_motion",
                                                "set_pattern_transform",
                                                "set_gain_db",
                                            ],
                                        },
                                        "value": {
                                            "anyOf": [{"type": "string"}, {"type": "number"}]
                                        },
                                    },
                                    "required": ["performerId", "kind", "value"],
                                    "additionalProperties": False,
                                },
                            },
                            "explanation": {"type": "string"},
                        },
                        "required": ["actions", "explanation"],
                        "additionalProperties": False,
                    },
                },
            },
        ]
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": "You are a musical paper-puppet director. First inspect performers, then propose preview_changes. Never execute code. Motion: still/hop/dance/roll/glide. Rhythm operators: offbeat_echo/mirror/halve/fill. Gain: -30 to -3 dB. Only edit IDs returned by list_performers. Explain concisely. Do not claim to hear the result.",
            },
            {"role": "user", "content": request.instruction},
        ]
        trace: list[str] = []
        for _ in range(4):
            response = await self.client.chat.completions.create(
                model="muse-wonder-1.0", messages=messages, tools=tools, tool_choice="required"
            )
            note_chat_cost(response, WONDER)
            message = response.choices[0].message
            if not message.tool_calls:
                raise ValueError("Wonder did not return a tool call")
            assistant: ChatCompletionAssistantMessageParam = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                    if call.type == "function"
                ],
            }
            if message.content:
                assistant["content"] = message.content
            messages.append(assistant)
            for call in message.tool_calls:
                if call.type != "function":
                    raise ValueError("Unsupported tool call type")
                arguments = json.loads(call.function.arguments)
                if call.function.name == "list_performers":
                    trace.append("list_performers → inspected the scene")
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": snapshot})
                elif call.function.name == "preview_changes" and trace:
                    actions = [Action.model_validate(action) for action in arguments["actions"]]
                    validate_actions(actions, request)
                    trace.append("preview_changes → validated IDs, operations and gain limits")
                    return Proposal(
                        explanation=arguments["explanation"],
                        actions=actions,
                        provenance="Muse Wonder",
                        trace=trace,
                    )
                else:
                    raise ValueError(
                        "Wonder must inspect before previewing; unknown tools are rejected"
                    )
        raise ValueError("Wonder exceeded the bounded tool loop")


def validate_actions(actions: list[Action], request: WonderRequest) -> None:
    ids = {p.id for p in request.performers}
    if not 1 <= len(actions) <= 5:
        raise ValueError("Expected 1–5 actions")
    for action in actions:
        if action.performerId not in ids:
            raise ValueError("Suggestion references an unknown performer")
        if action.kind == "set_gain_db":
            if not isinstance(action.value, (int, float)) or not -30 <= action.value <= -3:
                raise ValueError("Gain outside safe limits")
        elif action.kind == "set_motion":
            if action.value not in {"still", "hop", "dance", "roll", "glide"}:
                raise ValueError("Unknown motion")
        elif action.value not in {"offbeat_echo", "mirror", "halve", "fill"}:
            raise ValueError("Unknown rhythm operator")
