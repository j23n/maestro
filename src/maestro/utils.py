import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

CEFR_ORDER = ["A0", "A1", "A2", "B1", "B2"]


def cefr_levels_up_to(level: str) -> list[str]:
    """Return CEFR levels from A1 up to and including level+1.

    E.g. "A1" → ["A1", "A2"], "A2" → ["A1", "A2", "B1"], "B2" → all.
    """
    idx = CEFR_ORDER.index(level) if level in CEFR_ORDER else 0
    cap = min(idx + 2, len(CEFR_ORDER))
    return CEFR_ORDER[:cap]


def utcnow() -> datetime:
    """Timezone-aware UTC now. Drop-in replacement for deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC. Assumes naive datetimes are UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

# Absolute path to src/maestro/data/
DATA_DIR_ROOT = Path(__file__).parent / "data"


def data_dir(language: str | None = None) -> Path:
    """Return the data directory for the given language."""
    if language is None:
        from maestro.config import settings
        language = settings.TARGET_LANGUAGE
    return DATA_DIR_ROOT / language


_background_tasks: set[asyncio.Task] = set()
_pending_tasks: list[asyncio.Task] = []
_test_mode: bool = False
_logger = logging.getLogger(__name__)


def enable_test_mode():
    """Enable test mode: background tasks are collected for manual awaiting."""
    global _test_mode
    _test_mode = True


def disable_test_mode():
    """Disable test mode and clear pending tasks."""
    global _test_mode
    _test_mode = False
    _pending_tasks.clear()


async def drain_background_tasks():
    """Await all pending background tasks. Only useful in test mode."""
    while _pending_tasks:
        task = _pending_tasks.pop(0)
        try:
            await task
        except Exception:
            pass  # errors are already logged by the done callback


def create_background_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a background task with error logging. Prevents GC of the task."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    if _test_mode:
        _pending_tasks.append(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _logger.error(f"Background task {t.get_name()!r} failed: {exc}", exc_info=exc)

    task.add_done_callback(_done)
    return task


_LANG_SPAN_RE = re.compile(r'<span\s+lang="[^"]*"\s*>')


def strip_lang_spans(text: str) -> str:
    """Remove <span lang="..."> wrappers, leaving inner text intact."""
    text = _LANG_SPAN_RE.sub('', text)
    return text.replace('</span>', '')


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
