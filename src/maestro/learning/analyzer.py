"""
Learning signal extraction from student Italian messages.

Uses Claude Sonnet (via Anthropic API) to produce structured JSON
identifying grammar structures used/errored, communicative functions
performed, and themes present in a single student message.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from maestro.models import Message

from maestro.models import CommunicativeFunction, GrammarPoint, LearningEvent
from maestro.config import settings
from maestro.llm import get_client
from maestro.profile import get_profile
from maestro.prompts import analyzer as _prompts
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)

# Module-level caches populated from MongoDB on first use
_grammar_points_cache: list[GrammarPoint] = []
_comm_functions_cache: list[CommunicativeFunction] = []
_student_level: str = "B2"  # default to full list; refreshed on first load


async def _ensure_codes() -> None:
    global _grammar_points_cache, _comm_functions_cache, _student_level
    if _grammar_points_cache:
        return
    _grammar_points_cache = await GrammarPoint.find_all().to_list()
    _comm_functions_cache = await CommunicativeFunction.find_all().to_list()
    profile = await get_profile()
    if profile:
        _student_level = profile.cefr_estimate
    logger.info(
        f"[analyzer] cache loaded: {len(_grammar_points_cache)} grammar points, "
        f"{len(_comm_functions_cache)} comm functions, student level={_student_level}"
    )


def _client():
    return get_client()


def _build_prompt(text: str, drill_context: str = "") -> str:
    # Only include items at or below the student's current level — keeps the
    # taxonomy list manageable and improves matching precision.
    relevant_levels = {_student_level}

    gp_relevant = [g for g in _grammar_points_cache if g.cefr_level in relevant_levels]
    cf_relevant = [f for f in _comm_functions_cache if f.cefr_level in relevant_levels]
    logger.debug(
        f"[analyzer] building prompt: level={_student_level}, "
        f"{len(gp_relevant)} GPs, {len(cf_relevant)} CFs in taxonomy, "
        f"drill_context={'yes' if drill_context else 'no'}"
    )

    grammar_lines = "\n".join(f"{g.code}: {g.description}" for g in gp_relevant)
    function_lines = "\n".join(f"{f.code}: {f.description or f.label}" for f in cf_relevant)

    context_block = ""
    feedback_field = ""
    if drill_context:
        context_block = _prompts.context_block_fragment.render(drill_context=drill_context)
        feedback_field = _prompts.feedback_field_fragment.render().strip()

    return _prompts.analyze_message.render(
        context_block=context_block,
        text=text,
        grammar_lines=grammar_lines,
        function_lines=function_lines,
        feedback_field=feedback_field,
    )


async def analyze_message(
    text: str,
    message: Optional["Message"] = None,
    drill_context: str = "",
) -> Optional["LearningEvent"]:
    """
    Analyze a student message and return a LearningEvent (not yet saved).
    Returns None if analysis fails.
    drill_context is optional extra info (drill prompt + grammar point) for richer feedback.
    """

    word_count = len(text.split())
    # Skip very short messages (greetings, single words)
    if word_count < 3:
        logger.debug(f"[analyzer] skipping short message ({word_count} words): {text!r}")
        return None

    logger.info(f"[analyzer] analyzing message ({word_count} words): {text[:80]!r}{'...' if len(text) > 80 else ''}")

    try:
        await _ensure_codes()
        prompt = _build_prompt(text, drill_context)
        logger.debug(f"[analyzer] analyze_message prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[analyzer] LLM response in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] failed to parse response: {raw}")
            return None

        valid_grammar = {g.code for g in _grammar_points_cache}
        valid_functions = {f.code for f in _comm_functions_cache}
        valid_themes = {
            "self_identity",
            "family",
            "daily_routine",
            "food_home",
            "health_body",
            "shopping",
            "work_study",
            "travel",
            "culture_society",
            "nature_environment",
        }

        # Guard against model returning objects instead of plain code strings
        def _str_codes(items) -> list[str]:
            return [c for c in items if isinstance(c, str)]

        grammar_correct = [c for c in _str_codes(data.get("grammar_correct", [])) if c in valid_grammar]
        grammar_errors  = [c for c in _str_codes(data.get("grammar_errors", [])) if c in valid_grammar]
        functions       = [c for c in _str_codes(data.get("functions_performed", [])) if c in valid_functions]
        themes          = [t for t in _str_codes(data.get("themes", [])) if t in valid_themes]

        unknown_gp = [c for c in _str_codes(data.get("grammar_correct", []) + data.get("grammar_errors", [])) if c not in valid_grammar]
        unknown_cf = [c for c in _str_codes(data.get("functions_performed", [])) if c not in valid_functions]
        if unknown_gp:
            logger.warning(f"[analyzer] LLM returned unknown grammar codes (ignored): {unknown_gp}")
        if unknown_cf:
            logger.warning(f"[analyzer] LLM returned unknown CF codes (ignored): {unknown_cf}")

        logger.info(
            f"[analyzer] result: correct={grammar_correct}, errors={grammar_errors}, "
            f"functions={functions}, themes={themes}"
        )

        return LearningEvent(
            message=message,
            grammar_correct=grammar_correct,
            grammar_errors=grammar_errors,
            functions_performed=functions,
            themes=themes,
            feedback=json.dumps({"errors": data.get("errors", [])}) if drill_context else "",
        )
    except Exception as e:
        logger.error(f"[analyzer] error analyzing message: {e}", exc_info=True)
        return None


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

    logger.info(f"[analyzer] feedback_fill_blank: gp={grammar_point_code}, student={student_answer!r}, correct={correct_answer!r}")
    try:
        logger.debug(f"[analyzer] feedback_fill_blank prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        explanation = response.content[0].text.strip()
        logger.debug(f"[analyzer] feedback_fill_blank in {elapsed:.2f}s: {explanation!r}")
        return {"wrong": student_answer, "correct": correct_answer, "explanation": explanation}
    except Exception as e:
        logger.error(f"[analyzer] feedback_fill_blank error: {e}", exc_info=True)
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

    logger.info(f"[analyzer] evaluate_error_correction: student={student!r}, reference={reference!r}")
    try:
        logger.debug(f"[analyzer] evaluate_error_correction prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[analyzer] evaluate_error_correction in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] evaluate_error_correction failed to parse: {raw}")
            correct = student.strip().lower() == reference.strip().lower()
            return correct, ""
        is_correct = bool(data.get("correct", False))
        logger.info(f"[analyzer] evaluate_error_correction result: correct={is_correct}")
        feedback: dict | str = {
            "wrong": student,
            "correct": reference,
            "explanation": data.get("explanation", ""),
        }
        return is_correct, feedback
    except Exception as e:
        logger.error(f"[analyzer] evaluate_error_correction error: {e}", exc_info=True)
        correct = student.strip().lower() == reference.strip().lower()
        return correct, ""


_FALLBACK_ITEM = {"objective_correct": False, "objective_note": "", "grammar_errors": [], "tips": []}


async def score_multi_item_drill(
    exercise_type: str,
    grammar_point_code: str,
    items: list,
    student_answers: list[str],
    rag_content: str = "",
) -> list[dict]:
    """Score all items in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per item.
    - objective_correct: whether the student demonstrated the drill's specific grammar point
    - objective_note: Italian explanation if objective wrong, else ""
    - grammar_errors: list of grammar_point codes for other errors found (not the objective)
    - tips: list of freetext strings for spelling/accent issues
    """
    n = min(len(items), len(student_answers))
    logger.info(
        f"[analyzer] score_multi_item_drill: type={exercise_type}, gp={grammar_point_code}, "
        f"n_items={n}, rag={'yes' if rag_content else 'no'}"
    )

    await _ensure_codes()
    gp_label = next((g.label for g in _grammar_points_cache if g.code == grammar_point_code), grammar_point_code)
    grammar_code_list = "\n".join(f"  {g.code}: {g.label}" for g in _grammar_points_cache)
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
        logger.debug(f"[analyzer] score_multi_item_drill prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_multi_item_drill LLM in {elapsed:.2f}s: {raw}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[analyzer] score_multi_item_drill: {n_correct}/{n} correct")
            return result
        logger.error(f"[analyzer] score_multi_item_drill unexpected result shape: {raw}")
    except Exception as e:
        logger.error(f"[analyzer] score_multi_item_drill error: {e}", exc_info=True)

    logger.warning(f"[analyzer] score_multi_item_drill falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]


async def generate_writing_feedback(
    prompt: str,
    student_text: str,
    cefr_level: str,
) -> dict:
    """Generate feedback for a free-writing activity.

    Returns {objective_correct, objective_note, grammar_errors, tips} or
    {objective_correct: True, ...} on disabled / failure.
    - objective_correct: False only if student ignored the prompt entirely
    - grammar_errors: list of freetext strings (e.g. "ha mangiato → aveva mangiato")
    - tips: spelling/accent issues only (e.g. "città not citta")
    """
    word_count = len(student_text.split())
    logger.info(
        f"[analyzer] generate_writing_feedback: level={cefr_level}, "
        f"{word_count} words, prompt={prompt[:60]!r}..."
    )

    llm_prompt = _prompts.generate_writing_feedback.render(
        cefr_level=cefr_level,
        prompt=prompt,
        student_text=student_text,
    )

    try:
        logger.debug(f"[analyzer] generate_writing_feedback prompt: {llm_prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] generate_writing_feedback LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[analyzer] generate_writing_feedback unexpected shape: {raw}")
            return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}
        logger.info(
            f"[analyzer] generate_writing_feedback: objective_correct={data.get('objective_correct')}, "
            f"{len(data.get('grammar_errors', []))} errors, {len(data.get('tips', []))} tips"
        )
        return data
    except Exception as e:
        logger.error(f"[analyzer] generate_writing_feedback error: {e}", exc_info=True)
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
    - objective_correct: did the student make a genuine attempt? (grammar errors don't affect this)
    - grammar_errors: freetext strings for grammar issues found
    - tips: spelling/accent strings
    """
    rule_block = (
        f"\n\nRelevant grammar rule from the reference book:\n{rag_content}"
        if rag_content else ""
    )
    logger.info(
        f"[analyzer] score_free_form_drill: gp={grammar_point_code}, level={cefr_level}, "
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
        logger.debug(f"[analyzer] score_free_form_drill prompt: {llm_prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_free_form_drill LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[analyzer] score_free_form_drill unexpected shape: {raw}")
            return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}
        logger.info(
            f"[analyzer] score_free_form_drill: objective_correct={data.get('objective_correct')}, "
            f"{len(data.get('grammar_errors', []))} errors"
        )
        return data
    except Exception as e:
        logger.error(f"[analyzer] score_free_form_drill error: {e}", exc_info=True)
        return {"objective_correct": True, "objective_note": "", "grammar_errors": [], "tips": []}


