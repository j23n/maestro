"""
Migration 0009 — Fix lessons stuck with a PENDING activity at current_index.

When background generation appended activities to an initially-empty lesson,
the first activity was left in "pending" status instead of being activated.
This caused a redirect loop: the route redirected to the current activity,
which was PENDING, which redirected to the current activity, etc.

For each affected lesson:
- If the lesson is ACTIVE and its current activity is PENDING, activate it.
- If the lesson is stuck in a state that can't recover (no activities at all),
  mark it as abandoned.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LESSONS_COLL = "lessons"


async def run(db) -> None:
    coll = db[LESSONS_COLL]

    activated = 0
    abandoned = 0

    async for lesson in coll.find({"status": "active"}):
        activities = lesson.get("activities", [])
        current_index = lesson.get("current_index", 0)

        if not activities:
            # Active lesson with no activities — abandon it
            await coll.update_one(
                {"_id": lesson["_id"]},
                {"$set": {"status": "abandoned"}},
            )
            abandoned += 1
            logger.info(
                "0009: abandoned empty lesson %s",
                lesson["_id"],
            )
            continue

        if current_index >= len(activities):
            continue

        activity = activities[current_index]
        if activity.get("status") == "pending":
            await coll.update_one(
                {"_id": lesson["_id"]},
                {"$set": {f"activities.{current_index}.status": "active"}},
            )
            activated += 1
            logger.info(
                "0009: activated stuck activity %d on lesson %s",
                current_index,
                lesson["_id"],
            )

    logger.info(
        "0009: fixed %d stuck lessons (activated=%d, abandoned=%d)",
        activated + abandoned,
        activated,
        abandoned,
    )
