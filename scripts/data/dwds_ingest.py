"""
Ingest bare VocabularyWord documents from DWDS headwords JSON.

Creates one VocabularyWord per headword with empty senses — enrichment
from DWDS web pages happens on-demand when words are discovered.

Run with:  uv run python scripts/data/dwds_ingest.py
"""

import asyncio
import json
import logging
import re
import unicodedata

from pymongo.errors import BulkWriteError

from maestro.db import init_db
from maestro.models import VocabularyWord
from maestro.utils import data_dir, utcnow

logger = logging.getLogger(__name__)

HEADWORDS_PATH = data_dir("de") / "dwds_headwords.json"
BATCH_SIZE = 500

# Strip superscript digits used for homograph disambiguation (Bank¹, Bank²)
_SUPERSCRIPT_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$")


def _normalise(headword: str) -> str | None:
    """Normalise a headword, returning None if it should be skipped."""
    # Skip suffixes/prefixes (-abel, -ade)
    if headword.startswith("-"):
        return None
    # Skip symbols and non-alpha entries
    stripped = headword.strip()
    if not stripped or not stripped[0].isalpha():
        return None
    # Strip superscript disambiguation markers
    stripped = _SUPERSCRIPT_RE.sub("", stripped)
    # Normalise unicode (NFC)
    stripped = unicodedata.normalize("NFC", stripped)
    return stripped if stripped else None


def load_headwords() -> list[str]:
    """Load and filter the DWDS headwords JSON, returning deduplicated words."""
    raw: dict[str, str] = json.loads(HEADWORDS_PATH.read_text())
    seen: set[str] = set()
    words: list[str] = []
    for headword in raw:
        normalised = _normalise(headword)
        if normalised and normalised not in seen:
            seen.add(normalised)
            words.append(normalised)
    return words


async def ingest():
    await init_db()

    words = load_headwords()
    logger.info("Loaded %d unique headwords from DWDS", len(words))

    now = utcnow()
    docs = [
        VocabularyWord(
            word=w,
            part_of_speech="",
            language="de",
            senses=[],
            cefr_level=None,
            created_at=now,
            updated_at=now,
        )
        for w in words
    ]

    inserted = 0
    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        try:
            await VocabularyWord.insert_many(batch)
            inserted += len(batch)
        except BulkWriteError:
            # Fall back to individual inserts for duplicate-key handling
            for doc in batch:
                existing = await VocabularyWord.find_one(
                    VocabularyWord.word == doc.word,
                    VocabularyWord.part_of_speech == doc.part_of_speech,
                    VocabularyWord.language == doc.language,
                )
                if not existing:
                    try:
                        await doc.insert()
                        inserted += 1
                    except Exception:
                        pass  # duplicate, skip

        if (i + BATCH_SIZE) % 5000 < BATCH_SIZE:
            logger.info("Progress: %d / %d", min(i + BATCH_SIZE, len(docs)), len(docs))

    logger.info("Ingested %d bare VocabularyWord documents (language=de)", inserted)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(ingest())
