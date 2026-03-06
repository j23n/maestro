"""Typed Pydantic models for LLM scoring responses."""

from __future__ import annotations

from pydantic import BaseModel


class ScoringResult(BaseModel):
    objective_correct: bool = False
    objective_note: str = ""
    grammar_errors: list[str] = []
    tips: list[str] = []
