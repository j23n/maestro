"""
Generate VocabularyWordDefinition documents for all VocabularyWords.

Strategy:
  - A1–B2: Claude rewrites senses for learner-appropriate target language
    at each level, with per-sense English translations.

Runs in batches of 5 words. Idempotent — skips words that already have all
4 definitions with per-sense translations.

Run with:  python -m maestro.vocab.generate_definitions
"""

import argparse
import asyncio
import json
import logging
from typing import Any

from bson import DBRef

from maestro.db import init_db
from maestro.config import settings
from maestro.tts import _word_audio_path
from maestro.llm import llm_messages_create
from maestro.models import (
    CallType,
    CefrSense,
    UserVocabularyCard,
    VocabularyWord,
    VocabularyWordDefinition,
)
from maestro.prompts import vocab as _prompts
from maestro.utils import utcnow

logger = logging.getLogger(__name__)

BATCH_SIZE = 5


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


async def _call_api(
    batch: list[VocabularyWord], max_tokens: int = 16384
) -> dict[str, Any]:
    payload = {w.word: _word_payload(w) for w in batch}
    user_content = json.dumps(payload, ensure_ascii=False)
    words_str = ", ".join(w.word for w in batch)
    logger.info(
        "calling LLM for vocabulary definitions",
        extra={"n_words": len(batch), "words": words_str},
    )
    lang = settings.TARGET_LANGUAGE_NAME
    logger.debug(
        f"Claude request — system: {_prompts.definition_system.render_system(target_language=lang)!r}"
    )
    logger.debug(f"Claude request — user: {user_content}")
    msg = await llm_messages_create(
        model=settings.DEFINITION_MODEL,
        max_tokens=max_tokens,
        system=_prompts.definition_system.render_system(target_language=lang),
        messages=[{"role": "user", "content": user_content}],
        # entity_id is keyed to the first word in the batch; the single LLM call
        # covers all words in the batch, so only one usage record is written.
        entity_id=batch[0].id,
        call_type=CallType.VOCAB_DEFINITION,
    )
    raw = msg.content[0].text.strip()
    logger.debug(f"Claude response: {raw}")
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def _is_complete(defs: list[VocabularyWordDefinition]) -> bool:
    """Check if a word has all 4 level definitions with per-sense translations."""
    if len(defs) < 4:
        return False
    for d in defs:
        if any(not s.translation for s in d.senses):
            return False
    return True


async def _save_all_levels(word: VocabularyWord, claude_data: dict[str, Any]) -> None:
    """Persist A1–B2 definitions from Claude's response. Replaces existing."""
    entry = claude_data.get(word.word) or claude_data.get(word.word.lower())
    if not entry:
        logger.error("LLM returned no data for word", extra={"word": word.word})
        return

    top_translation = entry.get("translation", "")

    for level in ("A1", "A2", "B1", "B2"):
        level_data = entry.get(level, {})
        raw_senses = level_data.get("senses", [])
        senses = [
            CefrSense(
                definition=s.get("definition", ""),
                translation=s.get("translation", ""),
                examples=s.get("examples", [])[:1],
            )
            for s in raw_senses
            if s.get("definition")
        ]
        if not senses:
            logger.warning(
                "no senses for level", extra={"word": word.word, "level": level}
            )
            continue

        # Use top-level translation, fall back to aggregated sense translations
        translation = top_translation
        if not translation:
            sense_trs = [s.translation for s in senses if s.translation]
            translation = "; ".join(sense_trs) if sense_trs else ""

        existing = await VocabularyWordDefinition.find_one(
            {
                "word": DBRef(VocabularyWord.Settings.name, word.id),
                "student_level": level,
            }
        )
        if existing:
            existing.senses = senses
            existing.translation = translation
            existing.updated_at = utcnow()
            await existing.save()
            logger.info("updated definition", extra={"word": word.word, "level": level})
        else:
            await VocabularyWordDefinition(
                word=word,
                student_level=level,
                senses=senses,
                translation=translation,
                created_at=utcnow(),
            ).insert()
            logger.info("saved definition", extra={"word": word.word, "level": level})


