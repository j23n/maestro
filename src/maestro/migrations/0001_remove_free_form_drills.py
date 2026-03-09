"""
Migration 0001 — Remove free_form drill documents.

ExerciseType.FREE_FORM has been removed from the codebase (issue #27).
Existing documents with exercise_type="free_form" would cause Beanie
validation errors if fetched. This migration deletes them.

Collections affected:
  - drill_templates   (DrillTemplate)
  - generated_drills  (GeneratedDrill)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FILTER = {"exercise_type": "free_form"}


async def run(db) -> None:
    templates = await db["drill_templates"].delete_many(_FILTER)
    logger.info(
        "0001: deleted %d drill_templates with exercise_type=free_form",
        templates.deleted_count,
    )

    drills = await db["generated_drills"].delete_many(_FILTER)
    logger.info(
        "0001: deleted %d generated_drills with exercise_type=free_form",
        drills.deleted_count,
    )
