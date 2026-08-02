"""Pydantic schemas for the curriculum spec (``spec/<lang>/``).

The spec is Layer 1 of the greenfield architecture
(docs/plans/02-greenfield-architecture.md): the CEFR coordinate system that
content packs and learner evidence reference by stable ID. These models are
the single source of truth for its shape; ``validate_spec.py`` enforces the
cross-file invariants (referential integrity, prerequisite DAG acyclicity).

IDs are forever: renaming an ``id`` here is a breaking change for every pack
item and every learner event that references it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CefrLevel(StrEnum):
    A0 = "A0"  # pre-A1, true beginner
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class Source(BaseModel):
    """Provenance of a spec entry (Profilo descriptor, grammar-book chunk)."""

    model_config = ConfigDict(extra="forbid")

    descriptor_code: str | None = None  # was unistr_code; groups related points
    descriptor_label: str | None = None  # was unistr_label
    chunk_ref: str | None = None  # grammar-book excerpt reference
    source_url: str | None = None


class Explanation(BaseModel):
    """A pre-authored learner-facing explanation in one UI language."""

    model_config = ConfigDict(extra="forbid")

    language: str
    title: str = ""
    explanation: str = ""
    tip: str = ""
    why_this_matters: str = ""


class GrammarPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    cefr_level: CefrLevel
    category: str
    subcategory: str | None = None
    label: str
    description: str | None = None
    examples: list[str] = []
    prerequisites: list[str] = []  # grammar point ids
    explanations: dict[str, Explanation] = {}  # keyed by UI language
    source: Source = Source()


class CommunicativeFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    cefr_level: CefrLevel
    category: str
    label: str
    description: str | None = None
    patterns: list[str] = []
    examples: list[str] = []


# How much a lesson (or an item) asks of the learner — the rung of the
# spiral (docs/plans/07 §2). Maps 1:1 onto the core's `EvidenceClass`.
#
#   meet    -> receptive  recognise it: a passage, a comprehension question
#   use     -> targeted   produce it with scaffolding: cloze, guided speaking
#   perform -> productive produce it without: open task, role-play, free writing
Demand = Literal["meet", "use", "perform"]

DEMAND_TO_EVIDENCE_CLASS: dict[str, str] = {
    "meet": "receptive",
    "use": "targeted",
    "perform": "productive",
}

# Ordering, for "a revisit may not go down a rung".
DEMAND_RANK: dict[str, int] = {"meet": 0, "use": 1, "perform": 2}


class Revisit(BaseModel):
    """One thing a lesson comes back to, and the rung it takes it to."""

    model_config = ConfigDict(extra="forbid")

    id: str
    demand: Demand


class Introduces(BaseModel):
    """What a lesson teaches for the first time — its exclusive homes.

    Everything listed here is introduced by this lesson and no other, so
    the lesson owes it a reference page and a first bank of items.
    """

    model_config = ConfigDict(extra="forbid")

    grammar: list[str] = []
    functions: list[str] = []
    vocab: list[str] = []


class Revisits(BaseModel):
    """What a lesson comes back to, one rung up. The spiral, declared."""

    model_config = ConfigDict(extra="forbid")

    grammar: list[Revisit] = []
    functions: list[Revisit] = []
    vocab: list[Revisit] = []


class Capstone(BaseModel):
    """A can-do proved at one rung — the lesson's closing performance.

    A can-do is capstoned in three lessons at rising demand; only the
    ``perform`` pass moves it to *achieved*.
    """

    model_config = ConfigDict(extra="forbid")

    cando: str
    demand: Literal["use", "perform"]


class Lesson(BaseModel):
    """One scenario at one depth — the unit the learner actually plays.

    A lesson is authored, named, and declares both what it introduces and
    what it comes back to. It ships with a required set of items or the
    composer never offers it (docs/plans/07 §2).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+\.d[0-9]+$")
    # Depth carries its own level: a scenario's band rises by at most one
    # across its depths, which is where A2 lives (docs/plans/07 §4a).
    # None inherits the scenario's.
    cefr_level: CefrLevel | None = None
    label: str = ""
    # What the learner will be able to do by the end — the capstone in
    # plain words, and what the splash screen leads with.
    goal: str | None = None
    # The one-line framing this depth had before lessons were objects.
    summary: str = ""
    introduces: Introduces = Introduces()
    revisits: Revisits = Revisits()
    capstones: list[Capstone] = []
    # Per-depth narrative; falls back to the scenario's.
    scene_setting: str | None = None
    outro: str | None = None
    # Authored override for the lesson illustration's generation prompt
    # (`generate-images`). Authoring-only: the art itself ships by its
    # conventional path, this field never does.
    image_prompt: str | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    cefr_level: CefrLevel
    # Unlock grouping (A1+): phase N opens after enough phase N-1 scenarios.
    phase: int = Field(default=1, ge=1)
    # Fixed linear position within the level, for the A0 crash course.
    sequence: int | None = None
    label: str
    description: str
    # The scenario's lessons, in order; index = depth - 1.
    depths: list[Lesson] = Field(min_length=1)
    # Derived unions of the depths' introduces+revisits, kept because packs
    # and can-dos reference them; `validate_spec` asserts they agree.
    grammar_ids: list[str] = []
    function_ids: list[str] = []
    # Optional authored narrative framing (present for A0 today).
    overview: str | None = None
    scene_setting: str | None = None
    outro: str | None = None
    image: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _lift_legacy_depths(cls, data):
        """Accept the pre-lesson `depths: [str]` form.

        Depths were one-line framings before they were objects. Lifting
        them here rather than rewriting the spec in the same change keeps
        this migration reviewable: every scenario still loads, and the
        spec fill (docs/plans/07 step 4) is what populates the rest.
        """
        if not isinstance(data, dict):
            return data
        depths = data.get("depths")
        if not isinstance(depths, list):
            return data
        data = dict(data)
        data["depths"] = [
            {"id": f"{data.get('id', 'unknown')}.d{n}", "summary": d}
            if isinstance(d, str)
            else d
            for n, d in enumerate(depths, 1)
        ]
        return data

    def lesson(self, depth: int) -> Lesson:
        """The lesson at ``depth`` (1-based), as the composer counts them."""
        return self.depths[depth - 1]

    def level_at(self, depth: int) -> CefrLevel:
        return self.depths[depth - 1].cefr_level or self.cefr_level


