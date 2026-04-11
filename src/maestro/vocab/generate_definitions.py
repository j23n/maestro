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
from maestro.tts import word_audio_path
from maestro.llm import llm_messages_create
from maestro.models import (
    CallType,
    CefrSense,
    UserVocabularyCard,
    VocabularyWord,
    VocabularyWordDefinition,
)
from maestro.prompts import vocab as _prompts, json_output_block as _job
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


def _word_key(w: VocabularyWord) -> str:
    """Unique key for a word in the LLM payload — disambiguates homographs."""
    return f"{w.word} ({w.part_of_speech})" if w.part_of_speech else w.word


def _find_entry(word: VocabularyWord, claude_data: dict[str, Any]) -> dict | None:
    """Look up a word's entry in LLM response, tolerating dropped POS in key."""
    key = _word_key(word)
    return (
        claude_data.get(key)
        or claude_data.get(key.lower())
        or claude_data.get(word.word)
        or claude_data.get(word.word.lower())
    )


async def _call_api(
    batch: list[VocabularyWord],
    max_tokens: int = 16384,
    *,
    language: str,
) -> dict[str, Any]:
    from maestro.language import get_language_config

    lang_cfg = get_language_config(language)
    payload = {_word_key(w): _word_payload(w) for w in batch}
    user_content = json.dumps(payload, ensure_ascii=False)
    words_str = ", ".join(_word_key(w) for w in batch)
    logger.info(
        "calling LLM for vocabulary definitions",
        extra={"n_words": len(batch), "words": words_str},
    )
    lang = lang_cfg.name
    logger.debug(
        f"Claude request — system: {_prompts.definition_system.render_system(target_language=lang, json_output=_job())!r}"
    )
    logger.debug(f"Claude request — user: {user_content}")
    msg = await llm_messages_create(
        model=settings.DEFINITION_MODEL,
        max_tokens=max_tokens,
        system=_prompts.definition_system.render_system(
            target_language=lang, json_output=_job()
        ),
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
    entry = _find_entry(word, claude_data)
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


async def _apply_entry_metadata(word: VocabularyWord, entry: dict) -> None:
    """Set CEFR level and IPA on a word from an LLM response entry."""
    save_needed = False
    if word.cefr_level is None:
        cefr = entry.get("cefr_level")
        if cefr in ("A1", "A2", "B1", "B2"):
            word.cefr_level = cefr
            save_needed = True
            logger.info(
                "classified word CEFR level",
                extra={"word": word.word, "cefr_level": cefr},
            )
    ipa = entry.get("ipa")
    if ipa and not word.ipa:
        word.ipa = ipa
        save_needed = True
        logger.info("set word IPA", extra={"word": word.word, "ipa": ipa})
    if save_needed:
        await word.save()


async def generate_definitions_for_word(word: VocabularyWord) -> None:
    """Generate A1–B2 VocabularyWordDefinitions for a single word and classify its CEFR level."""
    # Skip only if the word has neither senses nor POS — German particles
    # (bitte, ja) often have POS from DWDS but no extractable senses, and the
    # LLM can still generate definitions from POS alone.  Italian words always
    # have senses from the EPUB dictionary, so this change has no effect there.
    if not word.senses and not word.part_of_speech:
        logger.info(
            "skipping definition generation: no senses or POS",
            extra={"word": word.word},
        )
        return
    logger.info("generating definitions", extra={"word": word.word})
    claude_data = await _call_api([word], max_tokens=4096, language=word.language)
    entry = _find_entry(word, claude_data)
    if entry:
        await _apply_entry_metadata(word, entry)
    await _save_all_levels(word, claude_data)


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
    words_filter: list[str] | None = None,
    level: str | None = None,
    defs_only: bool = False,
    audio_only: bool = False,
    force: bool = False,
    dry_run: bool = False,
    missing_ipa: bool = False,
):
    await init_db()

    if missing:
        my_cards = True  # --missing implies --my-cards

    # --- collect candidate words ---
    if words_filter:
        words = await VocabularyWord.find({"word": {"$in": words_filter}}).to_list()
        logger.info(f"Found {len(words)} words matching --words filter")
    elif my_cards:
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

    if level:
        words = [w for w in words if w.cefr_level == level]
        logger.info(f"{len(words)} words after --level {level} filter")

    if missing_ipa:
        words = [w for w in words if not w.ipa and w.senses]
        logger.info(f"{len(words)} words missing IPA (with senses)")
        force = True  # re-run definitions to get IPA
        defs_only = True

    # --- determine what needs work ---
    if audio_only:
        need_defs: list[VocabularyWord] = []
    elif force:
        need_defs = [w for w in words if w.senses]
    else:
        need_defs = await _collect_words_needing_regen(words)

    if defs_only:
        need_audio: list[VocabularyWord] = []
    elif force:
        need_audio = list(words)
    else:
        # Find words missing audio files — excluding words that will get audio
        # as a side effect of definition generation
        words_missing_audio = [
            w
            for w in words
            if not word_audio_path(w.word, language=w.language).exists()
        ]
        need_defs_ids = {w.id for w in need_defs}
        need_audio = [w for w in words_missing_audio if w.id not in need_defs_ids]

    logger.info(
        f"{len(need_defs)} words need definitions, {len(need_audio)} need audio"
    )

    if dry_run:
        if need_defs:
            logger.info(
                "Would regenerate definitions for: %s",
                ", ".join(w.word for w in need_defs),
            )
        if need_audio:
            logger.info(
                "Would regenerate audio for: %s",
                ", ".join(w.word for w in need_audio),
            )
        return

    if test:
        need_defs = need_defs[:BATCH_SIZE]
        need_audio = need_audio[:BATCH_SIZE]
        logger.info(f"  --test: limiting to {BATCH_SIZE} words")

    # --- process definitions in batches ---
    if need_defs:
        total_batches = (len(need_defs) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(need_defs), BATCH_SIZE):
            batch = need_defs[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            words_str = ", ".join(w.word for w in batch)
            logger.info(f"Batch {batch_num}/{total_batches}: {words_str}")

            try:
                claude_data = await _call_api(batch, language=batch[0].language)
            except Exception as exc:
                logger.error(f"API error on batch {batch_num}: {exc}")
                continue

            # Delete existing definitions only after successful API response
            # to avoid data loss if the LLM call fails.
            if force:
                for word in batch:
                    await VocabularyWordDefinition.find(
                        {"word": DBRef(VocabularyWord.Settings.name, word.id)}
                    ).delete()

            for word in batch:
                try:
                    entry = _find_entry(word, claude_data)
                    if entry:
                        await _apply_entry_metadata(word, entry)
                    await _save_all_levels(word, claude_data)
                except Exception as exc:
                    logger.error(f"Failed to save definitions for '{word.word}': {exc}")

    # --- process audio-only words ---
    for i, word in enumerate(need_audio, 1):
        try:
            logger.info(
                "[%d/%d] Generating audio for '%s'", i, len(need_audio), word.word
            )
            if force:
                path = word_audio_path(word.word, language=word.language)
                if path.exists():
                    path.unlink()
            from maestro.tts import generate_word_audio

            await generate_word_audio(word.word, language=word.language)
        except Exception as exc:
            logger.error(f"Failed to generate audio for '{word.word}': {exc}")

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
    parser.add_argument(
        "--words",
        type=str,
        default=None,
        help="Comma-separated list of words to regenerate (default: all)",
    )
    parser.add_argument(
        "--level",
        type=str,
        default=None,
        choices=["A0", "A1", "A2", "B1", "B2"],
        help="Filter by CEFR level",
    )
    parser.add_argument(
        "--defs-only",
        action="store_true",
        help="Only regenerate definitions (skip audio)",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Only regenerate audio (skip definitions)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if definitions/audio already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be regenerated without making changes",
    )
    parser.add_argument(
        "--missing-ipa",
        action="store_true",
        help="Regenerate definitions for words that have definitions but no IPA",
    )
    args = parser.parse_args()

    if args.defs_only and args.audio_only:
        parser.error("--defs-only and --audio-only are mutually exclusive")

    words_list = [w.strip() for w in args.words.split(",")] if args.words else None

    asyncio.run(
        generate(
            test=args.test,
            my_cards=args.my_cards,
            missing=args.missing,
            words_filter=words_list,
            level=args.level,
            defs_only=args.defs_only,
            audio_only=args.audio_only,
            force=args.force,
            dry_run=args.dry_run,
            missing_ipa=args.missing_ipa,
        )
    )
