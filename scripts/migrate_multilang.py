"""
Migration for multi-language support (Phase 1).

1. Rename italian_chunks -> grammar_chunks collection
2. Add language="it" to all existing language-specific documents
3. Add target_language="it" to learning_profile documents

Run once against the production database:
    python scripts/migrate_multilang.py
"""
import asyncio
import logging

from pymongo import AsyncMongoClient

from maestro.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate():
    client = AsyncMongoClient(settings.database_url)
    db = client[settings.MONGODB_DB]

    # 1. Rename collection: italian_chunks -> grammar_chunks
    collections = await db.list_collection_names()
    if "italian_chunks" in collections:
        if "grammar_chunks" in collections:
            logger.warning("Both italian_chunks and grammar_chunks exist — skipping rename")
        else:
            await db.italian_chunks.rename("grammar_chunks")
            logger.info("Renamed collection: italian_chunks -> grammar_chunks")
    else:
        logger.info("Collection italian_chunks not found — already renamed or fresh db")

    # 2. Add language="it" to language-specific document collections
    lang_collections = [
        "grammar_chunks",
        "curriculum_scenarios",
        "vocabulary_words",
        "vocabulary_word_definitions",
        "grammar_points",
        "comm_functions",
        "grammar_point_explanations",
        "drill_templates",
        "lessons",
    ]
    for coll_name in lang_collections:
        if coll_name not in await db.list_collection_names():
            logger.info(f"  Collection {coll_name} not found — skipping")
            continue
        result = await db[coll_name].update_many(
            {"language": {"$exists": False}},
            {"$set": {"language": "it"}},
        )
        logger.info(f"  {coll_name}: set language='it' on {result.modified_count} docs")

    # 3. Add target_language="it" to learning_profile documents
    if "learning_profile" in await db.list_collection_names():
        result = await db.learning_profile.update_many(
            {"target_language": {"$exists": False}},
            {"$set": {"target_language": "it"}},
        )
        logger.info(f"  learning_profile: set target_language='it' on {result.modified_count} docs")
    else:
        logger.info("  learning_profile collection not found — skipping")

    logger.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
