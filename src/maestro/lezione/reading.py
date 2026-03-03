"""
Generate a level-appropriate Italian reading text with comprehension questions.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anthropic

from maestro.settings import Settings
from maestro.utils import parse_llm_json

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
settings = Settings()


def generate_reading(
    cefr_level: str,
    topic: str,
    client: anthropic.Anthropic,
) -> tuple[str, list[str], list[str]] | None:
    """Return (text, questions, correct_answers) or None on failure."""
    word_count = {"A1": 80, "A2": 120, "B1": 200, "B2": 300}.get(cefr_level, 150)
    prompt = (
        f"Write a {word_count}-word Italian reading text at {cefr_level} level "
        f"about: {topic}. "
        "Then write exactly 3 comprehension questions in Italian with short correct answers.\n\n"
        "Return ONLY valid JSON (no markdown, no explanation):\n"
        '{"text":"...","questions":["...","...","..."],"answers":["...","...","..."]}'
    )
    response = client.messages.create(
        model=settings.DRILL_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    data = parse_llm_json(response.content[0].text)
    if not data:
        logger.warning("[reading] Failed to parse response")
        return None
    return (
        data.get("text", ""),
        data.get("questions", []),
        data.get("answers", []),
    )


def generate_writing_prompt(
    cefr_level: str,
    topic: str,
    client: anthropic.Anthropic,
) -> str | None:
    """Return a writing prompt string or None on failure."""
    prompt = (
        f"Write one open-ended Italian writing prompt at {cefr_level} level "
        f"on the topic: {topic}. "
        "It should ask the student to write a short text (3–6 sentences). "
        "Return ONLY the prompt text in Italian, no JSON, no explanation."
    )
    response = client.messages.create(
        model=settings.DRILL_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip() or None
