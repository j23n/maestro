"""
Vocabulary ingest — enriched from the EPUB dictionary via epub_parser.

Run with:  python -m maestro.vocab.ingest

Words without an EPUB entry are skipped (no fallback).
"""

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)
from bs4 import BeautifulSoup

from maestro.db import init_db
from maestro.models import Sense, UserVocabularyCard, VocabularyWord, VocabularyWordDefinition
from maestro.vocab.epub_parser import parse_epub
from maestro.vocab.nlp import get_nlp


WORDLISTS = [
    ("A1", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a1.html"),
    ("A2", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a2.html"),
    ("B1", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b1.html"),
    ("B2", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b2.html"),
]

# UniStraPG POS abbreviations → keep raw for consistency with EPUB
POS_MAP = {
    "v.t.": "v.tr.",
    "v. t.": "v.tr.",
    "v.int.": "v.intr.",
    "v. int.": "v.intr.",
    "v.": "v.",
    "s.m.": "s.m.",
    "s.f.": "s.f.",
    "s.m./f.": "s.m./f.",
    "agg.": "agg.",
    "avv.": "avv.",
    "prep.": "prep.",
    "pron.": "pron.",
    "art.": "art.",
    "cong.": "cong.",
    "inter.": "inter.",
    "num.": "num.",
}

HEADERS = {
    "User-Agent": "maestro-italian-tutor/1.0 (language learning app; contact via github)"
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


# Compiled once at module level
_CLITIC_TRAILING_RE = re.compile(r"(\s+(si|ci|ne|lo|la|li|le|se|mi|ti|vi))+$")
_CLITIC_SUFFIX_RE = re.compile(
    r"r(si|sela|sele|sene|seli|ci|cela|celo|cene|ne|la|lo|li|le|mi|ti|vi)$"
)


def make_lookup(by_form: dict, nlp):
    """
    Return a lookup(word) callable that searches the EPUB index using:

    1. Direct form match against EPUB headwords.
    2. spaCy lemma — md model gives e.g. "alzare si" for reflexives;
       strip trailing clitic words (" si", " se ne" …) → clean lemma.
    3. Regex stripping of enclitic pronoun clusters from the original word
       (handles cavarsela, farcela, prendersela, andarsene …).
    4. Adverbs in -mente: derive the base adjective and try variants.
    """
    by_lemma: dict[str, object] = {}
    forms = list(by_form.keys())
    for form, doc in zip(forms, nlp.pipe(forms, disable=["parser", "senter", "ner"])):
        by_lemma.setdefault(doc[0].lemma_.lower(), by_form[form])

    def _lookup(word: str):
        # 1. Direct form
        if word in by_form:
            return by_form[word]

        # 2. spaCy lemma with trailing clitics stripped
        spacy_lemma = nlp(word)[0].lemma_.lower()
        clean_lemma = _CLITIC_TRAILING_RE.sub("", spacy_lemma).strip()
        for candidate in dict.fromkeys([spacy_lemma, clean_lemma]):
            if candidate in by_form:
                return by_form[candidate]
            hit = by_lemma.get(candidate)
            if hit:
                return hit

        # 3. Enclitic pronoun cluster on infinitive stem
        m = _CLITIC_SUFFIX_RE.search(word)
        if m:
            base = word[: m.start()] + "re"
            if base in by_form:
                return by_form[base]
            hit = by_lemma.get(nlp(base)[0].lemma_.lower())
            if hit:
                return hit

        # 4. Adverbs in -mente → derive base adjective
        if word.endswith("mente") and len(word) > 8:
            stem = word[:-5]
            candidates = [stem]
            if stem.endswith(("l", "r")):
                candidates.append(stem + "e")       # "cordial" → "cordiale"
            elif stem.endswith("a"):
                candidates.append(stem[:-1] + "o")  # "lenta" → "lento"
            elif stem.endswith("i"):
                candidates.append(stem[:-1] + "e")  # "felici" → "felice"
            for v in candidates:
                if v in by_form:
                    return by_form[v]
                hit = by_lemma.get(nlp(v)[0].lemma_.lower())
                if hit:
                    return hit

        return None

    return _lookup


async def ingest():
    await init_db()
    nlp = get_nlp()

    logger.info("Parsing EPUB dictionary…")
    epub = parse_epub()
    by_form = epub["epub_by_form"]
    lookup = make_lookup(by_form, nlp)

    ingested: set[str] = set()

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        for cefr_level, url in WORDLISTS:
            logger.info(f"=== {cefr_level} ===")
            wordlist = await fetch_wordlist(url, cefr_level, client)
            logger.info(f"Found {len(wordlist)} words")

            for word, pos, level in wordlist:
                if word in ingested:
                    continue

                entry = lookup(word)
                if entry is None:
                    logger.warning(f"no EPUB entry for '{word}', skipping")
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

                existing = await VocabularyWord.find_one(VocabularyWord.word == word)
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

                ingested.add(word)

    await _migrate_stale(ingested)


async def _migrate_stale(ingested: set[str]) -> None:
    """Delete VocabularyWords that have no EPUB match, plus their dependent docs."""
    all_words = await VocabularyWord.find_all().to_list()
    stale = [w for w in all_words if w.word not in ingested]
    if not stale:
        logger.info("Migration: no stale words.")
        return

    stale_ids = [w.id for w in stale]
    logger.info(
        f"Migration: removing {len(stale)} stale words: "
        f"{[w.word for w in stale[:10]]}{'…' if len(stale) > 10 else ''}"
    )

    # Delete UserVocabularyCards referencing stale words
    cards = await UserVocabularyCard.find({"word.$id": {"$in": stale_ids}}).to_list()
    for card in cards:
        await card.delete()
    logger.info(f"Deleted {len(cards)} UserVocabularyCards")

    # Delete VocabularyWordDefinitions referencing stale words
    defs = await VocabularyWordDefinition.find({"word.$id": {"$in": stale_ids}}).to_list()
    for d in defs:
        await d.delete()
    logger.info(f"Deleted {len(defs)} VocabularyWordDefinitions")

    # Delete the stale words themselves
    for w in stale:
        await w.delete()
    logger.info(f"Deleted {len(stale)} VocabularyWords")


if __name__ == "__main__":
    asyncio.run(ingest())
