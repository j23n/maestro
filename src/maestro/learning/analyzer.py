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

from maestro.models import LearningEvent
from maestro.config import settings
from maestro.llm import get_async_client
from maestro import taxonomy
from maestro.prompts import analyzer as _prompts
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)


async def _ensure_loaded() -> None:
    """Ensure taxonomy cache is populated."""
    await taxonomy.ensure_loaded()


def _client():
    return get_async_client()


def _build_prompt(text: str, student_level: str, drill_context: str = "") -> str:
    # Only include items at or below the student's current level — keeps the
    # taxonomy list manageable and improves matching precision.
    relevant_levels = {student_level}

    gp_relevant = [g for g in taxonomy.grammar_points() if g.cefr_level in relevant_levels]
    cf_relevant = [f for f in taxonomy.comm_functions() if f.cefr_level in relevant_levels]
    logger.debug(
        f"[analyzer] building prompt: level={student_level}, "
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
    student_id=None,
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
        await _ensure_loaded()
        from maestro.profile import get_cefr_level
        level = await get_cefr_level(student_id) if student_id else "B2"
        prompt = _build_prompt(text, level, drill_context)
        logger.debug(f"[analyzer] analyze_message prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client().messages.create(
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

        valid_grammar = {g.code for g in taxonomy.grammar_points()}
        valid_functions = {f.code for f in taxonomy.comm_functions()}
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


