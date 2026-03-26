"""
Vocabulary cache: lemma-indexed VocabularyWord lookup, phrase-indexed lookup,
and per-level VocabularyWordDefinition lookup.

Call ensure_loaded() at startup (or before first use). Use set_definition()
to update the cache after on-demand generation without a restart.
Call invalidate() in tests to reset state between runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from maestro.models import CefrSense, VocabularyWord, VocabularyWordDefinition

logger = logging.getLogger(__name__)


@dataclass
class TranslationOnlyDef:
    """Lightweight stand-in for VocabularyWordDefinition used in A0 fallback."""

    translation: str = ""
    senses: list[CefrSense] = field(default_factory=list)


# headword (str, lowercased) → list of VocabularyWord (one per POS variant)
_word_index: dict[str, list[VocabularyWord]] = {}
# phrase (str, lowercased, multi-word) → list of VocabularyWord
_phrase_index: dict[str, list[VocabularyWord]] = {}
# (word_id_str, student_level) → VocabularyWordDefinition
_def_index: dict[tuple[str, str], VocabularyWordDefinition] = {}
_loaded: bool = False


async def ensure_loaded() -> None:
    """Load vocab data from DB if not already cached."""
    global _word_index, _phrase_index, _def_index, _loaded
    if _loaded:
        return
    words = await VocabularyWord.find_all().to_list()
    # Use the raw headword as the index key — dictionary headwords are already
    # lemmas, and running them through spaCy in isolation produces wrong lemmas
    # for some words (e.g. "attrezzatura" → "attrezzaturare").
    _word_index = {}
    _phrase_index = {}
    for word in words:
        key = word.word.lower()
        if " " in key:
            _phrase_index.setdefault(key, []).append(word)
        else:
            _word_index.setdefault(key, []).append(word)

    defs = await VocabularyWordDefinition.find_all().to_list()
    _def_index = {}
    for d in defs:
        word_id = str(d.word.ref.id) if hasattr(d.word, "ref") else str(d.word.id)
        _def_index[(word_id, d.student_level)] = d

    _loaded = True
    logger.info(
        "loaded %d words, %d phrases, %d definitions",
        len(_word_index),
        len(_phrase_index),
        len(_def_index),
    )


def word_index() -> dict[str, list[VocabularyWord]]:
    """Return the lemma→words index. Must call ensure_loaded() first."""
    return _word_index


def phrase_index() -> dict[str, list[VocabularyWord]]:
    """Return the phrase→words index. Must call ensure_loaded() first."""
    return _phrase_index


def get_definition(
    word_id: str, level: str
) -> VocabularyWordDefinition | TranslationOnlyDef | None:
    """Look up a definition by word id and student level.

    For A0: returns the A0 def if it exists (vocab_a0.yaml words), otherwise
    falls back to the A1 def with definitions/examples stripped — A0 students
    see only English translations in tooltips.
    """
    wdef = _def_index.get((word_id, level))
    if wdef is not None:
        return wdef
    if level != "A0":
        return None
    # A0 fallback: use A1 definition, translation only (deduplicated)
    a1 = _def_index.get((word_id, "A1"))
    if a1 is None:
        return None
    seen: set[str] = set()
    senses = []
    for s in a1.senses:
        if s.translation and s.translation not in seen:
            seen.add(s.translation)
            senses.append(CefrSense(definition="", translation=s.translation))
    return TranslationOnlyDef(translation=a1.translation, senses=senses)


def set_definition(word_id: str, level: str, wdef: VocabularyWordDefinition) -> None:
    """Update the cache after on-demand definition generation."""
    _def_index[(word_id, level)] = wdef


def invalidate() -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call."""
    global _word_index, _phrase_index, _def_index, _loaded
    _word_index = {}
    _phrase_index = {}
    _def_index = {}
    _loaded = False


def seed(
    words: dict[str, list[VocabularyWord]] | None = None,
    defs: dict[tuple[str, str], VocabularyWordDefinition] | None = None,
    phrases: dict[str, list[VocabularyWord]] | None = None,
) -> None:
    """Directly populate cache for testing. Marks cache as loaded."""
    global _word_index, _phrase_index, _def_index, _loaded
    if words is not None:
        _word_index = words
    if defs is not None:
        _def_index = defs
    if phrases is not None:
        _phrase_index = phrases
    _loaded = True
