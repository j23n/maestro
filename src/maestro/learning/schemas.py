"""Typed Pydantic models for LLM scoring responses."""

from __future__ import annotations

from pydantic import BaseModel


class ScoringResult(BaseModel):
    objective_correct: bool = False
    objective_note: str = ""
    grammar_errors: list[str] = []
    tips: list[str] = []
    grammar_correct_codes: list[str] = []
    grammar_error_codes: list[str] = []
    themes: list[str] = []
