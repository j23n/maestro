"""
Scoring and feedback generation for drills, writing, and reading activities.

Each function calls an LLM to evaluate student responses and returns
structured feedback dicts.
"""

from __future__ import annotations

import logging

from maestro.language import get_language_config
from maestro.learning import grammar_cache
from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType

from maestro.models import DrillItem, ExerciseType
from maestro.prompts import analyzer as _prompts, span_tagging_block as _stb
from maestro.utils import parse_llm_json
from maestro.learning.schemas import ScoringResult

logger = logging.getLogger(__name__)


def _validate_results(result: list, n: int, label: str) -> list[dict]:
    """Validate a list of raw dicts into ScoringResult dicts."""
    validated = [ScoringResult.model_validate(r).model_dump() for r in result]
    n_correct = sum(1 for r in validated if r.get("objective_correct"))
    logger.info("scored items", extra={"label": label, "n_correct": n_correct, "n": n})
    for r in validated:
        if r.get("grammar_errors") and not r.get("grammar_error_codes"):
            logger.warning(
                "grammar errors detected as freetext but no GP codes returned (multi)",
                extra={"label": label, "grammar_errors": r["grammar_errors"]},
            )
    logger.debug(
        "scored items detail",
        extra={
            "label": label,
            "grammar_error_codes": [
                c for r in validated for c in r.get("grammar_error_codes", [])
            ],
            "grammar_correct_codes": [
                c for r in validated for c in r.get("grammar_correct_codes", [])
            ],
        },
    )
    return validated


def _grammar_code_list(cefr_level: str, language: str) -> str:
    return "\n".join(
        f"  {g.code}: {g.label}"
        for g in grammar_cache.grammar_points(language)
        if g.cefr_level == cefr_level
    )


def _feedback_language(cefr_level: str, language_name: str) -> str:
    if cefr_level == "A0":
        return f"English (use only {language_name} words the student has learned)"
    elif cefr_level == "A1":
        return f"a mix of {language_name} and English"
    return language_name


def _system_prompt(
    cefr_level: str,
    language_name: str,
    language_code: str,
) -> str:
    return _prompts.scoring_system.render_system(
        target_language=language_name,
        feedback_language=_feedback_language(cefr_level, language_name),
        grammar_code_list=_grammar_code_list(cefr_level, language_code),
        span_tagging=_stb(language_name, language_code),
    )


async def _score_single(
    prompt: str,
    *,
    max_tokens: int = 512,
    label: str,
    cefr_level: str,
    model: str | None = None,
    student_id=None,
    lesson_id=None,
    language: str,
) -> dict:
    """LLM call -> JSON parse -> ScoringResult validation."""
    lang_cfg = get_language_config(language)
    await grammar_cache.ensure_loaded(lang_cfg.code)
    effective_model = model or settings.SCORING_MODEL
    logger.debug("%s using model=%s", label, effective_model)
    response = await llm_messages_create(
        model=effective_model,
        max_tokens=max_tokens,
        system=_system_prompt(cefr_level, lang_cfg.name, lang_cfg.code),
        messages=[{"role": "user", "content": prompt}],
        entity_id=lesson_id,
        call_type=CallType.SCORER_SINGLE,
        student_id=student_id,
    )
    raw = response.content[0].text.strip()
    logger.debug(f"{label} LLM response: {raw}")
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError(f"unexpected LLM response shape: {raw!r}")
    validated = ScoringResult.model_validate(data)
    if validated.grammar_errors and not validated.grammar_error_codes:
        logger.warning(
            "grammar errors detected as freetext but no GP codes returned",
            extra={
                "label": label,
                "lesson_id": str(lesson_id),
                "cefr_level": cefr_level,
                "grammar_errors": validated.grammar_errors,
            },
        )
    logger.info(
        "scoring result",
        extra={
            "label": label,
            "lesson_id": str(lesson_id),
            "cefr_level": cefr_level,
            "objective_correct": validated.objective_correct,
            "grammar_errors": validated.grammar_errors,
            "grammar_error_codes": validated.grammar_error_codes,
            "grammar_correct_codes": validated.grammar_correct_codes,
        },
    )
    return validated.model_dump()


