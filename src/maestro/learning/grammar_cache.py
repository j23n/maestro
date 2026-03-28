"""
Shared cache for grammar points and communicative functions.

Used by analyzer.py and lesson_analyzer.py to avoid repeated DB queries.
Call invalidate() after bulk writes (e.g. ingest scripts) to force a refresh.

Caches are keyed by language code so multiple target languages can coexist.
"""

from __future__ import annotations

import logging
from maestro.models import GrammarPoint, CommunicativeFunction

logger = logging.getLogger(__name__)

_grammar_points: dict[str, list[GrammarPoint]] = {}
_comm_functions: dict[str, list[CommunicativeFunction]] = {}


async def ensure_loaded(language: str | None = None) -> None:
    """Load taxonomy data from DB if not already cached for *language*."""
    if language is None:
        from maestro.config import settings

        language = settings.TARGET_LANGUAGE

    if language in _grammar_points:
        return

    gps = await GrammarPoint.find(GrammarPoint.language == language).to_list()
    cfs = await CommunicativeFunction.find(
        CommunicativeFunction.language == language
    ).to_list()
    _grammar_points[language] = gps
    _comm_functions[language] = cfs
    logger.info(
        "[grammar_cache] loaded %d grammar points, %d comm functions (language=%s)",
        len(gps),
        len(cfs),
        language,
    )


def grammar_points(language: str | None = None) -> list[GrammarPoint]:
    """Return cached grammar points. Must call ensure_loaded() first."""
    if language is None:
        from maestro.config import settings

        language = settings.TARGET_LANGUAGE
    return _grammar_points.get(language, [])


def comm_functions(language: str | None = None) -> list[CommunicativeFunction]:
    """Return cached communicative functions. Must call ensure_loaded() first."""
    if language is None:
        from maestro.config import settings

        language = settings.TARGET_LANGUAGE
    return _comm_functions.get(language, [])


def invalidate(language: str | None = None) -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call.

    Pass a language code to clear only that language, or None to clear all.
    """
    if language is None:
        _grammar_points.clear()
        _comm_functions.clear()
    else:
        _grammar_points.pop(language, None)
        _comm_functions.pop(language, None)


def seed(
    gps: list[GrammarPoint] | None = None,
    cfs: list[CommunicativeFunction] | None = None,
    *,
    language: str = "it",
) -> None:
    """Directly populate cache for testing. Marks cache as loaded.

    Always sets both dicts for the language so ensure_loaded() considers
    the language fully cached.
    """
    _grammar_points.setdefault(language, [])
    _comm_functions.setdefault(language, [])
    if gps is not None:
        _grammar_points[language] = gps
    if cfs is not None:
        _comm_functions[language] = cfs
