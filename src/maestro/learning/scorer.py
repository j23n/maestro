"""
Scoring and feedback generation for drills, writing, and reading activities.

Each function calls an LLM to evaluate student responses and returns
structured feedback dicts.
"""

from __future__ import annotations

import logging
import time

from maestro import taxonomy
from maestro.config import settings
from maestro.llm import get_async_client, log_llm_usage

from maestro.models import ExerciseType
from maestro.prompts import analyzer as _prompts
from maestro.utils import parse_llm_json
from maestro.learning.schemas import ScoringResult

logger = logging.getLogger(__name__)

_TL = None  # lazy cache for target language name


def _target_language() -> str:
    global _TL
    if _TL is None:
        _TL = settings.TARGET_LANGUAGE_NAME
    return _TL


_FALLBACK_ITEM = ScoringResult().model_dump()


def _client():
    return get_async_client()


def _validate_results(result: list, n: int, label: str) -> list[dict]:
    """Validate a list of raw dicts into ScoringResult dicts, with per-item fallback."""
    validated = []
    for r in result:
        try:
            validated.append(ScoringResult.model_validate(r).model_dump())
        except Exception:
            validated.append(dict(_FALLBACK_ITEM))
    n_correct = sum(1 for r in validated if r.get("objective_correct"))
    logger.info(f"[scorer] {label}: {n_correct}/{n} correct")
    return validated


def _grammar_code_list(cefr_level: str) -> str:
    return "\n".join(
        f"  {g.code}: {g.label}"
        for g in taxonomy.grammar_points()
        if g.cefr_level == cefr_level
    )


def _feedback_language(cefr_level: str) -> str:
    if cefr_level == "A0":
        return "English (use only Italian words the student has learned)"
    elif cefr_level == "A1":
        return "a mix of Italian and English"
    return _target_language()


def _system_prompt(cefr_level: str) -> str:
    return _prompts.scoring_system.render_system(
        target_language=_target_language(),
        feedback_language=_feedback_language(cefr_level),
        grammar_code_list=_grammar_code_list(cefr_level),
    )


async def _score_single(
    prompt: str,
    *,
    max_tokens: int = 512,
    label: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
) -> dict:
    """LLM call -> JSON parse -> ScoringResult validation. Falls back to objective_correct=True."""
    try:
        await taxonomy.ensure_loaded()
        logger.debug(f"[scorer] {label} prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client().messages.create(
            model=settings.SCORING_MODEL,
            max_tokens=max_tokens,
            system=_system_prompt(cefr_level),
            messages=[{"role": "user", "content": prompt}],
        )
        log_llm_usage(response, "score", student_id=student_id, lesson_id=lesson_id)
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] {label} LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[scorer] {label} unexpected shape: {raw}")
            return ScoringResult(objective_correct=True).model_dump()
        try:
            validated = ScoringResult.model_validate(data)
        except Exception:
            logger.warning(f"[scorer] {label} validation partial, using raw dict")
            validated = ScoringResult(objective_correct=True)
        logger.info(
            f"[scorer] {label}: objective_correct={validated.objective_correct}, "
            f"{len(validated.grammar_errors)} errors"
        )
        return validated.model_dump()
    except Exception as e:
        logger.error(f"[scorer] {label} error: {e}", exc_info=True)
        return ScoringResult(objective_correct=True).model_dump()


