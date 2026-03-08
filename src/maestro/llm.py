"""
Anthropic client factories.

All LLM calls should obtain their client from here rather than constructing
one directly. This provides a single point of configuration and a single
target for test mocking.
"""

from functools import lru_cache

import anthropic
from maestro.config import settings


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """Return a synchronous Anthropic client."""
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    """Return an asynchronous Anthropic client."""
    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )
