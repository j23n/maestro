"""
Contextual feature hints shown once to new users, dismissable via HTMX.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from maestro.auth import get_current_student
from maestro.models import Student
from maestro.profile import get_or_create_profile

router = APIRouter()


@dataclass
class HintConfig:
    id: str
    message: str
    anchor_selector: str


HINTS: dict[str, HintConfig] = {
    "word_discovery": HintConfig(
        id="word_discovery",
        message=(
            "Italian words are highlighted automatically. "
            "Hover over any colored word to see its definition and add it to your vocabulary."
        ),
        anchor_selector=".vocab-word",
    ),
    "vocab_trainer": HintConfig(
        id="vocab_trainer",
        message=(
            "Press the Reveal button (or Space / Enter) to see the definition, "
            "then rate how well you knew it."
        ),
        anchor_selector="#reveal-btn",
    ),
    "vocab_page": HintConfig(
        id="vocab_page",
        message=(
            "Your words are organized into three stages: "
            "Due (need review today), Learning (seen recently), and Known (mastered). "
            "Words move between stages based on your reviews."
        ),
        anchor_selector=".vocab-section-header",
    ),
    "discovered_words_intro": HintConfig(
        id="discovered_words_intro",
        message=(
            "Underlined Italian words show a definition when you hover over them. Try it!"
        ),
        anchor_selector=".vocab-word",
    ),
}

# Which hints appear on which page
_PAGE_HINTS: dict[str, list[str]] = {
    "lesson_activity_grammar": ["word_discovery"],
    "lesson_activity_reading": ["word_discovery"],
    "lesson_activity_vocab": ["vocab_trainer"],
    "vocab_page": ["vocab_page"],
    "lesson_activity_info": ["discovered_words_intro"],
}


def hints_for_page(page_key: str, dismissed: list[str]) -> list[HintConfig]:
    """Return undismissed hints relevant to a page."""
    hint_ids = _PAGE_HINTS.get(page_key, [])
    return [HINTS[hid] for hid in hint_ids if hid not in dismissed]


@router.post("/hints/{hint_id}/dismiss")
async def dismiss_hint(hint_id: str, student: Student = Depends(get_current_student)):
    if hint_id not in HINTS:
        raise HTTPException(status_code=404)
    profile = await get_or_create_profile(student.id)
    if hint_id not in profile.dismissed_hints:
        profile.dismissed_hints.append(hint_id)
        await profile.save()
    return Response(status_code=204)
