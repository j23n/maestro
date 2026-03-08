"""Restore static curriculum data from a mongodump BSON directory."""

import logging
from pathlib import Path

import bson
from pymongo.errors import BulkWriteError

logger = logging.getLogger(__name__)

SEED_COLLECTIONS = [
    "grammar_points",
    "vocabulary_words",
    "comm_functions",
    "curriculum_scenarios",
    "drill_templates",
    "grammar_point_explanations",
    "vocabulary_word_definitions",
]

USER_COLLECTIONS = [
    "accounts",
    "user_vocabulary_cards",
    "learning_events",
    "learning_profile",
    "generated_drills",
    "drill_attempts",
    "lessons",
]

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed" / "current"


async def seed_if_empty(db) -> None:
    """Seed static collections from BSON dump if the database is empty."""
    if await db["grammar_points"].count_documents({}, limit=1):
        return

    if not SEED_DIR.exists():
        logger.warning("Seed directory not found: %s", SEED_DIR)
        return

    logger.info("Empty database detected — seeding from %s", SEED_DIR)
    for name in SEED_COLLECTIONS:
        path = SEED_DIR / f"{name}.bson"
        if not path.exists():
            logger.warning("Seed file missing: %s", path)
            continue
        try:
            docs = bson.decode_all(path.read_bytes())
        except Exception:
            logger.exception("Failed to decode %s", path)
            continue
        if docs:
            try:
                await db[name].insert_many(docs, ordered=False)
            except BulkWriteError as exc:
                n = exc.details.get("nInserted", 0)
                logger.info("  %s: inserted %d documents (skipped duplicates)", name, n)
                continue
            logger.info("  %s: inserted %d documents", name, len(docs))

    logger.info("Seeding complete")
