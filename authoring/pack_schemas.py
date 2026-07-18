"""Pydantic schemas for content-pack sources (``packs/<lang>/``).

Layer 2 of the architecture: concrete learning items, each tagged with
coordinates in the curriculum spec. Item families:

- drills (cloze / multiple choice / transform) — scorable, targeted
- readings & listenings — a parent passage/dialogue plus scorable
  comprehension questions
- vocab cards — SM-2 review material instantiating spec lemmas
- speaking prompts — closed speaking tasks with an authored target,
  scored by the core's transcript-alignment scorer
- writing prompts — open tasks with a deterministic rubric; free-form
  feedback is the (optional, eval-gated) LLM tier's job
- grammar refs — learner-facing reference pages for a grammar point

``build_pack.py`` compiles these into the SQLite bundle whose schema is
documented in ``core/src/pack.rs`` — that file is the contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from authoring.spec_schemas import CefrLevel


class Evidence(BaseModel):
    """One axis of the learner model this item feeds when completed."""

    model_config = ConfigDict(extra="forbid")

    axis: str = Field(pattern=r"^(grammar|function|vocab|cando)$")
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
    # Relative path under images/ once generated; None until then.
    image: str | None = None
    # Inline glosses for above-level words: word -> gloss.
    glossary: dict[str, str] = {}
    questions: list[Question] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    text: str
    # Relative path under audio/ once rendered; None until then. The
    # shell falls back to system TTS for un-rendered turns.
    audio: str | None = None


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


class VocabCardItem(BaseModel):
    """A review card instantiating one lemma from the leveled vocab list.

    Cards are the SM-2 scheduler's unit. Two modes at once: self-graded
    flip (front/back always present) and typed recall when ``answers``
    is authored (the learner produces the Italian side).
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^vocab\.[a-z0-9._]+$")
    item_type: str = Field(default="vocab_card", pattern=r"^vocab_card$")
    cefr_level: CefrLevel
    # The spec vocab id this card instantiates (lemmas may contain spaces).
    lemma: str
    front: str  # Italian side
    back: str  # English side
    example: str | None = None  # Italian example sentence
    example_gloss: str | None = None
    # Relative media paths once rendered/generated; None until then.
    audio: str | None = None
    image: str | None = None
    # Optional typed-recall answers (Italian productions of `back`).
    answers: list[Answer] = []
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def check_shape(self) -> VocabCardItem:
        if self.answers and not any(a.canonical for a in self.answers):
            raise ValueError(f"{self.id}: typed-recall answers need a canonical one")
        if not any(e.axis == "vocab" for e in self.evidence):
            raise ValueError(f"{self.id}: vocab card needs vocab-axis evidence")
        return self


class SpeakingPromptItem(BaseModel):
    """A closed speaking task: prompt + authored target utterance.

    Scored offline by the core's transcript-alignment scorer against
    ``target_text`` (variants are alternate acceptable targets).
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^speaking\.[a-z0-9._]+$")
    item_type: str = Field(default="speaking_prompt", pattern=r"^speaking_prompt$")
    cefr_level: CefrLevel
    # Learner-facing instruction ("Ordina un caffè e chiedi il conto.").
    prompt: str
    target_text: str
    variants: list[str] = []
    # Model pronunciation of target_text once rendered; None until then.
    audio: str | None = None
    explanation: str | None = None
    evidence: list[Evidence] = Field(min_length=1)


class WritingPromptItem(BaseModel):
    """An open writing task with a deterministic rubric.

    The rubric is checkable offline (length, structures attempted, vocab
    used); rubric-grade free-form feedback is the LLM tier's job and
    arrives via the pending-feedback queue.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^writing\.[a-z0-9._]+$")
    item_type: str = Field(default="writing_prompt", pattern=r"^writing_prompt$")
    cefr_level: CefrLevel
    prompt: str
    min_words: int = Field(default=20, ge=1)
    # Grammar-point ids the submission should attempt.
    required_grammar: list[str] = []
    # Spec vocab ids the submission should use.
    required_vocab: list[str] = []
    model_answer: str | None = None
    evidence: list[Evidence] = Field(min_length=1)


class GrammarRefItem(BaseModel):
    """A learner-facing reference page for one grammar point.

    Curated pack content (markdown body), distinct from the spec's own
    terse explanation: refs are written for the learner, versioned with
    the pack, and can exist in several UI languages later.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="reviewed", pattern=r"^(draft|reviewed|flagged)$")
    review_note: str | None = None

    id: str = Field(pattern=r"^grammar_ref\.[a-z0-9._]+$")
    item_type: str = Field(default="grammar_ref", pattern=r"^grammar_ref$")
    cefr_level: CefrLevel
    grammar_id: str
    title: str
    body_md: str
    examples: list[str] = []
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def check_shape(self) -> GrammarRefItem:
        if not any(
            e.axis == "grammar" and e.id == self.grammar_id for e in self.evidence
        ):
            raise ValueError(
                f"{self.id}: evidence must include grammar {self.grammar_id}"
            )
        return self


class Tombstone(BaseModel):
    """A record of an item removed from the pack.

    Kept forever (``packs/<lang>/tombstones.yaml``) so learner history
    referencing the removed id stays interpretable across pack updates.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: str
    removed_in: str  # pack_version that first shipped without the item
    reason: str | None = None


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    pack_version: str = Field(pattern=r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")
    # "1": media + tombstones + spec_vocab tables, new item families.
    schema_version: str = "1"
