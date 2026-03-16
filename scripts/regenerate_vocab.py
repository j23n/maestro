"""Regenerate definitions and/or audio for VocabularyWords.

Useful when definition prompts change, TTS voice/settings change, or words
were ingested without definitions.  Supports filtering by word list, CEFR
level, and regeneration mode (defs-only, audio-only, or both).

Run with:
    uv run python scripts/regenerate_vocab.py [OPTIONS]

Examples:
    # Dry-run: see what would be regenerated
    uv run python scripts/regenerate_vocab.py --dry-run

    # Regenerate definitions only for A1 words
    uv run python scripts/regenerate_vocab.py --level A1 --defs-only

    # Force-regenerate audio for specific words
    uv run python scripts/regenerate_vocab.py --words mangiare,bere --audio-only --force

    # Regenerate everything that's missing
    uv run python scripts/regenerate_vocab.py
"""

import argparse
import asyncio
import logging

from bson import DBRef

from maestro.db import init_db
from maestro.models import VocabularyWord, VocabularyWordDefinition
from maestro.tts import generate_word_audio, word_audio_path
from maestro.vocab.generate_definitions import (
    _collect_words_needing_regen,
    generate_definitions_for_word,
)

logger = logging.getLogger(__name__)


async def _collect_words(
    *,
    words_filter: list[str] | None,
    level: str | None,
) -> list[VocabularyWord]:
    """Load and filter VocabularyWords from the database."""
    if words_filter:
        all_words = await VocabularyWord.find({"word": {"$in": words_filter}}).to_list()
    else:
        all_words = await VocabularyWord.find_all().to_list()

    if level:
        all_words = [w for w in all_words if w.cefr_level == level]

    return all_words


async def main(
    *,
    words_filter: list[str] | None = None,
    level: str | None = None,
    defs_only: bool = False,
    audio_only: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    await init_db()

    all_words = await _collect_words(words_filter=words_filter, level=level)
    logger.info("Found %d words matching filters", len(all_words))

    # Determine which words need work
    if audio_only:
        need_defs: list[VocabularyWord] = []
    elif force:
        need_defs = [w for w in all_words if w.senses]
    else:
        need_defs = await _collect_words_needing_regen(all_words)

    if defs_only:
        need_audio: list[VocabularyWord] = []
    elif force:
        need_audio = list(all_words)
    else:
        need_audio = [w for w in all_words if not word_audio_path(w.word).exists()]

    need_defs_ids = {w.id for w in need_defs}

    logger.info(
        "%d words need definitions, %d need audio", len(need_defs), len(need_audio)
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

    # Process definitions
    for i, word in enumerate(need_defs, 1):
        try:
            logger.info(
                "[%d/%d] Generating definitions for '%s'", i, len(need_defs), word.word
            )
            if force:
                # Delete existing definitions so they're regenerated
                await VocabularyWordDefinition.find(
                    {"word": DBRef(VocabularyWord.Settings.name, word.id)}
                ).delete()
            await generate_definitions_for_word(word)
        except Exception as exc:
            logger.error("Failed to generate definitions for '%s': %s", word.word, exc)

    # Process audio (skip words that already got audio via generate_definitions_for_word)
    for i, word in enumerate(need_audio, 1):
        if word.id in need_defs_ids and not force:
            # generate_definitions_for_word already handles audio
            continue
        try:
            logger.info(
                "[%d/%d] Generating audio for '%s'", i, len(need_audio), word.word
            )
            if force:
                path = word_audio_path(word.word)
                if path.exists():
                    path.unlink()
            await generate_word_audio(word.word)
        except Exception as exc:
            logger.error("Failed to generate audio for '%s': %s", word.word, exc)

    logger.info("Done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Regenerate definitions and/or audio for vocabulary words"
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
    args = parser.parse_args()

    if args.defs_only and args.audio_only:
        parser.error("--defs-only and --audio-only are mutually exclusive")

    words_list = [w.strip() for w in args.words.split(",")] if args.words else None

    asyncio.run(
        main(
            words_filter=words_list,
            level=args.level,
            defs_only=args.defs_only,
            audio_only=args.audio_only,
            force=args.force,
            dry_run=args.dry_run,
        )
    )
