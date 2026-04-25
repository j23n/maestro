"""Lesson-content output schema builder.

Produces the JSON-shaped *example* embedded in the planner prompt — separate
from `LessonContentResponse` (the validation schema) so the prompt's expected
shape lives in one place and can evolve without touching the prompt assembler.

The shape is dynamic: which top-level fields appear depends on the activity
slots requested for this lesson. Listenings and readings live in distinct
fields with different field-level guidance — listenings are TTS-bound and
require the em-dash dialogue convention, readings optimise for visual flow.
"""

from __future__ import annotations

from maestro.models import CommunicativeFunction, ExerciseType
from maestro.lessons.slots import _READING_QUESTION_COUNT, _READING_WORD_COUNT


def _drill_example(spec: dict) -> dict:
    if spec["exercise_type"] in (
        ExerciseType.FILL_BLANK,
        ExerciseType.ERROR_CORRECTION,
    ):
        return {
            "grammar_point_code": spec["grammar_point_code"],
            "items": [
                {"prompt": "...", "correct_answer": "..."},
                "... 10 items total",
            ],
        }
    return {
        "grammar_point_code": spec["grammar_point_code"],
        "prompt": "...",
        "correct_answer": None,
        "distractors": [],
    }


def _question_examples() -> list[dict]:
    return [
        {"text": f"question {i + 1}", "correct_answer": f"answer {i + 1}"}
        for i in range(_READING_QUESTION_COUNT)
    ]


def build_output_schema(
    *,
    language_name: str,
    cefr_level: str,
    drill_specs: list[dict],
    listening_count: int,
    reading_count: int,
    include_writing: bool,
    speaking_cfs: list[CommunicativeFunction],
) -> dict:
    """Return the JSON-shaped example for the planner prompt's <output_schema>.

    Only includes top-level fields for activity slots that this lesson needs.
    """
    word_count = _READING_WORD_COUNT.get(cefr_level, 150)

    schema: dict = {
        "topic_title": f"A creative {language_name} title for this lesson (3-8 words)",
        "topic_description": "1-2 sentences describing the specific situation covered",
        "overview": (
            f"2-3 sentences in {language_name}: what this lesson covers and what "
            f"the student will gain"
        ),
    }

    if drill_specs:
        schema["drills"] = [_drill_example(s) for s in drill_specs]

    if listening_count > 0:
        schema["listenings"] = [
            {
                "text": (
                    f"{language_name} dialogue (~{word_count} words at {cefr_level} "
                    f"level) on the lesson topic. REQUIRED format: a two-speaker "
                    f"dialogue with each speaker turn on its own line prefixed by "
                    f"'— ' (em-dash + space). An optional narrator scene-setter "
                    f"sentence may precede the first dialogue line. This text is "
                    f"rendered as audio with alternating TTS voices, so favour "
                    f"short natural sentences and clear turn-taking."
                ),
                "questions": _question_examples(),
            }
            for _ in range(listening_count)
        ]

    if reading_count > 0:
        schema["readings"] = [
            {
                "text": (
                    f"{language_name} reading text (~{word_count} words at "
                    f"{cefr_level} level) on the lesson topic. Optimise for visual "
                    f"reading: prose or dialogue both work, longer sentences and "
                    f"denser prose are fine. Will be displayed as text only, not "
                    f"played as audio."
                ),
                "questions": _question_examples(),
            }
            for _ in range(reading_count)
        ]

    if include_writing:
        schema["writing"] = {
            "prompt": (
                f"A {language_name} writing prompt appropriate for {cefr_level} "
                f"level on the lesson topic"
            )
        }

    if speaking_cfs:
        schema["speakings"] = [
            {
                "prompt": (
                    f"2-3 sentence {language_name} speaking prompt asking the "
                    f"student to practise {cf.label}. If the prompt embeds a "
                    f"mini-dialogue for context, mark each speaker turn with "
                    f"'— ' (em-dash + space) at the start of its line."
                )
            }
            for cf in speaking_cfs
        ]

    return schema
