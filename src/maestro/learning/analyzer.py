"""
Learning signal extraction from student Italian messages.

Uses Claude Sonnet (via Anthropic API) to produce structured JSON
identifying grammar structures used/errored, communicative functions
performed, and themes present in a single student message.

Set ANALYSIS_ENABLED=False in settings to disable API calls.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    from maestro.models import Message

from maestro.models import LearningEvent
from maestro.settings import Settings
from maestro.utils import DATA_DIR, parse_llm_json

logger = logging.getLogger(__name__)

# Module-level caches loaded once at startup
_grammar_codes: list[dict] = []
_function_codes: list[dict] = []


def _load_codes() -> None:
    global _grammar_codes, _function_codes
    if _grammar_codes:
        return
    with open(DATA_DIR / "grammar_points.json") as f:
        _grammar_codes = json.load(f)
    with open(DATA_DIR / "comm_functions.json") as f:
        _function_codes = json.load(f)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=Settings().ANTHROPIC_API_KEY)


def _build_prompt(text: str, drill_context: str = "") -> str:
    _load_codes()
    grammar_lines = "\n".join(
        f"{g['code']}: {g['description']}" for g in _grammar_codes
    )
    function_lines = "\n".join(f"{f['code']}: {f['label']}" for f in _function_codes)

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
    Returns None if analysis is disabled or fails.
    drill_context is optional extra info (drill prompt + grammar point) for richer feedback.
    """
    settings = Settings()
    if not settings.ANALYSIS_ENABLED:
        return None

    # Skip very short messages (greetings, single words)
    if len(text.split()) < 3:
        return None

    try:
        prompt = _build_prompt(text, drill_context)
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] Failed to parse response: {raw[:200]}")
            return None

        _load_codes()
        valid_grammar = {g["code"] for g in _grammar_codes}
        valid_functions = {f["code"] for f in _function_codes}
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

        return LearningEvent(
            message=message,
            grammar_correct=[
                c for c in data.get("grammar_correct", []) if c in valid_grammar
            ],
            grammar_errors=[
                c for c in data.get("grammar_errors", []) if c in valid_grammar
            ],
            functions_performed=[
                c for c in data.get("functions_performed", []) if c in valid_functions
            ],
            themes=[t for t in data.get("themes", []) if t in valid_themes],
            feedback=json.dumps({"errors": data.get("errors", [])}) if drill_context else "",
        )
    except Exception as e:
        logger.error(f"[analyzer] Error analyzing message: {e}")
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
    or empty string if ANALYSIS_ENABLED=False or on any error.
    """
    settings = Settings()
    if not settings.ANALYSIS_ENABLED:
        return ""

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

    try:
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        explanation = response.content[0].text.strip()
        return {"wrong": student_answer, "correct": correct_answer, "explanation": explanation}
    except Exception as e:
        logger.error(f"[analyzer] feedback_fill_blank error: {e}")
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
    Raises RuntimeError if analysis is unavailable.
    """
    settings = Settings()
    if not settings.ANALYSIS_ENABLED:
        raise RuntimeError(
            "Error-correction evaluation unavailable — check ANALYSIS_ENABLED"
        )

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

    try:
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        data = parse_llm_json(raw)
        if data is None:
            logger.error(f"[analyzer] evaluate_error_correction failed to parse: {raw[:200]}")
            correct = student.strip().lower() == reference.strip().lower()
            return correct, ""
        is_correct = bool(data.get("correct", False))
        feedback: dict | str = {
            "wrong": student,
            "correct": reference,
            "explanation": data.get("explanation", ""),
        }
        return is_correct, feedback
    except Exception as e:
        logger.error(f"[analyzer] evaluate_error_correction error: {e}")
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
    settings = Settings()
    n = min(len(items), len(student_answers))

    _load_codes()
    gp_label = next((g["label"] for g in _grammar_codes if g["code"] == grammar_point_code), grammar_point_code)
    grammar_code_list = "\n".join(f"  {g['code']}: {g['label']}" for g in _grammar_codes)
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
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            return result
        logger.error(f"[analyzer] score_multi_item_drill unexpected result: {raw[:200]}")
    except Exception as e:
        logger.error(f"[analyzer] score_multi_item_drill error: {e}")

    return [dict(_FALLBACK_ITEM) for _ in range(n)]


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
    settings = Settings()
    n = min(len(questions), len(student_answers))

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
        response = _client().messages.create(
            model=settings.LESSON_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        result = parse_llm_json(raw)
        if isinstance(result, list) and len(result) == n:
            return result
        logger.error(f"[analyzer] score_reading_answers unexpected result: {raw[:200]}")
    except Exception as e:
        logger.error(f"[analyzer] score_reading_answers error: {e}")

    return [dict(_FALLBACK_ITEM) for _ in range(n)]
