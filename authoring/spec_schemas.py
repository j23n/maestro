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

from pydantic import BaseModel, ConfigDict, Field


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
    # Progressive framings of the same scenario; index = depth - 1.
    depths: list[str] = Field(min_length=1)
    grammar_ids: list[str] = []
    function_ids: list[str] = []
    # Optional authored narrative framing (present for A0 today).
    overview: str | None = None
    scene_setting: str | None = None
    outro: str | None = None
    image: str | None = None


class VocabEntry(BaseModel):
    """One lemma in the leveled vocabulary list.

    Doubles as the constraint list for content: words above the learner's
    level appearing in generated items must be glossed or rejected
    (enforced as build warnings until lemmatization is battle-tested).
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # the lemma itself (lowercase; may contain spaces for phrases)
    cefr_level: CefrLevel
    pos: str  # noun | verb | adj | adv | pron | prep | conj | num | inter | phrase
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
