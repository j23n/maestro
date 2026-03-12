"""
Anthropic client factories and LLM cost tracking.

All LLM calls should go through llm_messages_create rather than constructing
a client directly. This provides automatic cost recording and a single target
for test mocking.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

import anthropic
import httpx
from anthropic import (
    APIStatusError as AnthropicAPIStatusError,
    APITimeoutError as AnthropicAPITimeoutError,
    RateLimitError,
)
from maestro.config import settings
from maestro.errors import (
    APIRateLimitError,
    APIStatusError,
    APITimeoutError,
    APIUnavailableError,
)
from maestro.models import CallType, LLMUsageRecord

logger = logging.getLogger(__name__)


async def create_message(client, **kwargs):
    """Thin wrapper around client.messages.create with error classification.

    Translates Anthropic-specific errors into provider-agnostic errors from
    maestro.errors so callers never import anthropic types directly.
    """
    try:
        return await client.messages.create(**kwargs)
    except RateLimitError as e:
        logger.warning("llm_rate_limited", extra={"error": str(e)})
        raise APIRateLimitError("Rate limited", provider="anthropic") from e
    except AnthropicAPITimeoutError as e:
        logger.warning("llm_timeout", extra={"error": str(e)})
        raise APITimeoutError("Timeout", provider="anthropic") from e
    except AnthropicAPIStatusError as e:
        logger.error(
            "llm_api_error",
            extra={"status": e.status_code, "error": str(e)},
        )
        raise APIStatusError(
            f"API error {e.status_code}",
            status_code=e.status_code,
            provider="anthropic",
        ) from e


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


async def _record_llm_usage(
    response,
    entity_id,
    student_id,
    duration_ms: float,
    call_type: CallType,
) -> None:
    """Log and persist one LLM call's usage. Swallows all exceptions."""
    # --- Extract usage fields and emit structured log ---
    try:
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
                "duration_ms": round(duration_ms, 1),
                "student_id": str(student_id) if student_id else None,
                "entity_id": str(entity_id) if entity_id else None,
            },
        )
    except Exception:
        logger.warning(
            "record_llm_usage: failed to extract usage from response",
            extra={"call_type": str(call_type)},
            exc_info=True,
        )
        return

    # --- Persist to DB ---
    if entity_id is None:
        logger.warning(
            "record_llm_usage: entity_id is None, skipping DB insert",
            extra={"call_type": call_type.value},
        )
        return

    try:
        await LLMUsageRecord(
            student_id=student_id,
            entity_id=entity_id,
            call_type=call_type,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        ).insert()
    except Exception:
        logger.warning(
            "record_llm_usage: DB insert failed",
            extra={"call_type": call_type.value},
            exc_info=True,
        )


async def llm_messages_create(
    *,
    model: str,
    messages: list,
    max_tokens: int,
    system: str,
    entity_id,
    call_type: CallType,
    student_id=None,
    **kwargs,
) -> anthropic.types.Message:
    """Make an async Anthropic messages.create call and record usage automatically."""
    logger.debug(
        "llm_request",
        extra={
            "call_type": call_type.value,
            "model": model,
            "system": system,
            "messages": messages,
        },
    )
    client = get_async_client()
    t0 = time.monotonic()
    try:
        response = await create_message(
            client,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            system=system,
            **kwargs,
        )
    except APIUnavailableError:
        raise
    except Exception:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.warning(
            "llm_messages_create: API call failed",
            extra={
                "call_type": call_type.value,
                "model": model,
                "duration_ms": round(duration_ms, 1),
            },
            exc_info=True,
        )
        raise
    duration_ms = (time.monotonic() - t0) * 1000
    await _record_llm_usage(response, entity_id, student_id, duration_ms, call_type)
    return response


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """Return a synchronous Anthropic client."""
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=2,
        timeout=httpx.Timeout(60.0, connect=5.0),
    )


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    """Return an asynchronous Anthropic client."""
    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=2,
        timeout=httpx.Timeout(60.0, connect=5.0),
    )
