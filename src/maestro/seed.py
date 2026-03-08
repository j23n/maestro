"""Restore static curriculum data from seed dump files."""
import logging
from pathlib import Path

from bson import json_util

logger = logging.getLogger(__name__)

# Restore order: parents before children (Link targets first)
SEED_COLLECTIONS = [
    "grammar_points",
    "grammar_chunks",
    "vocabulary_words",
    "comm_functions",
    "curriculum_scenarios",
    "drill_templates",
    "grammar_point_explanations",    # links → grammar_points
    "vocabulary_word_definitions",   # links → vocabulary_words
]

SEED_DIR = Path(__file__).resolve().parent / "data" / "seed"


async def seed_if_empty(db) -> None:
    """Seed static collections from dump files if the database is empty.

    Args:
        db: PyMongo AsyncDatabase from get_db()
    """
    if await db["grammar_points"].count_documents({}, limit=1):
        return

    if not SEED_DIR.exists():
        logger.warning("Seed directory not found: %s", SEED_DIR)
        return

    logger.info("Empty database detected — seeding from dump files")
    for name in SEED_COLLECTIONS:
        path = SEED_DIR / f"{name}.json"
        if not path.exists():
            logger.warning("Seed file missing: %s", path)
            continue
        docs = json_util.loads(path.read_text())
        if docs:
            await db[name].insert_many(docs)
            logger.info("  %s: inserted %d documents", name, len(docs))

    logger.info("Seeding complete")
