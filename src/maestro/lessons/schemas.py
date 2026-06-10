"""Typed Pydantic models for lesson-content payloads.

Used both for validated LLM responses and for content assembled from the
static banks (lessons.bank_assembly) — the `vocab_annotations` fields are
only populated on the bank path, carrying pre-verified vocab mappings
through to the materialized activities.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator

from maestro.models import VocabAnnotation


class DrillItemResponse(BaseModel):
    prompt: str = ""
    correct_answer: Optional[str] = None
    hint: Optional[str] = None


class DrillResponse(BaseModel):
    grammar_point_code: str = ""
    items: list[DrillItemResponse] = []
    prompt: Optional[str] = None
    correct_answer: Optional[str] = None
    distractors: list[str] = []
    vocab_annotations: list[VocabAnnotation] = []


class ReadingQuestionResponse(BaseModel):
    text: str = ""
    correct_answer: str = ""
    grammar_point_codes: list[str] = []


class ReadingResponse(BaseModel):
    text: str = ""
    questions: list[ReadingQuestionResponse] = []
    vocab_annotations: list[VocabAnnotation] = []

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_questions(cls, data):
        """LLM may return questions as flat strings; coerce into structured form."""
        if isinstance(data, dict):
            qs = data.get("questions")
            if qs and isinstance(qs, list) and qs and isinstance(qs[0], str):
                answers = data.pop("answers", [])
                data["questions"] = [
                    {
                        "text": q,
                        "correct_answer": answers[i] if i < len(answers) else "",
                    }
                    for i, q in enumerate(qs)
                ]
            elif "answers" in data:
                data.pop("answers")
        return data


class WritingResponse(BaseModel):
    prompt: str = ""
    vocab_annotations: list[VocabAnnotation] = []


class SpeakingResponse(BaseModel):
    prompt: str = ""
    vocab_annotations: list[VocabAnnotation] = []


class LessonContentResponse(BaseModel):
    topic_title: str = ""
    topic_description: str = ""
    overview: str = ""
    drills: list[DrillResponse] = []
    listenings: list[ReadingResponse] = []
    readings: list[ReadingResponse] = []
    writing: Optional[WritingResponse] = None
    speakings: list[SpeakingResponse] = []