class VocabEntry(BaseModel):
    """One lemma in the leveled vocabulary list.

    Doubles as the constraint list for content: words above the learner's
    level appearing in generated items must be glossed or rejected
    (enforced as build warnings until lemmatization is battle-tested).
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # the lemma itself (lowercase; may contain spaces for phrases)
    cefr_level: CefrLevel
    # Cardable: noun | verb | adj | adv | num | inter | phrase — SRS material,
    # owed a vocab card by its home lesson. Grammatical: art | prep | pron |
    # conj — a dictionary gloss and nothing more (docs/plans/08 §2).
    pos: str
    gloss: str  # English gloss


class Skill(StrEnum):
    """The CEFR's five modes of communication."""

    LISTENING = "listening"
    READING = "reading"
    SPOKEN_INTERACTION = "spoken_interaction"
    SPOKEN_PRODUCTION = "spoken_production"
    WRITING = "writing"


class CanDo(BaseModel):
    """A CEFR can-do statement — the learner-facing unit of progress.

    Each descriptor decomposes into the grammar, functions, and vocabulary
    it requires and maps to the scenarios where it is practiced. A can-do
    is *achieved* when its grammar is mastered, its functions demonstrated,
    and at least one application-grade task for it completed
    (docs/plans/02-greenfield-architecture.md §4).

    Descriptor text is original, informed by the CEFR Companion Volume and
    the Profilo della lingua italiana as completeness checklists.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9._]+$")
    cefr_level: CefrLevel
    skill: Skill
    label: str  # the descriptor text, always starting "Can ..."
    theme: str  # coarse grouping for display (social, services, travel, ...)
    function_ids: list[str] = []
    grammar_ids: list[str] = []
    scenario_ids: list[str] = []
    # Free-form for now; becomes IDs into the leveled vocab list when that
    # lands (Phase 1 vocab consolidation).
    vocab_domains: list[str] = []
    notes: str | None = None


class Spec(BaseModel):
    """A whole language's curriculum spec, loaded for cross-validation."""

    model_config = ConfigDict(extra="forbid")

    language: str
    grammar_points: list[GrammarPoint]
    communicative_functions: list[CommunicativeFunction]
    scenarios: list[Scenario]
    can_dos: list[CanDo] = []
    vocab: list[VocabEntry] = []