async def _score_multi(
    prompt: str,
    n: int,
    *,
    max_tokens: int = 4000,
    label: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
) -> list[dict]:
    """LLM call -> JSON array parse -> per-item ScoringResult validation. Falls back to all-incorrect."""
    try:
        await taxonomy.ensure_loaded()
        logger.debug(f"[scorer] {label} prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client().messages.create(
            model=settings.SCORING_MODEL,
            max_tokens=max_tokens,
            system=_system_prompt(cefr_level),
            messages=[{"role": "user", "content": prompt}],
        )
        log_llm_usage(response, "score", student_id=student_id, lesson_id=lesson_id)
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] {label} LLM in {elapsed:.2f}s: {raw}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            return _validate_results(result, n, label)
        logger.error(f"[scorer] {label} unexpected result shape: {raw}")
    except Exception as e:
        logger.error(f"[scorer] {label} error: {e}", exc_info=True)
    logger.warning(f"[scorer] {label} falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]


async def feedback_fill_blank(
    drill_prompt: str,
    correct_answer: str,
    student_answer: str,
    grammar_point_code: str,
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
) -> dict | str:
    """Generate structured feedback for a wrong fill-blank answer.

    Returns {"wrong": ..., "correct": ..., "explanation": ...}
    or empty string on any error.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content
        else ""
    )
    prompt = _prompts.feedback_fill_blank.render(
        target_language=_target_language(),
        feedback_language=_feedback_language(cefr_level),
        grammar_point_code=grammar_point_code,
        drill_prompt=drill_prompt,
        correct_answer=correct_answer,
        student_answer=student_answer,
        rule_block=rule_block,
    )

    logger.info(
        f"[scorer] feedback_fill_blank: gp={grammar_point_code}, student={student_answer!r}, correct={correct_answer!r}"
    )
    try:
        logger.debug(f"[scorer] feedback_fill_blank prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client().messages.create(
            model=settings.SCORING_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        log_llm_usage(
            response, "score_fill_blank", student_id=student_id, lesson_id=lesson_id
        )
        elapsed = time.monotonic() - t0
        explanation = response.content[0].text.strip()
        logger.debug(f"[scorer] feedback_fill_blank in {elapsed:.2f}s: {explanation!r}")
        return {
            "wrong": student_answer,
            "correct": correct_answer,
            "explanation": explanation,
        }
    except Exception as e:
        logger.error(f"[scorer] feedback_fill_blank error: {e}", exc_info=True)
        return ""


async def evaluate_error_correction(
    erroneous: str,
    reference: str,
    student: str,
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
) -> tuple[bool, dict | str]:
    """
    Use the LLM to judge whether the student's correction is essentially correct,
    allowing for punctuation differences and equivalent phrasing.
    Returns (correct, feedback) where feedback is
    {"wrong": ..., "correct": ..., "explanation": ...} or "" on failure.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content
        else ""
    )
    prompt = _prompts.evaluate_error_correction.render(
        target_language=_target_language(),
        feedback_language=_feedback_language(cefr_level),
        erroneous=erroneous,
        reference=reference,
        student=student,
        rule_block=rule_block,
    )

    logger.info(
        f"[scorer] evaluate_error_correction: student={student!r}, reference={reference!r}"
    )
    try:
        logger.debug(f"[scorer] evaluate_error_correction prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client().messages.create(
            model=settings.SCORING_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        log_llm_usage(
            response,
            "score_error_correction",
            student_id=student_id,
            lesson_id=lesson_id,
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[scorer] evaluate_error_correction in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[scorer] evaluate_error_correction failed to parse: {raw}")
            correct = student.strip().lower() == reference.strip().lower()
            return correct, ""
        is_correct = bool(data.get("correct", False))
        logger.info(f"[scorer] evaluate_error_correction result: correct={is_correct}")
        feedback: dict | str = {
            "wrong": student,
            "correct": reference,
            "explanation": data.get("explanation", ""),
        }
        return is_correct, feedback
    except Exception as e:
        logger.error(f"[scorer] evaluate_error_correction error: {e}", exc_info=True)
        correct = student.strip().lower() == reference.strip().lower()
        return correct, ""


async def score_multi_item_drill(
    exercise_type: str,
    grammar_point_code: str,
    items: list,
    student_answers: list[str],
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
) -> list[dict]:
    """Score all items in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per item.
    """
    n = min(len(items), len(student_answers))
    logger.info(
        f"[scorer] score_multi_item_drill: type={exercise_type}, gp={grammar_point_code}, "
        f"n_items={n}, rag={'yes' if rag_content else 'no'}"
    )

    await taxonomy.ensure_loaded()
    gp_label = next(
        (g.label for g in taxonomy.grammar_points() if g.code == grammar_point_code),
        grammar_point_code,
    )
    rule_block = f"\n\nGrammar rule reference:\n{rag_content}" if rag_content else ""

    if exercise_type == ExerciseType.FILL_BLANK:
        task_desc = _prompts.task_fill_blank.render(target_language=_target_language())
        lines = [
            f'{i + 1}. Sentence: "{items[i].prompt}" | Correct: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]
    else:  # error_correction
        task_desc = _prompts.task_error_correction.render(
            target_language=_target_language()
        )
        lines = [
            f'{i + 1}. Erroneous: "{items[i].prompt}" | Reference: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]

    prompt = _prompts.score_multi_item.render(
        target_language=_target_language(),
        task_desc=task_desc,
        gp_label=gp_label,
        grammar_point_code=grammar_point_code,
        rule_block=rule_block,
        items_block="\n".join(lines),
        n=n,
    )

    return await _score_multi(
        prompt,
        n,
        label="score_multi_item_drill",
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
    )


async def generate_writing_feedback(
    prompt: str,
    student_text: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
) -> dict:
    """Generate feedback for a free-writing activity.

    Returns {objective_correct, objective_note, grammar_errors, tips} or
    {objective_correct: True, ...} on disabled / failure.
    """
    word_count = len(student_text.split())
    logger.info(
        f"[scorer] generate_writing_feedback: level={cefr_level}, "
        f"{word_count} words, prompt={prompt[:60]!r}..."
    )

    llm_prompt = _prompts.generate_writing_feedback.render(
        target_language=_target_language(),
        cefr_level=cefr_level,
        prompt=prompt,
        student_text=student_text,
    )

    return await _score_single(
        llm_prompt,
        label="generate_writing_feedback",
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
    )


async def score_free_form_drill(
    prompt: str,
    student_text: str,
    grammar_point_code: str,
    cefr_level: str,
    rag_content: str = "",
    student_id=None,
    lesson_id=None,
) -> dict:
    """Score a free-form drill response using task-completion as the sole pass/fail criterion.

    Returns {objective_correct, objective_note, grammar_errors, tips}.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content
        else ""
    )
    logger.info(
        f"[scorer] score_free_form_drill: gp={grammar_point_code}, level={cefr_level}, "
        f"student={student_text[:60]!r}..."
    )

    llm_prompt = _prompts.score_free_form_drill.render(
        target_language=_target_language(),
        cefr_level=cefr_level,
        grammar_point_code=grammar_point_code,
        prompt=prompt,
        student_text=student_text,
        rule_block=rule_block,
    )

    return await _score_single(
        llm_prompt,
        label="score_free_form_drill",
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
    )


async def score_reading_answers(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
) -> list[dict]:
    """Score student answers to reading comprehension questions in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per question.
    """
    n = min(len(questions), len(student_answers))
    logger.info(f"[scorer] score_reading_answers: {n} questions")

    lines = [
        f'{i + 1}. Question: "{questions[i]}" | Expected: "{correct_answers[i] if i < len(correct_answers) else ""}" | Student: "{student_answers[i]}"'
        for i in range(n)
    ]

    prompt = _prompts.score_reading_answers.render(
        target_language=_target_language(),
        items_block="\n".join(lines),
        n=n,
    )

    return await _score_multi(
        prompt,
        n,
        label="score_reading_answers",
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
    )