async def score_reading_answers(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
) -> list[dict]:
    """Score student answers to reading comprehension questions in a single LLM call.

    Returns a list of {objective_correct, objective_note, grammar_errors, tips} per question.
    - objective_correct: whether the student adequately answered the question (accept paraphrasing)
    - objective_note: Italian note if wrong, else ""
    - grammar_errors: list of short grammar error descriptions
    - tips: list of freetext tips
    """
    n = min(len(questions), len(student_answers))
    logger.info(f"[analyzer] score_reading_answers: {n} questions")

    lines = [
        f'{i + 1}. Question: "{questions[i]}" | Expected: "{correct_answers[i] if i < len(correct_answers) else ""}" | Student: "{student_answers[i]}"'
        for i in range(n)
    ]

    prompt = _prompts.score_reading_answers.render(
        items_block="\n".join(lines),
        n=n,
    )

    try:
        logger.debug(f"[analyzer] score_reading_answers prompt: {prompt}")
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_reading_answers LLM in {elapsed:.2f}s: {raw}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[analyzer] score_reading_answers: {n_correct}/{n} correct")
            return result
        logger.error(f"[analyzer] score_reading_answers unexpected result shape: {raw}")
    except Exception as e:
        logger.error(f"[analyzer] score_reading_answers error: {e}", exc_info=True)

    logger.warning(f"[analyzer] score_reading_answers falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]
