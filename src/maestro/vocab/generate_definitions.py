"""
Generate VocabularyWordDefinition documents for all VocabularyWords.

Strategy:
  - B1/B2: created programmatically from VocabularyWord.senses (no Claude call)
  - A1/A2: Claude claude-opus-4-6 rewrites senses for learner-appropriate Italian

Runs in batches of 20 words. Idempotent — skips words that already have all
4 definitions.

Run with:  python -m maestro.vocab.generate_definitions
"""

import argparse
import asyncio
import json
import logging
from typing import Any

import anthropic

from maestro.db import init_db
from maestro.settings import Settings
from maestro.models import CefrSense, VocabularyWord, VocabularyWordDefinition

logger = logging.getLogger(__name__)
settings = Settings()

BATCH_SIZE = 20
LEVELS = ("A1", "A2", "B1", "B2")

SYSTEM_PROMPT = """\
You are a lexicographer creating Italian dictionary entries for language learners.

For each word you receive you are given its full dictionary senses. Produce graded
entries for A1 and A2 learners. Each entry contains:
- A filtered list of senses (fewer at A1, more at A2)
- Each sense's definition rewritten in Italian for that level
- 0–1 short example per sense (rewritten for the level if one exists)
- A single English translation (most common equivalent, 1–3 words)

Level guidance:
- A1: 1–2 senses, simplest concrete meaning only, simplest Italian vocabulary,
      present-tense examples only
- A2: up to 3 senses, most common figurative uses if very frequent, A1–A2 vocabulary

Return a JSON object only — no markdown fences, no prose. Schema:
{
  "<word>": {
    "translation": "<English>",
    "A1": {"senses": [{"definition": "...", "examples": ["..."]}]},
    "A2": {"senses": [{"definition": "...", "examples": ["..."]}]}
  },
  ...
}
"""


def _word_payload(word: VocabularyWord) -> dict[str, Any]:
    return {
        "pos": word.part_of_speech,
        "senses": [
            {
                "definition": s.definition,
                "examples": s.examples[:2],
            }
            for s in word.senses
            if s.definition
        ],
    }


def _call_claude(batch: list[VocabularyWord]) -> dict[str, Any]:
    """Call Claude claude-opus-4-6 for A1/A2 definitions of a batch of words."""
    payload = {w.word: _word_payload(w) for w in batch}
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=settings.CHAT_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    raw = msg.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


async def _has_all_definitions(word: VocabularyWord) -> bool:
    count = await VocabularyWordDefinition.find({"word.$id": word.id}).count()
    return count >= 4


async def _save_b1_b2(word: VocabularyWord, translation: str) -> None:
    """Create B1/B2 definitions by copying EPUB senses verbatim."""
    for level in ("B1", "B2"):
        existing = await VocabularyWordDefinition.find_one(
            {"word.$id": word.id, "student_level": level}
        )
        if existing:
            continue
        await VocabularyWordDefinition(
            word=word,
            student_level=level,
            senses=[
                CefrSense(definition=s.definition, examples=s.examples[:1])
                for s in word.senses
                if s.definition
            ],
            translation=translation,
        ).insert()


async def _save_a1_a2(word: VocabularyWord, claude_data: dict[str, Any]) -> None:
    """Persist A1 and A2 definitions from Claude's response."""
    entry = claude_data.get(word.word) or claude_data.get(word.word.lower())
    if not entry:
        logger.warning(f"Claude returned no data for '{word.word}'")
        return

    translation = entry.get("translation", "")

    for level in ("A1", "A2"):
        existing = await VocabularyWordDefinition.find_one(
            {"word.$id": word.id, "student_level": level}
        )
        if existing:
            continue
        level_data = entry.get(level, {})
        raw_senses = level_data.get("senses", [])
        senses = [
            CefrSense(
                definition=s.get("definition", ""),
                examples=s.get("examples", [])[:1],
            )
            for s in raw_senses
            if s.get("definition")
        ]
        if not senses:
            logger.warning(f"No {level} senses for '{word.word}'")
            continue
        await VocabularyWordDefinition(
            word=word,
            student_level=level,
            senses=senses,
            translation=translation,
        ).insert()

    # B1/B2 use the same translation from Claude
    await _save_b1_b2(word, translation)


async def generate(test: bool = False):
    await init_db()

    words = await VocabularyWord.find_all().to_list()
    logger.info(f"Found {len(words)} vocabulary words")

    # Filter to words that need at least one definition
    todo = []
    for w in words:
        if not await _has_all_definitions(w):
            todo.append(w)

    logger.info(f"{len(todo)} words need definitions")

    # Words without senses can't be defined — skip
    no_senses = [w for w in todo if not w.senses]
    if no_senses:
        logger.info(f"  {len(no_senses)} words have no EPUB senses — skipping")
        todo = [w for w in todo if w.senses]

    if test:
        todo = todo[:BATCH_SIZE]
        logger.info(f"  --test: limiting to {len(todo)} words (one batch)")

    # Process in batches
    total_batches = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        words_str = ", ".join(w.word for w in batch)
        logger.info(f"Batch {batch_num}/{total_batches}: {words_str}")

        try:
            claude_data = _call_claude(batch)
        except Exception as exc:
            logger.error(f"Claude API error on batch {batch_num}: {exc}")
            continue

        for word in batch:
            try:
                await _save_a1_a2(word, claude_data)
            except Exception as exc:
                logger.error(f"Failed to save definitions for '{word.word}': {exc}")

    logger.info("Done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate CEFR vocabulary definitions")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Only run one batch (~20 words) for testing",
    )
    args = parser.parse_args()
    asyncio.run(generate(test=args.test))
