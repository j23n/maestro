"""
Migration: add default Student and set student_id on all per-student documents.

Idempotent — safe to re-run.

Run with:
  python scripts/migrate_multi_student.py
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    from maestro.db import init_db
    from maestro.models import (
        Student,
        LearningProfile,
        UserVocabularyCard,
        Lesson,
        LearningEvent,
        DrillAttempt,
        GeneratedDrill,
    )

    await init_db()

    # 1. Create default student if none exist
    existing = await Student.find_all().to_list()
    if existing:
        default = existing[0]
        logger.info(f"Using existing student: {default.name} ({default.id})")
    else:
        default = Student(name="Studente")
        await default.insert()
        logger.info(f"Created default student: {default.id}")

    # 2. Set student_id on all per-student collections
    collections = [
        (LearningProfile, "learning_profile"),
        (UserVocabularyCard, "user_vocabulary_cards"),
        (Lesson, "lessons"),
        (LearningEvent, "learning_events"),
        (DrillAttempt, "drill_attempts"),
        (GeneratedDrill, "generated_drills"),
    ]

    for model, name in collections:
        result = await model.find(
            {"student_id": {"$exists": False}}
        ).update_many({"$set": {"student_id": default.id}})
        # Also handle docs where student_id is null
        result2 = await model.find(
            {"student_id": None}
        ).update_many({"$set": {"student_id": default.id}})
        total = (result.modified_count if result else 0) + (result2.modified_count if result2 else 0)
        logger.info(f"  {name}: updated {total} documents")

    logger.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
