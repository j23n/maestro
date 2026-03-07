"""
Utility to inspect a word in both the EPUB dictionary and MongoDB.

Usage:
    uv run python -m maestro.vocab.query <word>
    uv run python -m maestro.vocab.query andare
    uv run python -m maestro.vocab.query vestirsi   # resolves via clitic stripping
    uv run python -m maestro.vocab.query velocemente  # resolves via -mente rule
"""

import asyncio
import sys

from bson import DBRef

from maestro.db import init_db
from maestro.models import VocabularyWord, VocabularyWordDefinition
from maestro.vocab.epub_parser import parse_epub
from maestro.vocab.ingest import make_lookup
from maestro.vocab.nlp import get_nlp


def _word_ref(word: "VocabularyWord") -> DBRef:
    """Build a DBRef for querying VocabularyWordDefinition.word."""
    return DBRef(VocabularyWord.Settings.name, word.id)


async def get_word_definition(
    word: "VocabularyWord", student_level: str
) -> "VocabularyWordDefinition | None":
    """Load the student-level definition for a word, with A0→A1 fallback."""
    ref = _word_ref(word)
    wdef = await VocabularyWordDefinition.find_one(
        {"word": ref, "student_level": student_level}
    )
    if wdef is None and student_level == "A0":
        wdef = await VocabularyWordDefinition.find_one(
            {"word": ref, "student_level": "A1"}
        )
    return wdef


def _hr(char="─", width=60):
    print(char * width)


def _show_epub(word_str: str, entry) -> None:
    _hr()
    resolved = f"  (resolved from '{word_str}')" if entry.headword != word_str else ""
    print(f"EPUB  [{entry.entry_id}]  {entry.headword}{resolved}")
    if entry.hyph:
        print(f"  syllabization : {entry.hyph}")
    print(f"  POS           : {entry.pos_abbrev}")
    print(f"  senses ({len(entry.senses)}):")
    for i, s in enumerate(entry.senses, 1):
        style = f" ({s.style})" if s.style else ""
        pos_tag = f" [{s.pos}]" if s.pos else ""
        print(f"    {i}.{pos_tag}{style} {s.definition}")
        for ex in s.examples[:2]:
            print(f"       ex: {ex}")
        if s.synonyms:
            print(f"       syn: {', '.join(s.synonyms)}")
        if s.antonyms:
            print(f"       ant: {', '.join(s.antonyms)}")


async def _show_db(word_str: str) -> None:
    _hr()
    doc = await VocabularyWord.find_one(VocabularyWord.word == word_str)
    if doc is None:
        print(f"DB    '{word_str}' — not in vocabulary_words")
        return

    print(f"DB    [{doc.entry_id}]  {doc.word}  ({doc.part_of_speech}, {doc.cefr_level})")
    if doc.syllabization:
        print(f"  syllabization : {doc.syllabization}")
    print(f"  senses ({len(doc.senses)}):")
    for i, s in enumerate(doc.senses, 1):
        print(f"    {i}. {s.definition[:80]}")
        for ex in s.examples[:2]:
            print(f"       ex: {ex}")

    defs = await VocabularyWordDefinition.find({"word": _word_ref(doc)}).to_list()
    if defs:
        print(f"  definitions ({len(defs)} levels):")
        for d in sorted(defs, key=lambda x: x.student_level):
            trans = f"  [{d.translation}]" if d.translation else ""
            print(f"    {d.student_level}{trans}")
            for s in d.senses[:2]:
                print(f"      • {s.definition[:70]}")
    else:
        print("  definitions : none generated yet")


async def main(word: str) -> None:
    print(f"\nQuerying: '{word}'")

    epub = parse_epub()
    nlp = get_nlp()
    lookup = make_lookup(epub["epub_by_form"], nlp)

    entry = lookup(word)
    if entry:
        _show_epub(word, entry)
    else:
        _hr()
        print(f"EPUB  '{word}' — no entry found")

    await init_db()
    await _show_db(word)
    _hr()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m maestro.vocab.query <word>")
        sys.exit(1)
    asyncio.run(main(" ".join(sys.argv[1:])))
