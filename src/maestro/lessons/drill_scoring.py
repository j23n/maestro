"""
Drill scoring logic.

- fill_blank / error_correction: LLM evaluates per-item with objective-focused grading.
  Each item returns {objective_correct, objective_note, grammar_errors, tips,
  grammar_correct_codes, grammar_error_codes}.
  Drill pass/fail is based solely on objective_correct counts.
  All detected GP codes feed into the LearningEvent.
  Grammar errors and tips are freetext, surfaced in feedback only.

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
from maestro.learning.scorer import score_multi_item_drill
from maestro.learning import grammar_cache

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.7  # fraction of items correct to count the drill as passed


def _dedup_grammar_errors(objective_note: str, grammar_errors: list[str]) -> list[str]:
    """Remove grammar_errors that overlap with objective_note."""
    if not objective_note or not grammar_errors:
        return grammar_errors
    note_lower = objective_note.lower()
    deduped = []
    for err in grammar_errors:
        # Extract the correction portion: text before " (" parenthetical explanation
        correction = err.split(" (")[0].strip() if " (" in err else err
        # Also try the part after "→" (e.g. "no parlo → non parlo")
        arrow_parts = correction.split("→")
        key_phrases = [correction.lower()]
        if len(arrow_parts) == 2:
            key_phrases.append(arrow_parts[1].strip().lower())
            key_phrases.append(arrow_parts[0].strip().lower())
        if not any(phrase in note_lower for phrase in key_phrases if len(phrase) > 2):
            deduped.append(err)
    return deduped


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
    lesson_id=None,
    language: str | None = None,
) -> tuple[bool | None, object | None, dict | str, list[dict]]:
    """Returns (correct, learning_event, feedback, rule_refs).

    For multi-item drills (fill_blank / error_correction with items),
    student_answer must be a list[str] and feedback is {"items": [...]}.
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
            student_id=student_id,
            lesson_id=lesson_id,
            language=language,
        )

        n = min(len(generated_drill.items), len(answers), len(raw_results))
        enriched = [
            {
                "prompt": generated_drill.items[j].prompt,
                "correct_answer": generated_drill.items[j].correct_answer,
                "student_answer": answers[j] if j < len(answers) else "",
                "objective_correct": raw_results[j].get("objective_correct", False),
                "objective_note": raw_results[j].get("objective_note", ""),
                "grammar_errors": _dedup_grammar_errors(
                    raw_results[j].get("objective_note", ""),
                    raw_results[j].get("grammar_errors", []),
                ),
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

        # Build per-item effective GP codes (item-level override or drill-level fallback)
        item_gp_codes = [
            generated_drill.items[j].grammar_point_code or code for j in range(n)
        ]

        # Credit/debit per-item GP codes based on objective_correct
        correct_gp_set: set[str] = set()
        error_gp_set: set[str] = set()
        for j in range(n):
            if enriched[j]["objective_correct"]:
                correct_gp_set.add(item_gp_codes[j])
            else:
                error_gp_set.add(item_gp_codes[j])

        # Also aggregate LLM-detected GP codes, filtering out hallucinated ones
        valid_codes = {g.code for g in grammar_cache.grammar_points()}
        raw_correct = [
            c for r in raw_results[:n] for c in r.get("grammar_correct_codes", [])
        ]
        raw_errors = [
            c for r in raw_results[:n] for c in r.get("grammar_error_codes", [])
        ]
        llm_correct_codes = {c for c in raw_correct if c in valid_codes}
        llm_error_codes = {c for c in raw_errors if c in valid_codes}
        filtered_out = [c for c in raw_correct + raw_errors if c not in valid_codes]
        if filtered_out:
            logger.debug(
                "GP codes filtered out (not in taxonomy)",
                extra={"lesson_id": str(lesson_id), "filtered_codes": filtered_out},
            )

        # Merge per-item GP tracking with LLM-detected codes
        all_correct_codes = list(correct_gp_set | llm_correct_codes)
        all_error_codes = list(error_gp_set | llm_error_codes)
        logger.debug(
            "drill GP codes after filter",
            extra={
                "lesson_id": str(lesson_id),
                "all_correct_codes": all_correct_codes,
                "all_error_codes": all_error_codes,
            },
        )

        if overall_correct:
            event = LearningEvent(
                student_id=student_id,
                evidence_type="targeted",
                grammar_correct=all_correct_codes,
                grammar_errors=all_error_codes,
            )
            return overall_correct, event, feedback, []

        event = LearningEvent(
            student_id=student_id,
            evidence_type="targeted",
            grammar_correct=all_correct_codes,
            grammar_errors=all_error_codes,
            feedback=json.dumps(feedback),
        )
        return overall_correct, event, feedback, rule_refs

    logger.warning(
        "unknown exercise type", extra={"exercise_type": generated_drill.exercise_type}
    )
    return None, None, "", []
