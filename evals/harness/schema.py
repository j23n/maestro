"""Case and result shapes for the LLM eval loop (plan §11)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="allow")  # task-specific template vars

    level: str
    submission: str | None = None
    prompt: str | None = None
    weakness_tags: list[str] = []


class Expectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Grammar tags the output MUST identify as errors (seeded by
    # construction, so these are ground truth).
    must_identify: list[str] = []
    # Tags that MUST NOT be claimed as errors (hallucination check —
    # the cardinal sin for a small model).
    must_not_claim: list[str] = []
    # Substrings that must appear somewhere in the output (e.g. the
    # corrected form).
    must_contain: list[str] = []
    # Hard length cap on any single prose field, in words.
    max_field_words: int = 120


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task: str  # writing_feedback | mistake_explanation | speaking_feedback
    # How the errors were seeded, for auditability.
    seeding_note: str | None = None
    input: CaseInput
    expect: Expectations


class CaseResult(BaseModel):
    case_id: str
    ok_json: bool
    deterministic_score: float = Field(ge=0, le=1)
    judge_score: float | None = None
    #  0.6 * deterministic + 0.4 * judge (deterministic-only if no judge).
    total: float = Field(ge=0, le=1)
    failures: list[str] = []
    raw_output: str = ""


class Scorecard(BaseModel):
    task: str
    runner: str
    prompt_version: int
    cases: int
    mean_total: float
    mean_deterministic: float
    mean_judge: float | None
    hallucination_rate: float  # fraction of cases claiming a must_not_claim tag
    results: list[CaseResult]
