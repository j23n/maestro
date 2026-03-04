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

import anthropic

if TYPE_CHECKING:
    from maestro.models import Message

from maestro.models import CommunicativeFunction, GrammarPoint, LearningEvent, LearningProfile
from maestro.config import settings
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
    profile = await LearningProfile.find_one()
    if profile:
        _student_level = profile.cefr_estimate
    logger.info(
        f"[analyzer] cache loaded: {len(_grammar_points_cache)} grammar points, "
        f"{len(_comm_functions_cache)} comm functions, student level={_student_level}"
    )


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


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
        context_block = f"Drill context (what the student was asked to do):\n{drill_context}\n\n"
        feedback_field = (
            ',"errors":[{"wrong":"<exact wrong phrase from student text>","correct":"<corrected version>",'
            '"explanation":"<one sentence in Italian explaining the rule>"}]'
        )

    return (
        "Analyze this Italian learner's message. Identify which grammar structures "
        "appear (correctly used vs errors), communicative functions performed, and themes.\n\n"
        f"{context_block}"
        f'Student message: "{text}"\n\n'
        "Grammar point codes + descriptions:\n"
        f"{grammar_lines}\n\n"
        "Communicative function codes:\n"
        f"{function_lines}\n\n"
        "Themes: self_identity, family, daily_routine, food_home, health_body, "
        "shopping, work_study, travel, culture_society, nature_environment\n\n"
        "Return ONLY valid JSON (no markdown, no explanation):\n"
        '{"grammar_correct":[...],"grammar_errors":[...],"functions_performed":[...],"themes":[...]'
        f"{feedback_field}}}"
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
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[analyzer] LLM response in {elapsed:.2f}s: {raw[:200]}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] failed to parse response: {raw[:300]}")
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

        grammar_correct = [c for c in data.get("grammar_correct", []) if c in valid_grammar]
        grammar_errors  = [c for c in data.get("grammar_errors", []) if c in valid_grammar]
        functions       = [c for c in data.get("functions_performed", []) if c in valid_functions]
        themes          = [t for t in data.get("themes", []) if t in valid_themes]

        unknown_gp = [c for c in data.get("grammar_correct", []) + data.get("grammar_errors", []) if c not in valid_grammar]
        unknown_cf = [c for c in data.get("functions_performed", []) if c not in valid_functions]
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
    prompt = (
        f"An Italian learner made an error in a fill-in-the-blank exercise.\n\n"
        f"Grammar point: {grammar_point_code}\n"
        f"Exercise: {drill_prompt}\n"
        f"Correct answer: {correct_answer}\n"
        f"Student's answer: {student_answer}"
        f"{rule_block}\n\n"
        "Write ONE sentence in Italian explaining why the student's answer is wrong and "
        "what the correct rule is. Be concise and direct. "
        "Return ONLY the explanation sentence, no JSON, no labels."
    )

    logger.info(f"[analyzer] feedback_fill_blank: gp={grammar_point_code}, student={student_answer!r}, correct={correct_answer!r}")
    try:
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
    prompt = (
        "You are evaluating an Italian grammar exercise. "
        "The student was asked to find and correct ONE grammatical error in a sentence.\n\n"
        f'Original sentence (contains one error): "{erroneous}"\n'
        f'Reference correction: "{reference}"\n'
        f'Student\'s answer: "{student}"'
        f"{rule_block}\n\n"
        "Decide whether the student's answer is essentially correct. "
        "Accept minor differences in punctuation or spacing. "
        "Focus on whether the grammatical error was correctly identified and fixed.\n\n"
        "Return ONLY valid JSON (no markdown, no explanation):\n"
        '{"correct":true,"explanation":"ONE sentence in Italian explaining what the error was and the rule"}'
    )

    logger.info(f"[analyzer] evaluate_error_correction: student={student!r}, reference={reference!r}")
    try:
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[analyzer] evaluate_error_correction in {elapsed:.2f}s: {raw[:200]}")
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] evaluate_error_correction failed to parse: {raw[:300]}")
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
        task_desc = (
            f"The student was asked to fill a blank in an Italian sentence. "
            f"The student may have typed just the missing word OR the full sentence — both are valid. "
            f"If the student typed the full sentence, extract the word(s) filling the blank for evaluation."
        )
        lines = [
            f'{i + 1}. Sentence: "{items[i].prompt}" | Correct: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]
    else:  # error_correction
        task_desc = (
            f"The student was asked to correct a grammatical error in an Italian sentence. "
            f"Accept minor punctuation differences and equivalent phrasings."
        )
        lines = [
            f'{i + 1}. Erroneous: "{items[i].prompt}" | Reference: "{items[i].correct_answer}" | Student: "{student_answers[i]}"'
            for i in range(n)
        ]

    prompt = (
        f"You are grading an Italian grammar exercise. {task_desc}\n\n"
        f"LEARNING OBJECTIVE: {gp_label} ({grammar_point_code})\n"
        f"{rule_block}\n\n"
        f"For each item evaluate TWO things independently:\n"
        f"1. OBJECTIVE — Did the student correctly demonstrate '{gp_label}'? "
        f"Ignore accents, spelling typos, and unrelated grammar when judging this.\n"
        f"2. OTHER ISSUES — Identify any additional problems:\n"
        f"   a) Other grammar errors: tag with codes from this list:\n{grammar_code_list}\n"
        f"   b) Spelling/accent issues: short freetext note (e.g. \"città not citta\")\n\n"
        f"Items:\n" + "\n".join(lines) + "\n\n"
        f"Return ONLY a JSON array of exactly {n} objects, one per item, in order.\n"
        f"Schema:\n"
        f'[{{"objective_correct": true, "objective_note": "", "grammar_errors": [], "tips": []}}, ...]\n'
        f"Rules:\n"
        f"- objective_note: empty string when correct; one sentence in Italian when wrong\n"
        f"- grammar_errors: codes for OTHER grammar errors (never include {grammar_point_code} here)\n"
        f"- tips: short strings for spelling/accent issues only\n"
        f"No markdown, no other text."
    )

    try:
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_multi_item_drill LLM in {elapsed:.2f}s: {raw[:200]}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[analyzer] score_multi_item_drill: {n_correct}/{n} correct")
            return result
        logger.error(f"[analyzer] score_multi_item_drill unexpected result shape: {raw[:300]}")
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

    llm_prompt = (
        f"You are an Italian language teacher reviewing a {cefr_level} student's writing.\n\n"
        f"Writing prompt: {prompt}\n\n"
        f"Student's text: {student_text}\n\n"
        "Evaluate TWO things independently:\n"
        "1. TASK COMPLETION — Did the student make a genuine attempt to address the prompt? "
        "Set objective_correct=false ONLY if the text is blank, completely off-topic, or "
        "just a random word/phrase with no relation to the task.\n"
        "2. LANGUAGE QUALITY — Separately list grammar errors and spelling/accent tips. "
        "These never affect objective_correct.\n\n"
        "grammar_errors: list of freetext strings describing grammar issues "
        "(e.g. \"ha mangiato → aveva mangiato (trapassato prossimo)\"). Up to 4.\n"
        "tips: spelling/accent issues only (e.g. \"città not citta\"). Up to 3.\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"objective_correct":true,"objective_note":"","grammar_errors":[],"tips":[]}'
    )

    try:
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] generate_writing_feedback LLM in {elapsed:.2f}s: {raw[:200]}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[analyzer] generate_writing_feedback unexpected shape: {raw[:300]}")
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

    llm_prompt = (
        f"You are grading a free-form Italian drill for a {cefr_level} learner.\n\n"
        f"Grammar point being practised: {grammar_point_code}\n"
        f"Drill prompt: {prompt}\n"
        f"Student's answer: {student_text}"
        f"{rule_block}\n\n"
        "Evaluate TWO things independently:\n"
        "1. TASK COMPLETION — Did the student make a genuine attempt at the task? "
        "Set objective_correct=false ONLY if the answer is blank, completely off-topic, "
        "or so short/nonsensical it shows no engagement. "
        "Grammar errors alone must NOT make this false.\n"
        "2. LANGUAGE QUALITY — Separately list grammar errors and spelling/accent tips. "
        "These never affect objective_correct.\n\n"
        "grammar_errors: list of freetext strings (e.g. \"ho andato → sono andato (essere verbs)\"). Up to 4.\n"
        "tips: spelling/accent issues only (e.g. \"perché not perche\"). Up to 3.\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"objective_correct":true,"objective_note":"","grammar_errors":[],"tips":[]}'
    )

    try:
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": llm_prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_free_form_drill LLM in {elapsed:.2f}s: {raw[:200]}")
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[analyzer] score_free_form_drill unexpected shape: {raw[:300]}")
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

    prompt = (
        "You are grading reading comprehension answers for an Italian language learner.\n\n"
        "For each item, judge whether the student's answer correctly addresses the question. "
        "Accept paraphrasing, approximate wording, and answers in a mix of Italian and English. "
        "Focus on whether the student understood the text, not perfect grammar.\n\n"
        f"Items:\n" + "\n".join(lines) + "\n\n"
        f"Return ONLY a JSON array of exactly {n} objects, one per item, in order.\n"
        f"Schema:\n"
        f'[{{"objective_correct": true, "objective_note": "", "grammar_errors": [], "tips": []}}, ...]\n'
        "Rules:\n"
        "- objective_note: empty when correct; one Italian sentence explaining what was wrong or missing when incorrect\n"
        "- grammar_errors: list of short strings describing grammar issues in the student's Italian (if any)\n"
        "- tips: short spelling/accent tip strings only\n"
        "No markdown, no other text."
    )

    try:
        t0 = time.monotonic()
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text.strip()
        logger.debug(f"[analyzer] score_reading_answers LLM in {elapsed:.2f}s: {raw[:200]}")
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            n_correct = sum(1 for r in result if r.get("objective_correct"))
            logger.info(f"[analyzer] score_reading_answers: {n_correct}/{n} correct")
            return result
        logger.error(f"[analyzer] score_reading_answers unexpected result shape: {raw[:300]}")
    except Exception as e:
        logger.error(f"[analyzer] score_reading_answers error: {e}", exc_info=True)

    logger.warning(f"[analyzer] score_reading_answers falling back to all-incorrect for {n} items")
    return [dict(_FALLBACK_ITEM) for _ in range(n)]
