"""Pydantic schemas for content-pack sources (``packs/<lang>/``).

Layer 2 of the architecture: concrete learning items, each tagged with
coordinates in the curriculum spec. Phase 0/2 slice: drills only; the
other item types (readings, listenings, dialogues, prompts) follow the
same pattern in Phase 2 proper.

``build_pack.py`` compiles these into the SQLite bundle whose schema is
documented in ``core/src/pack.rs`` — that file is the contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from authoring.spec_schemas import CefrLevel


class Evidence(BaseModel):
    """One axis of the learner model this item feeds when completed."""

    model_config = ConfigDict(extra="forbid")

    axis: str = Field(pattern=r"^(grammar|function|vocab)$")
    id: str
    weight: float = Field(default=1.0, gt=0, le=2.0)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    canonical: bool = False


class DrillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Review lifecycle (plan §10): draft -> reviewed | flagged. Only
    # `reviewed` items are built into the bundle. Hand-authored items
    # default to reviewed.
    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^drill\.[a-z0-9._]+$")
    item_type: str = Field(pattern=r"^drill_(cloze|multiple_choice|transform)$")
    cefr_level: CefrLevel
    modality: str = "writing"
    prompt: str
    answers: list[Answer] = Field(min_length=1)
    # Anticipated wrong answer -> curated feedback for it.
    distractor_feedback: dict[str, str] = {}
    # General mistake explanation, shown when no distractor matches.
    explanation: str | None = None
    evidence: list[Evidence] = Field(min_length=1)
    # Choices for multiple_choice; must include one canonical answer text.
    choices: list[str] = []

    @model_validator(mode="after")
    def check_shape(self) -> DrillItem:
        canonical = [a for a in self.answers if a.canonical]
        if not canonical:
            raise ValueError(f"{self.id}: no canonical answer")
        if self.item_type == "drill_multiple_choice":
            if not self.choices:
                raise ValueError(f"{self.id}: multiple_choice needs choices")
            if not any(a.text in self.choices for a in canonical):
                raise ValueError(f"{self.id}: no canonical answer among choices")
        return self


class Question(BaseModel):
    """A comprehension question attached to a passage or dialogue.

    At build time each question becomes its own scorable item
    (`<parent>.q<n>`, item_type `<parent_type>_question`) so the core's
    one-item-one-answer scoring model holds; the parent item carries the
    passage and the ordered question ids in its payload.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str
    answers: list[Answer] = Field(min_length=1)
    explanation: str | None = None


class ReadingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^reading\.[a-z0-9._]+$")
    cefr_level: CefrLevel
    title: str
    text: str
    # Inline glosses for above-level words: word -> gloss.
    glossary: dict[str, str] = {}
    questions: list[Question] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    text: str


class ListeningItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^listening\.[a-z0-9._]+$")
    cefr_level: CefrLevel
    title: str
    turns: list[DialogueTurn] = Field(min_length=1)
    # Relative path under audio/<lang>/ once rendered; None until then.
    audio: str | None = None
    questions: list[Question] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    pack_version: str = Field(pattern=r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")
    schema_version: str = "0"
