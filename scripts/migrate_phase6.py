"""
Phase 6 migration script — run once, idempotent.

1. Copy LearningProfile.student_interests → persona.tags, then unset student_interests
2. For each Lesson with topic field: copy topic.title → topic_title, topic.description → topic_description, then unset topic
3. For each GeneratedDrill with topic_used: unset topic_used

Run with:  uv run python scripts/migrate_phase6.py
"""
import asyncio
import logging

from pymongo import AsyncMongoClient

from maestro.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    client = AsyncMongoClient(settings.database_url)
    db = client[settings.MONGODB_DB]

    # 1. LearningProfile: student_interests → persona.tags
    profiles = db["learning_profile"]
    result = await profiles.update_many(
        {"student_interests": {"$exists": True}},
        [
            {"$set": {
                "persona.tags": {"$ifNull": ["$student_interests", []]},
                "persona.freetext": "",
            }},
            {"$unset": "student_interests"},
        ],
    )
    logger.info(f"Profiles migrated: {result.modified_count}")

    # Also ensure scenario_progress exists
    result2 = await profiles.update_many(
        {"scenario_progress": {"$exists": False}},
        {"$set": {"scenario_progress": {}}},
    )
    logger.info(f"Profiles with scenario_progress added: {result2.modified_count}")

    # 2. Lessons: topic → topic_title / topic_description
    lessons = db["lessons"]
    result = await lessons.update_many(
        {"topic": {"$exists": True}},
        [
            {"$set": {
                "topic_title": "$topic.title",
                "topic_description": "$topic.description",
            }},
            {"$unset": "topic"},
        ],
    )
    logger.info(f"Lessons migrated: {result.modified_count}")

    # 3. GeneratedDrills: unset topic_used
    drills = db["generated_drills"]
    result = await drills.update_many(
        {"topic_used": {"$exists": True}},
        {"$unset": {"topic_used": ""}},
    )
    logger.info(f"Drills migrated: {result.modified_count}")

    logger.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
