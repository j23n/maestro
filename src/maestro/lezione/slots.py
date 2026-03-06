"""Slot allocation by lesson duration."""

from __future__ import annotations

_READING_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_READING_QUESTION_COUNT = 5


def _allocate_slots(duration_minutes: int) -> dict[str, int]:
    """Return counts of each activity type to include."""
    if duration_minutes <= 10:
        return {
            "grammar": 1,
            "drill": 3,
            "vocab_review": 10,
            "reading": 1,
            "writing": 1,
            "speaking": 1,
        }
    elif duration_minutes <= 20:
        return {
            "grammar": 2,
            "drill": 6,
            "vocab_review": 15,
            "reading": 2,
            "writing": 1,
            "speaking": 1,
        }
    else:  # 40 min
        return {
            "grammar": 3,
            "drill": 12,
            "vocab_review": 25,
            "reading": 3,
            "writing": 2,
            "speaking": 2,
        }
