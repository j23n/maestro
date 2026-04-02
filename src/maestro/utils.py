import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

CEFR_ORDER = ["A0", "A1", "A2", "B1", "B2"]


def explanation_lang_for_level(cefr: str, target_language: str) -> str:
    """Return target_language for B1/B2 explanations, 'en' for A0/A1/A2."""
    return target_language if cefr in ("B1", "B2") else "en"


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


# Absolute path to data/ at repository root.
# Assumes utils.py is at src/maestro/utils.py (2 levels below repo root).
DATA_DIR_ROOT = Path(__file__).resolve().parents[2] / "data"


_DATA_SKIP_DIRS = frozenset({"seed", "images"})


def iter_language_dirs() -> Iterator[Path]:
    """Yield each language directory under data/, sorted alphabetically."""
    for d in sorted(DATA_DIR_ROOT.iterdir()):
        if d.is_dir() and d.name not in _DATA_SKIP_DIRS:
            yield d


def data_dir(language: str) -> Path:
    """Return the data directory for the given language."""
    return DATA_DIR_ROOT / language


def combined_lock_hash(lock_filename: str) -> str | None:
    """Combine per-language lock hashes into a single deterministic hash.

    Returns None if no lock files are found in any language directory.
    """
    h = hashlib.sha256()
    found = False
    for lang_dir in iter_language_dirs():
        lock_path = lang_dir / lock_filename
        if not lock_path.exists():
            continue
        try:
            lock_sha = json.loads(lock_path.read_text())["sha256"]
        except Exception:
            continue
        h.update(f"{lang_dir.name}:{lock_sha}".encode())
        found = True
    return h.hexdigest() if found else None


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
            _logger.error(
                f"Background task {t.get_name()!r} failed: {exc}", exc_info=exc
            )

    task.add_done_callback(_done)
    return task


_LANG_SPAN_RE = re.compile(r"<span\s+lang=[\"'][^\"']*[\"']\s*>")


def strip_lang_spans(text: str) -> str:
    """Remove <span lang="..."> wrappers, leaving inner text intact."""
    text = _LANG_SPAN_RE.sub("", text)
    return text.replace("</span>", "")


_HTML_DQ_ATTR_RE = re.compile(r'(<\w+\s+\w+=)"([^"]*)"(\s*/?>)')


def parse_llm_json(text: str) -> dict | list | None:
    """Strip markdown fences and extract the first JSON object or array from an LLM response."""
    text = re.sub(r"^```(?:json)?\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not match:
        return None
    raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # LLMs sometimes emit unescaped double-quoted HTML attributes inside
        # JSON strings (e.g. <span lang="de">), breaking the JSON.  Replace
        # them with single quotes and retry.
        repaired = _HTML_DQ_ATTR_RE.sub(r"\1'\2'\3", raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None
