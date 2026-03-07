"""
Vocabulary cache: lemma-indexed VocabularyWord lookup and per-level
VocabularyWordDefinition lookup.

Call ensure_loaded() at startup (or before first use). Use set_definition()
to update the cache after on-demand generation without a restart.
Call invalidate() in tests to reset state between runs.
"""
from __future__ import annotations

import logging

from maestro.models import VocabularyWord, VocabularyWordDefinition

logger = logging.getLogger(__name__)

# headword (str, lowercased) → VocabularyWord
_word_index: dict[str, VocabularyWord] = {}
# (word_id_str, student_level) → VocabularyWordDefinition
_def_index: dict[tuple[str, str], VocabularyWordDefinition] = {}
_loaded: bool = False


async def ensure_loaded() -> None:
    """Load vocab data from DB if not already cached."""
    global _word_index, _def_index, _loaded
    if _loaded:
        return
    words = await VocabularyWord.find_all().to_list()
    # Use the raw headword as the index key — dictionary headwords are already
    # lemmas, and running them through spaCy in isolation produces wrong lemmas
    # for some words (e.g. "attrezzatura" → "attrezzaturare").
    _word_index = {}
    for word in words:
        key = word.word.lower()
        if key not in _word_index:
            _word_index[key] = word

    defs = await VocabularyWordDefinition.find_all().to_list()
    _def_index = {}
    for d in defs:
        word_id = str(d.word.ref.id) if hasattr(d.word, "ref") else str(d.word.id)
        _def_index[(word_id, d.student_level)] = d

    _loaded = True
    logger.info(
        f"[vocab_cache] loaded {len(_word_index)} words, {len(_def_index)} definitions"
    )


def word_index() -> dict[str, VocabularyWord]:
    """Return the lemma→word index. Must call ensure_loaded() first."""
    return _word_index


def get_definition(word_id: str, level: str) -> VocabularyWordDefinition | None:
    """Look up a definition by word id and student level."""
    return _def_index.get((word_id, level))


def set_definition(word_id: str, level: str, wdef: VocabularyWordDefinition) -> None:
    """Update the cache after on-demand definition generation."""
    _def_index[(word_id, level)] = wdef


def invalidate() -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call."""
    global _word_index, _def_index, _loaded
    _word_index = {}
    _def_index = {}
    _loaded = False


def seed(
    words: dict[str, VocabularyWord] | None = None,
    defs: dict[tuple[str, str], VocabularyWordDefinition] | None = None,
) -> None:
    """Directly populate cache for testing. Marks cache as loaded."""
    global _word_index, _def_index, _loaded
    if words is not None:
        _word_index = words
    if defs is not None:
        _def_index = defs
    _loaded = True
