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
from maestro.llm import get_client
from maestro.prompts import analyzer as _prompts
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)

_FALLBACK_ITEM = {"objective_correct": False, "objective_note": "", "grammar_errors": [], "tips": []}


def _client():
    return get_client()


async def feedback_fill_blank(
    drill_prompt: str,
    correct_answer: str,
    student_answer: str,
    grammar_point_code: str,
    rag_content: str = "",
) -> dict | str:
    """Generate structured feedback for a wrong fill-blank answer.

    Returns {"wrong": ..., "correct": ..., "explanation": ...}
    or empty string on any error.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content else ""
    )
    prompt = _prompts.feedback_fill_blank.render(
        grammar_point_code=grammar_point_code,
        drill_prompt=drill_prompt,
        correct_answer=correct_answer,
        student_answer=student_answer,
        rule_block=rule_block,
    )

    logger.info(f"[scorer] feedback_fill_blank: gp={grammar_point_code}, student={student_answer!r}, correct={correct_answer!r}")
    try:
        logger.debug(f"[scorer] feedback_fill_blank prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        explanation = response.content[0].text.strip()
        logger.debug(f"[scorer] feedback_fill_blank in {elapsed:.2f}s: {explanation!r}")
        return {"wrong": student_answer, "correct": correct_answer, "explanation": explanation}
    except Exception as e:
        logger.error(f"[scorer] feedback_fill_blank error: {e}", exc_info=True)
        return ""


async def evaluate_error_correction(
    erroneous: str,
    reference: str,
    student: str,
    rag_content: str = "",
) -> tuple[bool, dict | str]:
    """
    Use the LLM to judge whether the student's correction is essentially correct,
    allowing for punctuation differences and equivalent phrasing.
    Returns (correct, feedback) where feedback is
    {"wrong": ..., "correct": ..., "explanation": ...} or "" on failure.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content else ""
    )
    prompt = _prompts.evaluate_error_correction.render(
        erroneous=erroneous,
        reference=reference,
        student=student,
        rule_block=rule_block,
    )

    logger.info(f"[scorer] evaluate_error_correction: student={student!r}, reference={reference!r}")
    try:
        logger.debug(f"[scorer] evaluate_error_correction prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
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
    gp_label = next((g.label for g in taxonomy.grammar_points() if g.code == grammar_point_code), grammar_point_code)
    grammar_code_list = "\n".join(f"  {g.code}: {g.label}" for g in taxonomy.grammar_points())
    rule_block = f"\n\nGrammar rule reference:\n{rag_content}" if rag_content else ""

    if exercise_type == "fill_blank":
        task_desc = _prompts.task_fill_blank.render()
        lines = [
            f'{i + 1}. Sentence: "{items[i].prompt}" | Correct: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]
    else:  # error_correction
        task_desc = _prompts.task_error_correction.render()
        lines = [
            f'{i + 1}. Erroneous: "{items[i].prompt}" | Reference: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]

    prompt = _prompts.score_multi_item.render(
        task_desc=task_desc,
        gp_label=gp_label,
        grammar_point_code=grammar_point_code,
        rule_block=rule_block,
        grammar_code_list=grammar_code_list,
        items_block="\n".join(lines),
        n=n,
    )

    try:
        logger.debug(f"[scorer] score_multi_item_drill prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] score_multi_item_drill LLM in {elapsed:.2f}s: {raw}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[scorer] score_multi_item_drill: {n_correct}/{n} correct")
            return result
        logger.error(f"[scorer] score_multi_item_drill unexpected result shape: {raw}")
    except Exception as e:
        logger.error(f"[scorer] score_multi_item_drill error: {e}", exc_info=True)

    logger.warning(f"[scorer] score_multi_item_drill falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]


async def generate_writing_feedback(
    prompt: str,
    student_text: str,
    cefr_level: str,
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
        cefr_level=cefr_level,
        prompt=prompt,
        student_text=student_text,
    )

    try:
        logger.debug(f"[scorer] generate_writing_feedback prompt: {llm_prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] generate_writing_feedback LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[scorer] generate_writing_feedback unexpected shape: {raw}")
            return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}
        logger.info(
            f"[scorer] generate_writing_feedback: objective_correct={data.get('objective_correct')}, "
            f"{len(data.get('grammar_errors', []))} errors, {len(data.get('tips', []))} tips"
        )
        return data
    except Exception as e:
        logger.error(f"[scorer] generate_writing_feedback error: {e}", exc_info=True)
        return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}


async def score_free_form_drill(
    prompt: str,
    student_text: str,
    grammar_point_code: str,
    cefr_level: str = "A1",
    rag_content: str = "",
) -> dict:
    """Score a free-form drill response using task-completion as the sole pass/fail criterion.

    Returns {objective_correct, objective_note, grammar_errors, tips}.
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content else ""
    )
    logger.info(
        f"[scorer] score_free_form_drill: gp={grammar_point_code}, level={cefr_level}, "
        f"student={student_text[:60]!r}..."
    )

    llm_prompt = _prompts.score_free_form_drill.render(
        cefr_level=cefr_level,
        grammar_point_code=grammar_point_code,
        prompt=prompt,
        student_text=student_text,
        rule_block=rule_block,
    )

    try:
        logger.debug(f"[scorer] score_free_form_drill prompt: {llm_prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] score_free_form_drill LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[scorer] score_free_form_drill unexpected shape: {raw}")
            return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}
        logger.info(
            f"[scorer] score_free_form_drill: objective_correct={data.get('objective_correct')}, "
            f"{len(data.get('grammar_errors', []))} errors"
        )
        return data
    except Exception as e:
        logger.error(f"[scorer] score_free_form_drill error: {e}", exc_info=True)
        return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}


async def score_reading_answers(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
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
        items_block="\n".join(lines),
        n=n,
    )

    try:
        logger.debug(f"[scorer] score_reading_answers prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[scorer] score_reading_answers LLM in {elapsed:.2f}s: {raw}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[scorer] score_reading_answers: {n_correct}/{n} correct")
            return result
        logger.error(f"[scorer] score_reading_answers unexpected result shape: {raw}")
    except Exception as e:
        logger.error(f"[scorer] score_reading_answers error: {e}", exc_info=True)

    logger.warning(f"[scorer] score_reading_answers falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]
