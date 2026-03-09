"""
Anthropic client factories.

All LLM calls should obtain their client from here rather than constructing
one directly. This provides a single point of configuration and a single
target for test mocking.
"""

import logging
from functools import lru_cache

import anthropic
from maestro.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """Return a synchronous Anthropic client."""
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )


def log_llm_usage(response, call_type, *, student_id=None, lesson_id=None):
    try:
        usage = response.usage
        logger.info(
            "[llm] call_type=%s model=%s in=%d out=%d student=%s lesson=%s",
            call_type,
            response.model,
            usage.input_tokens,
            usage.output_tokens,
            str(student_id) if student_id is not None else None,
            str(lesson_id) if lesson_id is not None else None,
        )
    except Exception:
        logger.debug(
            "[llm] log_llm_usage failed for call_type=%s", call_type, exc_info=True
        )


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    """Return an asynchronous Anthropic client."""
    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )
