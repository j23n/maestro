"""
Vocabulary ingest — enriched from the EPUB dictionary via epub_parser.

Run with:  python -m maestro.vocab.ingest

Words without an EPUB entry are skipped (no fallback).
"""

import asyncio
import logging
import re

import httpx

from bs4 import BeautifulSoup

from maestro.db import init_db
from maestro.models import Sense, VocabularyWord
from maestro.vocab.epub_parser import parse_epub
from maestro.vocab.morphology import get_lookup_factory
from maestro.vocab.morphology.it import WORDLISTS, POS_MAP
from maestro.vocab.nlp import get_nlp

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "maestro-language-tutor/1.0 (language learning app; contact via github)"
}


async def fetch_wordlist(
    url: str, cefr_level: str, client: httpx.AsyncClient
) -> list[tuple[str, str, str]]:
    response = await client.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    legend = soup.find("table", class_="tablelegenda")
    word_table = legend.find_next_sibling("table")
    seen: dict[str, tuple[str, str, str]] = {}
    for a in word_table.find_all("a"):
        word = a.get_text(strip=True).split("(")[0].split("/")[0].strip().lower()
        trailing = a.next_sibling or ""
        match = re.search(r"\(([^)]+)\)", str(trailing))
        raw_pos = match.group(1).strip() if match else ""
        pos = POS_MAP.get(raw_pos, raw_pos or "unknown")
        if word:
            seen[word] = (word, pos, cefr_level)
    return list(seen.values())


async def ingest():
    await init_db()
    nlp = get_nlp()

    logger.info("Parsing EPUB dictionary…")
    epub = parse_epub()
    by_form = epub["epub_by_form"]
    make_lookup = get_lookup_factory()
    lookup = make_lookup(by_form, nlp)

    ingested: set[tuple[str, str]] = set()

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        for cefr_level, url in WORDLISTS:
            logger.info(f"=== {cefr_level} ===")
            wordlist = await fetch_wordlist(url, cefr_level, client)
            logger.info(f"Found {len(wordlist)} words")

            for word, pos, level in wordlist:
                entry = lookup(word)
                if entry is None:
                    logger.warning(f"no EPUB entry for '{word}', skipping")
                    continue

                if (word, entry.pos_abbrev) in ingested:
                    continue

                senses = [
                    Sense(
                        definition=s.definition,
                        examples=s.examples,
                        synonyms=s.synonyms,
                        antonyms=s.antonyms,
                        pos=s.pos,
                        style=s.style,
                    )
                    for s in entry.senses
                ]

                existing = await VocabularyWord.find_one(
                    VocabularyWord.word == word,
                    VocabularyWord.part_of_speech == entry.pos_abbrev,
                )
                if existing:
                    existing.syllabization = entry.hyph
                    existing.part_of_speech = entry.pos_abbrev
                    existing.cefr_level = level
                    existing.entry_id = entry.entry_id
                    existing.senses = senses
                    await existing.save()
                    logger.info(f"updated: {word}")
                else:
                    await VocabularyWord(
                        word=word,
                        syllabization=entry.hyph,
                        part_of_speech=entry.pos_abbrev,
                        cefr_level=level,
                        entry_id=entry.entry_id,
                        senses=senses,
                    ).insert()
                    logger.info(f"inserted: {word} ({entry.pos_abbrev}, {level})")

                ingested.add((word, entry.pos_abbrev))

    logger.info(f"Phase 1: {len(ingested)} CEFR words ingested")

    # Phase 2: ingest all remaining EPUB headwords with no CEFR level
    new_words = []
    for headword, entry in by_form.items():
        if (headword, entry.pos_abbrev) in ingested:
            continue
        senses = [
            Sense(
                definition=s.definition,
                examples=s.examples,
                synonyms=s.synonyms,
                antonyms=s.antonyms,
                pos=s.pos,
                style=s.style,
            )
            for s in entry.senses
        ]
        new_words.append(
            VocabularyWord(
                word=headword,
                syllabization=entry.hyph,
                part_of_speech=entry.pos_abbrev,
                cefr_level=None,
                entry_id=entry.entry_id,
                senses=senses,
            )
        )
        ingested.add((headword, entry.pos_abbrev))

    BATCH = 500
    inserted_count = 0
    for i in range(0, len(new_words), BATCH):
        batch = new_words[i : i + BATCH]
        try:
            await VocabularyWord.insert_many(batch)
            inserted_count += len(batch)
        except Exception:
            # Fall back to individual upserts for this batch (handles duplicate key errors)
            for w in batch:
                existing = await VocabularyWord.find_one(
                    VocabularyWord.word == w.word,
                    VocabularyWord.part_of_speech == w.part_of_speech,
                )
                if not existing:
                    await w.insert()
                    inserted_count += 1

    logger.info(f"Phase 2: inserted {inserted_count} non-CEFR EPUB entries")


if __name__ == "__main__":
    asyncio.run(ingest())
