"""
Anthropic client factories.

All LLM calls should obtain their client from here rather than constructing
one directly. This provides a single point of configuration and a single
target for test mocking.
"""

import asyncio
import logging
from functools import lru_cache

import anthropic
from maestro.config import settings
from maestro.utils import create_background_task

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
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        extra: dict = {
            "call_type": call_type,
            "model": response.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if student_id is not None:
            extra["student_id"] = str(student_id)
        if lesson_id is not None:
            extra["lesson_id"] = str(lesson_id)
    except Exception:
        logger.debug(
            "log_llm_usage failed", extra={"call_type": call_type}, exc_info=True
        )
        return

    try:
        logger.info("llm_usage", extra=extra)
    except Exception:
        pass  # never let a logging handler failure block token accumulation

    if lesson_id is not None:
        try:
            asyncio.get_running_loop()  # raises RuntimeError if no loop
            create_background_task(
                _accumulate_lesson_tokens(lesson_id, input_tokens, output_tokens),
                name=f"accumulate-tokens-{lesson_id}",
            )
        except RuntimeError:
            pass  # no running event loop (sync batch scripts)


async def _accumulate_lesson_tokens(
    lesson_id, input_tokens: int, output_tokens: int
) -> None:
    try:
        from maestro.models import Lesson  # local import avoids circular dependency

        await Lesson.find_one(Lesson.id == lesson_id).update(
            {
                "$inc": {
                    "token_usage.input_tokens": input_tokens,
                    "token_usage.output_tokens": output_tokens,
                }
            }
        )
    except Exception:
        logger.debug(
            "accumulate_lesson_tokens failed",
            extra={"lesson_id": str(lesson_id)},
            exc_info=True,
        )


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    """Return an asynchronous Anthropic client."""
    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )
