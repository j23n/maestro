"""
Migration 0008 — Remove VocabularyWordDefinition entries whose sense text
contains HTML tags (e.g. ``<span lang="it">``).

An older LLM prompt run wrapped Italian definitions and examples in
``<span lang="it">...</span>`` tags.  These cause nested ``lang`` elements
when rendered inside ``<span class="sense-def" lang="it">``, which breaks
discover() annotation (``_has_nested_lang`` filters out all text nodes
inside the inner ``<span lang="it">``).

Affected words typically have duplicate definitions — the old tagged ones
and newer clean ones.  This migration deletes any definition doc where at
least one sense contains an HTML tag.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

DEFS_COLL = "vocabulary_word_definitions"

_TAG_RE = re.compile(r"<[^>]+>")


async def run(db) -> None:
    coll = db[DEFS_COLL]

    removed = 0
    async for doc in coll.find():
        senses = doc.get("senses", [])
        has_tags = any(
            _TAG_RE.search(s.get("definition", ""))
            or any(_TAG_RE.search(ex) for ex in s.get("examples", []))
            for s in senses
        )
        if has_tags:
            await coll.delete_one({"_id": doc["_id"]})
            removed += 1

    logger.info("0008: removed %d definitions with HTML tags", removed)
