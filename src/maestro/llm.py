"""
Anthropic client factories and LLM cost tracking.

All LLM calls should obtain their client from here rather than constructing
one directly. This provides a single point of configuration and a single
target for test mocking.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import anthropic
from maestro.config import settings
from maestro.utils import create_background_task

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from maestro.models import CallType

logger = logging.getLogger(__name__)

# USD per 1M tokens. Rates verified 2026-03-09.
# Source: https://www.anthropic.com/pricing
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}
_FALLBACK_PRICING = (3.00, 15.00)  # Sonnet rates for unknown models


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in USD for a single API call."""
    if model not in _MODEL_PRICING:
        logger.warning(
            "llm_cost: unknown model %s, falling back to Sonnet pricing", model
        )
    input_rate, output_rate = _MODEL_PRICING.get(model, _FALLBACK_PRICING)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


async def track_llm_call(
    response,
    call_type: "CallType",
    *,
    student_id=None,
    lesson_id=None,
) -> None:
    """Persist one LLM call's cost: log + DB record + Lesson rollup.

    All exceptions are swallowed — tracking never breaks calling code.
    """
    try:
        from maestro.models import LLMUsageRecord, Lesson

        usage = response.usage
        model = response.model
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cost = compute_cost_usd(model, input_tokens, output_tokens)

        logger.info(
            "llm_usage",
            extra={
                "call_type": call_type.value,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "student_id": str(student_id) if student_id else None,
                "lesson_id": str(lesson_id) if lesson_id else None,
            },
        )

        await LLMUsageRecord(
            student_id=student_id,
            lesson_id=lesson_id,
            call_type=call_type,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        ).insert()

        if lesson_id is not None:
            await Lesson.find_one({"_id": lesson_id}).update(
                {
                    "$inc": {
                        "token_usage.input_tokens": input_tokens,
                        "token_usage.output_tokens": output_tokens,
                        "cost_usd": cost,
                    }
                }
            )
    except Exception:
        logger.debug(
            "track_llm_call failed silently",
            extra={"call_type": str(call_type)},
            exc_info=True,
        )


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