async def _score_multi(
    prompt: str,
    n: int,
    *,
    max_tokens: int = 4000,
    label: str,
    cefr_level: str,
    model: str | None = None,
    student_id=None,
    lesson_id=None,
    language: str,
) -> list[dict]:
    """LLM call -> JSON array parse -> per-item ScoringResult validation."""
    if n == 0:
        return []
    lang_cfg = get_language_config(language)
    await grammar_cache.ensure_loaded(lang_cfg.code)
    effective_model = model or settings.SCORING_MODEL
    logger.debug("%s using model=%s (n=%d)", label, effective_model, n)
    response = await llm_messages_create(
        model=effective_model,
        max_tokens=max_tokens,
        system=_system_prompt(cefr_level, lang_cfg.name, lang_cfg.code),
        messages=[{"role": "user", "content": prompt}],
        entity_id=lesson_id,
        call_type=CallType.SCORER_MULTI,
        student_id=student_id,
    )
    raw = response.content[0].text.strip()
    logger.debug(f"{label} LLM response: {raw}")
    result = parse_llm_json(raw)
    if isinstance(result, dict) and n == 1:
        result = [result]
    if not isinstance(result, list) or len(result) != n:
        raise ValueError(f"unexpected LLM response shape: {raw!r}")
    return _validate_results(result, n, label)


async def feedback_fill_blank(
    drill_prompt: str,
    correct_answer: str,
    student_answer: str,
    grammar_point_code: str,
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
    *,
    language: str,
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
    lang_cfg = get_language_config(language)
    lang_name, lang_code = lang_cfg.name, lang_cfg.code
    prompt = _prompts.feedback_fill_blank.render(
        target_language=lang_name,
        feedback_language=_feedback_language(cefr_level, lang_name),
        grammar_point_code=grammar_point_code,
        drill_prompt=drill_prompt,
        correct_answer=correct_answer,
        student_answer=student_answer,
        rule_block=rule_block,
        span_tagging=_stb(lang_name, lang_code),
    )

    logger.info(
        "feedback_fill_blank",
        extra={
            "grammar_point_code": grammar_point_code,
            "student_answer": student_answer,
            "correct_answer": correct_answer,
        },
    )
    try:
        logger.debug(f"feedback_fill_blank prompt: {prompt}")
        response = await llm_messages_create(
            model=settings.DRILL_MODEL,
            max_tokens=128,
            system=_prompts.feedback_fill_blank.render_system(
                target_language=lang_name,
                feedback_language=_feedback_language(cefr_level, lang_name),
                span_tagging=_stb(lang_name, lang_code),
            ),
            messages=[{"role": "user", "content": prompt}],
            entity_id=lesson_id,
            call_type=CallType.SCORER_SINGLE,
            student_id=student_id,
        )
        explanation = response.content[0].text.strip()
        logger.debug(f"feedback_fill_blank response: {explanation!r}")
        return {
            "wrong": student_answer,
            "correct": correct_answer,
            "explanation": explanation,
        }
    except Exception:
        logger.error("feedback_fill_blank error", exc_info=True)
        return ""


async def evaluate_error_correction(
    erroneous: str,
    reference: str,
    student: str,
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
    *,
    language: str,
) -> tuple[bool, dict | str]:
    """
    Use the LLM to judge whether the student's correction is essentially correct,
    allowing for punctuation differences and equivalent phrasing.
    Returns (correct, feedback) where feedback is
    {"wrong": ..., "correct": ..., "explanation": ...} or "" on failure.
    """
    lang_cfg = get_language_config(language)
    lang_name, lang_code = lang_cfg.name, lang_cfg.code
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content
        else ""
    )
    prompt = _prompts.error_correction_eval.render(
        target_language=lang_name,
        feedback_language=_feedback_language(cefr_level, lang_name),
        erroneous=erroneous,
        reference=reference,
        student=student,
        rule_block=rule_block,
        span_tagging=_stb(lang_name, lang_code),
    )

    logger.info(
        "evaluate_error_correction",
        extra={"student": student, "reference": reference},
    )
    try:
        logger.debug(f"evaluate_error_correction prompt: {prompt}")
        response = await llm_messages_create(
            model=settings.DRILL_MODEL,
            max_tokens=256,
            system=_prompts.error_correction_eval.render_system(
                target_language=lang_name,
                span_tagging=_stb(lang_name, lang_code),
            ),
            messages=[{"role": "user", "content": prompt}],
            entity_id=lesson_id,
            call_type=CallType.SCORER_SINGLE,
            student_id=student_id,
        )
        raw = response.content[0].text
        logger.debug(f"evaluate_error_correction response: {raw}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(
                "evaluate_error_correction failed to parse response", extra={"raw": raw}
            )
            correct = student.strip().lower() == reference.strip().lower()
            return correct, ""
        is_correct = bool(data.get("correct", False))
        logger.info("error correction result", extra={"is_correct": is_correct})
        feedback: dict | str = {
            "wrong": student,
            "correct": reference,
            "explanation": data.get("explanation", ""),
        }
        return is_correct, feedback
    except Exception:
        logger.error("evaluate_error_correction error", exc_info=True)
        correct = student.strip().lower() == reference.strip().lower()
        return correct, ""


async def score_multi_item_drill(
    exercise_type: str,
    grammar_point_code: str,
    items: list[DrillItem],
    student_answers: list[str],
    rag_content: str = "",
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
    *,
    language: str,
) -> list[dict]:
    """Score all items in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per item.
    Items may carry per-item grammar_point_code overrides; the drill-level code is the fallback.
    """
    n = min(len(items), len(student_answers))
    logger.info(
        "score_multi_item_drill",
        extra={
            "exercise_type": exercise_type,
            "grammar_point_code": grammar_point_code,
            "n_items": n,
            "has_rag": bool(rag_content),
        },
    )

    lang_cfg = get_language_config(language)
    lang_name = lang_cfg.name
    await grammar_cache.ensure_loaded(lang_cfg.code)
    gp_lookup = {g.code: g.label for g in grammar_cache.grammar_points(lang_cfg.code)}

    rule_block = f"\n\nGrammar rule reference:\n{rag_content}" if rag_content else ""

    if exercise_type == ExerciseType.FILL_BLANK:
        task_desc = _prompts.fill_blank_task_fragment.render(target_language=lang_name)
        lines = []
        for i in range(n):
            item_gp = items[i].grammar_point_code or grammar_point_code
            item_label = gp_lookup.get(item_gp, item_gp)
            lines.append(
                f'{i + 1}. Sentence: "{items[i].prompt}" | Correct: "{items[i].correct_answer}" | Student: "{student_answers[i]}" | GP: {item_gp} ({item_label})'
            )
    else:  # error_correction
        task_desc = _prompts.error_correction_task_fragment.render(
            target_language=lang_name
        )
        lines = []
        for i in range(n):
            item_gp = items[i].grammar_point_code or grammar_point_code
            item_label = gp_lookup.get(item_gp, item_gp)
            lines.append(
                f'{i + 1}. Erroneous: "{items[i].prompt}" | Reference: "{items[i].correct_answer}" | Student: "{student_answers[i]}" | GP: {item_gp} ({item_label})'
            )

    prompt = _prompts.drill_scoring.render(
        target_language=lang_name,
        task_desc=task_desc,
        rule_block=rule_block,
        items_block="\n".join(lines),
        n=n,
    )

    return await _score_multi(
        prompt,
        n,
        label="score_multi_item_drill",
        cefr_level=cefr_level,
        model=settings.DRILL_MODEL,
        student_id=student_id,
        lesson_id=lesson_id,
        language=language,
    )


async def generate_writing_feedback(
    prompt: str,
    student_text: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
    *,
    language: str,
) -> dict:
    """Generate feedback for a free-writing activity.

    Returns {objective_correct, objective_note, grammar_errors, tips} or
    {objective_correct: True, ...} on disabled / failure.
    """
    lang_cfg = get_language_config(language)
    word_count = len(student_text.split())
    logger.info(
        "generate_writing_feedback",
        extra={"cefr_level": cefr_level, "word_count": word_count},
    )

    llm_prompt = _prompts.writing_scoring.render(
        target_language=lang_cfg.name,
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
        language=language,
    )


async def generate_speaking_feedback(
    prompt: str,
    student_text: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
    *,
    language: str,
) -> dict:
    """Generate feedback for a free-form speaking activity.

    Returns {objective_correct, objective_note, grammar_errors, tips}.
    """
    word_count = len(student_text.split())
    logger.info(
        "generate_speaking_feedback",
        extra={"cefr_level": cefr_level, "word_count": word_count},
    )

    llm_prompt = _prompts.speaking_scoring.render(
        cefr_level=cefr_level,
        prompt=prompt,
        student_text=student_text,
    )

    return await _score_single(
        llm_prompt,
        label="generate_speaking_feedback",
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
        language=language,
    )


async def score_reading_answers(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
    *,
    language: str,
) -> list[dict]:
    """Score student answers to reading comprehension questions in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per question.
    """
    lang_cfg = get_language_config(language)
    lang_name = lang_cfg.name
    n = min(len(questions), len(student_answers))
    logger.info("score_reading_answers", extra={"n": n})

    lines = [
        f'{i + 1}. Question: "{questions[i]}" | Expected: "{correct_answers[i] if i < len(correct_answers) else ""}" | Student: "{student_answers[i]}"'
        for i in range(n)
    ]

    answer_language = f"{lang_name} or English" if cefr_level == "A0" else lang_name
    prompt = _prompts.reading_scoring.render(
        target_language=lang_name,
        answer_language=answer_language,
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
        language=language,
    )
