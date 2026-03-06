"""Typed Pydantic models for LLM lesson-content responses."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GrammarMotivation(BaseModel):
    code: str = ""
    text: str = ""


class DrillItemResponse(BaseModel):
    prompt: str = ""
    correct_answer: Optional[str] = None


class DrillResponse(BaseModel):
    grammar_point_code: str = ""
    items: list[DrillItemResponse] = []
    prompt: Optional[str] = None
    correct_answer: Optional[str] = None
    distractors: list[str] = []


class ReadingResponse(BaseModel):
    text: str = ""
    questions: list[str] = []
    answers: list[str] = []


class WritingResponse(BaseModel):
    prompt: str = ""


class SpeakingResponse(BaseModel):
    prompt: str = ""


class LessonContentResponse(BaseModel):
    topic_title: str = ""
    topic_description: str = ""
    overview: str = ""
    grammar_motivations: list[GrammarMotivation] = []
    drills: list[DrillResponse] = []
    readings: list[ReadingResponse] = []
    writing: Optional[WritingResponse] = None
    speakings: list[SpeakingResponse] = []
