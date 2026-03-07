"""
Drill scoring logic.

- fill_blank / error_correction: LLM evaluates per-item with objective-focused grading.
  Each item returns {objective_correct, objective_note, grammar_errors, tips}.
  Drill pass/fail is based solely on objective_correct counts.
  All grammar errors (objective + other) feed into the LearningEvent.
  Tips (spelling/accent) are surfaced in feedback only, no learning event.

- free_form: LLM analysis → LearningEvent + feedback.

Returns (correct, event, feedback, rule_refs):
  correct    — bool or None
  event      — LearningEvent
  feedback   — dict {"items": [...], "correct_count": int, "total": int}
  rule_refs  — list of {"heading": str} for template display
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maestro.models import GeneratedDrill

from maestro.models import LearningEvent, GrammarChunk, ExerciseType
from maestro.learning.scorer import score_free_form_drill, score_multi_item_drill
from maestro import taxonomy

_PASS_THRESHOLD = 0.7  # fraction of items correct to count the drill as passed


async def _get_rule_context(
    drill: "GeneratedDrill",
) -> tuple[str, list[dict]]:
    """Load the chunk stored on this drill via chunk_ref. Returns (chunk_content, rule_refs)."""
    if not drill.chunk_ref:
        return "", []
    chunk = await GrammarChunk.find_one({"ref": drill.chunk_ref})
    if not chunk:
        return "", []
    heading = chunk.chunk_metadata.get("heading", chunk.ref)
    return chunk.content, [{"heading": heading, "ref": drill.chunk_ref}]


async def score_attempt(
    generated_drill: "GeneratedDrill",
    student_answer: str | list[str],
    student_id=None,
) -> tuple[bool | None, object | None, dict | str, list[dict]]:
    """Returns (correct, learning_event, feedback, rule_refs).

    For multi-item drills (fill_blank / error_correction with items),
    student_answer must be a list[str] and feedback is {"items": [...]}.
    For free_form, student_answer is a plain str.
    """
    code = generated_drill.grammar_point_code

    # --- multi-item: fill_blank or error_correction with items list ---
    if generated_drill.items and generated_drill.exercise_type in (ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION):
        answers: list[str] = student_answer if isinstance(student_answer, list) else [student_answer]
        rag_content, rule_refs = await _get_rule_context(generated_drill)

        raw_results = await score_multi_item_drill(
            generated_drill.exercise_type,
            code,
            generated_drill.items,
            answers,
            rag_content,
        )

        # Resolve grammar codes → human-readable labels for display
        await taxonomy.ensure_loaded()
        valid_codes = {g.code for g in taxonomy.grammar_points()}
        gp_labels = {g.code: g.label for g in taxonomy.grammar_points()}

        n = min(len(generated_drill.items), len(answers), len(raw_results))
        enriched = [
            {
                "prompt": generated_drill.items[j].prompt,
                "correct_answer": generated_drill.items[j].correct_answer,
                "student_answer": answers[j] if j < len(answers) else "",
                "objective_correct": raw_results[j].get("objective_correct", False),
                "objective_note": raw_results[j].get("objective_note", ""),
                "grammar_errors": [
                    gp_labels[c]
                    for c in raw_results[j].get("grammar_errors", [])
                    if c in valid_codes
                ],
                "tips": raw_results[j].get("tips", []),
            }
            for j in range(n)
        ]

        correct_count = sum(1 for r in enriched if r["objective_correct"])
        overall_correct = correct_count / max(n, 1) >= _PASS_THRESHOLD
        feedback: dict | str = {"items": enriched, "correct_count": correct_count, "total": n}

        # Aggregate all other grammar error codes across items for the learning event
        other_error_codes = list({
            c
            for r in raw_results[:n]
            for c in r.get("grammar_errors", [])
            if c in valid_codes
        })

        if overall_correct:
            event = LearningEvent(student_id=student_id, grammar_correct=[code], grammar_errors=other_error_codes)
            return overall_correct, event, feedback, []

        event = LearningEvent(
            student_id=student_id,
            grammar_errors=[code] + other_error_codes,
            feedback=json.dumps(feedback),
        )
        return overall_correct, event, feedback, rule_refs

    # --- free_form ---
    elif generated_drill.exercise_type == ExerciseType.FREE_FORM:
        answer_str = student_answer[0] if isinstance(student_answer, list) else student_answer
        rag_content, rule_refs = await _get_rule_context(generated_drill)

        feedback = await score_free_form_drill(
            generated_drill.prompt, answer_str, code,
            cefr_level=generated_drill.cefr_level, rag_content=rag_content,
        )
        correct = feedback.get("objective_correct", True)
        event = LearningEvent(
            student_id=student_id,
            grammar_correct=[code] if correct else [],
            grammar_errors=[] if correct else [code],
        )
        refs = rule_refs if not correct else []
        return correct, event, feedback, refs

    return None, None, "", []
