import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

CEFR_ORDER = ["A1", "A2", "B1", "B2"]


def utcnow() -> datetime:
    """Timezone-aware UTC now. Drop-in replacement for deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)

# Absolute path to src/maestro/data/
DATA_DIR = Path(__file__).parent / "data"


_background_tasks: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)


def create_background_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a background task with error logging. Prevents GC of the task."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _logger.error(f"Background task {t.get_name()!r} failed: {exc}", exc_info=exc)

    task.add_done_callback(_done)
    return task


def parse_llm_json(text: str) -> dict | list | None:
    """Strip markdown fences and extract the first JSON object or array from an LLM response."""
    text = re.sub(r"^```(?:json)?\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
