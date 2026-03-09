"""Shared LLM-as-judge helper for eval tests."""

import logging
import anthropic

from maestro.config import settings
from maestro.prompts import judge as _prompts
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)


def judge(prompt: str) -> tuple[bool, str]:
    """Single synchronous LLM judge call. Returns (acceptable: bool, reason: str)."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    logger.debug(f"[judge] prompt: {prompt}")
    response = client.messages.create(
        model=settings.EVAL_MODEL,
        max_tokens=256,
        system=_prompts.system.render_system(),
        messages=[
            {
                "role": "user",
                "content": prompt + "\n\n" + _prompts.reply_suffix.render(),
            }
        ],
    )
    raw = response.content[0].text.strip()
    logger.info(f"[judge] raw response: {raw!r}")
    data = parse_llm_json(raw)
    if isinstance(data, dict) and "acceptable" in data:
        result = bool(data["acceptable"]), str(data.get("reason", ""))
        logger.info(f"[judge] result: acceptable={result[0]}, reason={result[1]!r}")
        return result
    logger.warning(f"[judge] parse error — raw was: {raw!r}")
    return False, "parse error"


def judge_against_reference(
    generated: str,
    reference: str,
    context: str = "",
) -> tuple[bool, str]:
    """Judge whether generated output matches a reference answer.

    Accept paraphrasing — exact wording is not required.
    Returns (acceptable: bool, reason: str).
    """
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    ctx = f"Context: {context}\n\n" if context else ""
    logger.debug(
        f"[judge_ref] context={context!r} generated={generated!r} reference={reference!r}"
    )
    response = client.messages.create(
        model=settings.EVAL_MODEL,
        max_tokens=256,
        system=_prompts.system.render_system(),
        messages=[
            {
                "role": "user",
                "content": _prompts.reference_check.render(
                    context=ctx,
                    reference=reference,
                    generated=generated,
                ),
            }
        ],
    )
    raw = response.content[0].text.strip()
    logger.info(f"[judge_ref] raw response: {raw!r}")
    data = parse_llm_json(raw)
    if isinstance(data, dict) and "acceptable" in data:
        result = bool(data["acceptable"]), str(data.get("reason", ""))
        logger.info(f"[judge_ref] result: acceptable={result[0]}, reason={result[1]!r}")
        return result
    logger.warning(f"[judge_ref] parse error — raw was: {raw!r}")
    return False, "parse error"
