"""
Drill scoring logic.

- fill_blank / error_correction: LLM evaluates per-item with objective-focused grading.
  Each item returns {objective_correct, objective_note, grammar_errors, tips,
  grammar_correct_codes, grammar_error_codes}.
  Drill pass/fail is based solely on objective_correct counts.
  All detected GP codes feed into the LearningEvent.
  Grammar errors and tips are freetext, surfaced in feedback only.

- free_form: LLM analysis → LearningEvent + feedback.

Returns (correct, event, feedback, rule_refs):
  correct    — bool or None
  event      — LearningEvent
  feedback   — dict {"items": [...], "correct_count": int, "total": int}
  rule_refs  — list of {"heading": str} for template display
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maestro.models import GeneratedDrill

from maestro.models import LearningEvent, GrammarChunk, ExerciseType
from maestro.learning.scorer import score_free_form_drill, score_multi_item_drill
from maestro import taxonomy

logger = logging.getLogger(__name__)

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
    if generated_drill.items and generated_drill.exercise_type in (
        ExerciseType.FILL_BLANK,
        ExerciseType.ERROR_CORRECTION,
    ):
        answers: list[str] = (
            student_answer if isinstance(student_answer, list) else [student_answer]
        )
        rag_content, rule_refs = await _get_rule_context(generated_drill)

        raw_results = await score_multi_item_drill(
            generated_drill.exercise_type,
            code,
            generated_drill.items,
            answers,
            rag_content,
            cefr_level=generated_drill.cefr_level,
        )

        n = min(len(generated_drill.items), len(answers), len(raw_results))
        enriched = [
            {
                "prompt": generated_drill.items[j].prompt,
                "correct_answer": generated_drill.items[j].correct_answer,
                "student_answer": answers[j] if j < len(answers) else "",
                "objective_correct": raw_results[j].get("objective_correct", False),
                "objective_note": raw_results[j].get("objective_note", ""),
                "grammar_errors": raw_results[j].get("grammar_errors", []),
                "tips": raw_results[j].get("tips", []),
            }
            for j in range(n)
        ]

        correct_count = sum(1 for r in enriched if r["objective_correct"])
        overall_correct = correct_count / max(n, 1) >= _PASS_THRESHOLD
        feedback: dict | str = {
            "items": enriched,
            "correct_count": correct_count,
            "total": n,
        }

        # Aggregate GP codes detected across all items, filtering out hallucinated codes
        valid_codes = {g.code for g in taxonomy.grammar_points()}
        all_correct_codes = list(
            {
                c
                for r in raw_results[:n]
                for c in r.get("grammar_correct_codes", [])
                if c in valid_codes
            }
        )
        all_error_codes = list(
            {
                c
                for r in raw_results[:n]
                for c in r.get("grammar_error_codes", [])
                if c in valid_codes
            }
        )

        if overall_correct:
            event = LearningEvent(
                student_id=student_id,
                grammar_correct=[code] + [c for c in all_correct_codes if c != code],
                grammar_errors=all_error_codes,
            )
            return overall_correct, event, feedback, []

        event = LearningEvent(
            student_id=student_id,
            grammar_correct=all_correct_codes,
            grammar_errors=[code] + [c for c in all_error_codes if c != code],
            feedback=json.dumps(feedback),
        )
        return overall_correct, event, feedback, rule_refs

    # --- free_form ---
    elif generated_drill.exercise_type == ExerciseType.FREE_FORM:
        answer_str = (
            student_answer[0] if isinstance(student_answer, list) else student_answer
        )
        rag_content, rule_refs = await _get_rule_context(generated_drill)

        feedback = await score_free_form_drill(
            generated_drill.prompt,
            answer_str,
            code,
            cefr_level=generated_drill.cefr_level,
            rag_content=rag_content,
        )
        correct = feedback.get("objective_correct", True)
        valid_codes = {g.code for g in taxonomy.grammar_points()}
        gp_correct = [
            c for c in feedback.get("grammar_correct_codes", []) if c in valid_codes
        ]
        gp_errors = [
            c for c in feedback.get("grammar_error_codes", []) if c in valid_codes
        ]
        event = LearningEvent(
            student_id=student_id,
            grammar_correct=([code] if correct else [])
            + [c for c in gp_correct if c != code],
            grammar_errors=([] if correct else [code])
            + [c for c in gp_errors if c != code],
        )
        refs = rule_refs if not correct else []
        return correct, event, feedback, refs

    logger.warning(f"[scoring] unknown exercise type: {generated_drill.exercise_type}")
    return None, None, "", []
