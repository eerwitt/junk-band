from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The longest source clip. Containers often report a hair over a round length.
MAX_SOURCE_S = 60.0
DURATION_SLACK_S = 0.05


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Media(StrictModel):
    id: str
    duration_s: float
    width: int
    height: int
    audio_present: bool
    filename: str


class SegmentRequest(StrictModel):
    media_id: str
    frame_s: float = Field(ge=0, le=MAX_SOURCE_S)
    concept: str | None = Field(default=None, min_length=1, max_length=100)
    box: list[float] | None = None

    @model_validator(mode="after")
    def validate_prompt(self) -> "SegmentRequest":
        if (self.concept is None) == (self.box is None):
            raise ValueError("Use one concept OR one box")
        if self.box is not None:
            if len(self.box) != 4 or not all(0 <= x <= 1 for x in self.box):
                raise ValueError("Box must have four normalized coordinates")
            if self.box[0] >= self.box[2] or self.box[1] >= self.box[3]:
                raise ValueError("Box must have positive area")
        return self


class SelectionRequest(StrictModel):
    media_id: str
    frame_s: float = Field(ge=0, le=MAX_SOURCE_S)
    # A rough box to describe and refine, words to search for, or both.
    box: list[float] | None = None
    concept: str | None = Field(default=None, min_length=1, max_length=100)
    # The stretch kept in the first phase, which holds the sound window.
    start_s: float = Field(ge=0, le=MAX_SOURCE_S + DURATION_SLACK_S)
    end_s: float = Field(ge=0, le=MAX_SOURCE_S + DURATION_SLACK_S)

    @model_validator(mode="after")
    def validate_selection(self) -> "SelectionRequest":
        if self.box is None and self.concept is None:
            raise ValueError("Select a box or say what to find")
        if self.box is not None:
            if len(self.box) != 4 or not all(0 <= x <= 1 for x in self.box):
                raise ValueError("Box must have four normalized coordinates")
            if self.box[0] >= self.box[2] or self.box[1] >= self.box[3]:
                raise ValueError("Box must have positive area")
        if self.end_s < self.start_s:
            raise ValueError("The end of the stretch must follow its start")
        return self


class Selection(StrictModel):
    cutout_id: str
    cutout_url: str
    mask_url: str
    card_url: str
    frame_s: float
    name: str
    sound: str
    sound_start_s: float
    sound_end_s: float
    provenance: str


class SeparateRequest(StrictModel):
    media_id: str
    start_s: float = Field(ge=0, le=MAX_SOURCE_S - 2)
    end_s: float = Field(ge=2, le=MAX_SOURCE_S)
    description: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_window(self) -> "SeparateRequest":
        # Decimal trim inputs such as 2.3 - 0.3 have binary float roundoff.
        if not 2 - 1e-7 <= self.end_s - self.start_s <= 8 + 1e-7:
            raise ValueError("Extraction must be between 2 and 8 seconds")
        return self


SoundStage = Literal["sending", "separating", "collecting"]


class Job(StrictModel):
    id: str
    status: Literal["queued", "processing", "ready", "failed"]
    stage: SoundStage | None = None
    error: str | None = None
    target_url: str | None = None
    residual_url: str | None = None
    provenance: str
    metrics: dict[str, float | str] = Field(default_factory=dict)
    call_id: str | None = None
    queue_position: int = 0


class CharacterRequest(StrictModel):
    cutout_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    description: str = Field(min_length=1, max_length=160)
    details: str = Field(default="", max_length=300)


class RigLayer(StrictModel):
    name: Literal["left_arm", "right_arm", "left_leg", "right_leg"]
    url: str
    pivot: tuple[Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)]]
    max_angle: float = Field(gt=0, le=0.5)


class CharacterRigAsset(StrictModel):
    width: int = Field(gt=0, le=2048)
    height: int = Field(gt=0, le=2048)
    body_url: str
    parts: list[RigLayer] = Field(min_length=4, max_length=4)


class CharacterJob(StrictModel):
    id: str
    status: Literal["queued", "processing", "ready", "failed"]
    stage: Literal["painting", "cutting", "rigging", "ready"] = "painting"
    source_cutout_url: str
    character_url: str | None = None
    error: str | None = None
    provenance: str = "Meta Muse Image + SAM 3.1"
    rig: CharacterRigAsset | None = None
    queue_position: int = 0


class PerformerSummary(StrictModel):
    id: str = Field(max_length=100)
    name: str = Field(max_length=80)
    steps: list[Annotated[int, Field(ge=0, le=255)]] = Field(max_length=256)
    motion: Literal["still", "hop", "dance", "roll", "glide"]
    gainDb: float = Field(ge=-36, le=0)


class WonderRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=500)
    performers: list[PerformerSummary] = Field(min_length=1, max_length=24)


class Action(StrictModel):
    performerId: str
    kind: Literal["set_motion", "set_pattern_transform", "set_gain_db"]
    value: str | float


class Proposal(StrictModel):
    explanation: str
    actions: list[Action] = Field(min_length=1, max_length=5)
    provenance: Literal["mock rule", "Muse Wonder"]
    trace: list[str]
