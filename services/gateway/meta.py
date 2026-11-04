import base64
import logging
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from PIL import Image, ImageChops

from services.gateway.meta_costs import SAM_IMAGE, note_meta_cost
from services.gateway.models import SegmentRequest

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
