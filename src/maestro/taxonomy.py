"""
Shared cache for grammar points and communicative functions.

Used by analyzer.py and lesson_analyzer.py to avoid repeated DB queries.
Call invalidate() after bulk writes (e.g. ingest scripts) to force a refresh.
"""
from __future__ import annotations

import logging
from maestro.models import GrammarPoint, CommunicativeFunction

logger = logging.getLogger(__name__)

_grammar_points: list[GrammarPoint] = []
_comm_functions: list[CommunicativeFunction] = []
_loaded: bool = False


async def ensure_loaded() -> None:
    """Load taxonomy data from DB if not already cached."""
    global _grammar_points, _comm_functions, _loaded
    if _loaded:
        return
    _grammar_points = await GrammarPoint.find_all().to_list()
    _comm_functions = await CommunicativeFunction.find_all().to_list()
    _loaded = True
    logger.info(
        f"[taxonomy] loaded {len(_grammar_points)} grammar points, "
        f"{len(_comm_functions)} comm functions"
    )


def grammar_points() -> list[GrammarPoint]:
    """Return cached grammar points. Must call ensure_loaded() first."""
    return _grammar_points


def comm_functions() -> list[CommunicativeFunction]:
    """Return cached communicative functions. Must call ensure_loaded() first."""
    return _comm_functions


def invalidate() -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call."""
    global _grammar_points, _comm_functions, _loaded
    _grammar_points = []
    _comm_functions = []
    _loaded = False


def seed(
    gps: list[GrammarPoint] | None = None,
    cfs: list[CommunicativeFunction] | None = None,
) -> None:
    """Directly populate cache for testing. Marks cache as loaded."""
    global _grammar_points, _comm_functions, _loaded
    if gps is not None:
        _grammar_points = gps
    if cfs is not None:
        _comm_functions = cfs
    _loaded = True
