"""Slot allocation by lesson duration."""

from __future__ import annotations

from maestro.models import ActivityType

_READING_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_READING_QUESTION_COUNT = 5


def _allocate_slots(duration_minutes: int) -> dict[str, int]:
    """Return counts of each activity type to include.

    LISTENING is the audio-comprehension variant of reading (always 1 per lesson).
    READING is the follow-up text-only reading (0 for short sessions, 1+ for longer).
    The LLM receives LISTENING + READING as its total reading count.
    """
    if duration_minutes <= 10:
        return {
            ActivityType.GRAMMAR: 1,
            ActivityType.DRILL: 3,
            ActivityType.VOCAB_REVIEW: 10,
            ActivityType.LISTENING: 1,
            ActivityType.READING: 0,
            ActivityType.WRITING: 1,
            ActivityType.SPEAKING: 1,
        }
    elif duration_minutes <= 20:
        return {
            ActivityType.GRAMMAR: 2,
            ActivityType.DRILL: 6,
            ActivityType.VOCAB_REVIEW: 15,
            ActivityType.LISTENING: 1,
            ActivityType.READING: 1,
            ActivityType.WRITING: 1,
            ActivityType.SPEAKING: 1,
        }
    else:  # 40 min
        return {
            ActivityType.GRAMMAR: 3,
            ActivityType.DRILL: 12,
            ActivityType.VOCAB_REVIEW: 25,
            ActivityType.LISTENING: 1,
            ActivityType.READING: 2,
            ActivityType.WRITING: 2,
            ActivityType.SPEAKING: 2,
        }
