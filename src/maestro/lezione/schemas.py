"""Typed Pydantic models for LLM lesson-content responses."""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel


class DrillItemResponse(BaseModel):
    prompt: str = ""
    correct_answer: Optional[str] = None


class DrillResponse(BaseModel):
    grammar_point_code: str = ""
    items: list[DrillItemResponse] = []
    prompt: Optional[str] = None
    correct_answer: Optional[str] = None
    distractors: list[str] = []


class ReadingQuestionResponse(BaseModel):
    text: str = ""
    correct_answer: str = ""
    grammar_point_codes: list[str] = []


class ReadingResponse(BaseModel):
    text: str = ""
    questions: list[Union[ReadingQuestionResponse, str]] = []
    answers: list[str] = []  # used when questions are flat strings (LLM output)


class WritingResponse(BaseModel):
    prompt: str = ""


class SpeakingResponse(BaseModel):
    prompt: str = ""


class LessonContentResponse(BaseModel):
    topic_title: str = ""
    topic_description: str = ""
    overview: str = ""
    drills: list[DrillResponse] = []
    readings: list[ReadingResponse] = []
    writing: Optional[WritingResponse] = None
    speakings: list[SpeakingResponse] = []