async def generate_definitions_for_word(word: VocabularyWord) -> None:
    """Generate A1–B2 VocabularyWordDefinitions for a single word and classify its CEFR level."""
    if not word.senses:
        logger.info(
            "skipping definition generation: no senses", extra={"word": word.word}
        )
        return
    logger.info("generating definitions", extra={"word": word.word})
    claude_data = await _call_api([word], max_tokens=4096)
    entry = claude_data.get(word.word) or claude_data.get(word.word.lower())
    if entry and word.cefr_level is None:
        cefr = entry.get("cefr_level")
        if cefr in ("A1", "A2", "B1", "B2"):
            word.cefr_level = cefr
            await word.save()
            logger.info(
                "classified word CEFR level",
                extra={"word": word.word, "cefr_level": cefr},
            )
    await _save_all_levels(word, claude_data)
    # Generate audio if missing
    if word.audio_path is None:
        from maestro.tts import generate_word_audio

        audio_url = await generate_word_audio(word.word)
        if audio_url:
            word.audio_path = audio_url
            await word.save()


async def _collect_words_needing_regen(
    words: list[VocabularyWord],
) -> list[VocabularyWord]:
    """Filter to words whose definitions are missing or lack per-sense translations."""
    todo = []
    for w in words:
        if not w.senses:
            continue
        defs = await VocabularyWordDefinition.find(
            {
                "word": DBRef(VocabularyWord.Settings.name, w.id),
                "student_level": {"$in": ["A1", "A2", "B1", "B2"]},
            }
        ).to_list()
        if not _is_complete(defs):
            todo.append(w)
    return todo


async def generate(
    test: bool = False,
    my_cards: bool = False,
    missing: bool = False,
):
    await init_db()

    if missing:
        my_cards = True  # --missing implies --my-cards

    if my_cards:
        cards = await UserVocabularyCard.find_all().to_list()
        word_ids = set()
        for c in cards:
            ref = c.word
            word_ids.add(ref.ref.id if hasattr(ref, "ref") else ref.id)
        words = await VocabularyWord.find({"_id": {"$in": list(word_ids)}}).to_list()
        logger.info(f"Found {len(words)} words from {len(cards)} vocabulary cards")
    else:
        words = await VocabularyWord.find_all().to_list()
        logger.info(f"Found {len(words)} vocabulary words")

    if missing:
        # Include words missing definitions OR audio
        words_missing_audio = [
            w for w in words if not _word_audio_path(w.word).exists()
        ]
        todo_defs = await _collect_words_needing_regen(words)
        todo_def_ids = {w.id for w in todo_defs}
        todo = todo_defs + [w for w in words_missing_audio if w.id not in todo_def_ids]
        logger.info(f"{len(todo)} words need (re)generation or audio (--missing)")
    else:
        todo = await _collect_words_needing_regen(words)
        logger.info(f"{len(todo)} words need (re)generation")

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
            claude_data = await _call_api(batch)
        except Exception as exc:
            logger.error(f"API error on batch {batch_num}: {exc}")
            continue

        for word in batch:
            try:
                entry = claude_data.get(word.word) or claude_data.get(word.word.lower())
                if entry and word.cefr_level is None:
                    cefr = entry.get("cefr_level")
                    if cefr in ("A1", "A2", "B1", "B2"):
                        word.cefr_level = cefr
                        await word.save()
                        logger.info(
                            "classified word CEFR level",
                            extra={"word": word.word, "cefr_level": cefr},
                        )
                await _save_all_levels(word, claude_data)
                # Generate audio if missing
                if word.audio_path is None:
                    from maestro.tts import generate_word_audio

                    audio_url = await generate_word_audio(word.word)
                    if audio_url:
                        word.audio_path = audio_url
                        await word.save()
            except Exception as exc:
                logger.error(f"Failed to save definitions for '{word.word}': {exc}")

    logger.info("Done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate CEFR vocabulary definitions")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Only run one batch (~5 words) for testing",
    )
    parser.add_argument(
        "--my-cards",
        action="store_true",
        help="Only regenerate definitions for words in UserVocabularyCards",
    )
    parser.add_argument(
        "--missing",
        action="store_true",
        help="Process UserVocabularyCard words missing definitions OR audio",
    )
    args = parser.parse_args()
    asyncio.run(generate(test=args.test, my_cards=args.my_cards, missing=args.missing))
