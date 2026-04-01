"""
Vocabulary cache: lemma-indexed VocabularyWord lookup, phrase-indexed lookup,
and per-level VocabularyWordDefinition lookup.

Call ensure_loaded() at startup (or before first use). Use set_definition()
to update the cache after on-demand generation without a restart.
Call invalidate() in tests to reset state between runs.

Caches are keyed by language code so multiple target languages can coexist.
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


@dataclass
class _LangCache:
    word_index: dict[str, list[VocabularyWord]] = field(default_factory=dict)
    phrase_index: dict[str, list[VocabularyWord]] = field(default_factory=dict)
    def_index: dict[tuple[str, str], VocabularyWordDefinition] = field(
        default_factory=dict
    )


_caches: dict[str, _LangCache] = {}


def _get(language: str) -> _LangCache:
    cache = _caches.get(language)
    if cache is None:
        logger.warning(
            "vocab cache not loaded for language '%s' — returning empty; "
            "call ensure_loaded() first",
            language,
        )
        return _LangCache()
    return cache


async def ensure_loaded(language: str) -> None:
    """Load vocab data from DB if not already cached for *language*."""
    lang = language
    if lang in _caches:
        return

    words = await VocabularyWord.find(VocabularyWord.language == lang).to_list()
    cache = _LangCache()
    # Use the raw headword as the index key — dictionary headwords are already
    # lemmas, and running them through spaCy in isolation produces wrong lemmas
    # for some words (e.g. "attrezzatura" → "attrezzaturare").
    for word in words:
        key = word.word.lower()
        if " " in key:
            cache.phrase_index.setdefault(key, []).append(word)
        else:
            cache.word_index.setdefault(key, []).append(word)

    defs = await VocabularyWordDefinition.find(
        VocabularyWordDefinition.language == lang
    ).to_list()
    for d in defs:
        word_id = str(d.word.ref.id) if hasattr(d.word, "ref") else str(d.word.id)
        cache.def_index[(word_id, d.student_level)] = d

    _caches[lang] = cache
    logger.info(
        "loaded %d words, %d phrases, %d definitions (language=%s)",
        len(cache.word_index),
        len(cache.phrase_index),
        len(cache.def_index),
        lang,
    )


def word_index(language: str) -> dict[str, list[VocabularyWord]]:
    """Return the lemma->words index. Must call ensure_loaded() first."""
    return _get(language).word_index


def phrase_index(language: str) -> dict[str, list[VocabularyWord]]:
    """Return the phrase->words index. Must call ensure_loaded() first."""
    return _get(language).phrase_index


def get_definition(
    word_id: str,
    level: str,
    language: str,
) -> VocabularyWordDefinition | TranslationOnlyDef | None:
    """Look up a definition by word id and student level.

    For A0: returns the A0 def if it exists (vocab_a0.yaml words), otherwise
    falls back to the A1 def with definitions/examples stripped — A0 students
    see only English translations in tooltips.
    """
    cache = _get(language)
    wdef = cache.def_index.get((word_id, level))
    if wdef is not None:
        return wdef
    if level != "A0":
        return None
    # A0 fallback: use A1 definition, translation only (deduplicated)
    a1 = cache.def_index.get((word_id, "A1"))
    if a1 is None:
        return None
    seen: set[str] = set()
    senses = []
    for s in a1.senses:
        if s.translation and s.translation not in seen:
            seen.add(s.translation)
            senses.append(CefrSense(definition="", translation=s.translation))
    return TranslationOnlyDef(translation=a1.translation, senses=senses)


def set_definition(
    word_id: str,
    level: str,
    wdef: VocabularyWordDefinition,
    language: str,
) -> None:
    """Update the cache after on-demand definition generation."""
    lang = language
    if lang not in _caches:
        _caches[lang] = _LangCache()
    _caches[lang].def_index[(word_id, level)] = wdef


def invalidate(language: str | None = None) -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call.

    Pass a language code to clear only that language, or None to clear all.
    """
    if language is None:
        _caches.clear()
    else:
        _caches.pop(language, None)


def seed(
    words: dict[str, list[VocabularyWord]] | None = None,
    defs: dict[tuple[str, str], VocabularyWordDefinition] | None = None,
    phrases: dict[str, list[VocabularyWord]] | None = None,
    *,
    language: str = "it",
) -> None:
    """Directly populate cache for testing. Marks cache as loaded."""
    cache = _caches.get(language, _LangCache())
    if words is not None:
        cache.word_index = words
    if defs is not None:
        cache.def_index = defs
    if phrases is not None:
        cache.phrase_index = phrases
    _caches[language] = cache
