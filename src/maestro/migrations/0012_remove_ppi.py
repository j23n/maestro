"""
Migration 0012 — Remove student-generated content and raw LLM output from
persisted documents (see issue #19).

Scope:
- ``drill_attempts``: drop ``student_answer``.
- ``learning_events``: drop ``student_text`` and ``feedback``.
- ``lessons``: drop top-level ``feedback_summary``; strip PPI-bearing keys
  (``student_answer``, ``student_answers``, ``recognized_text``, ``feedback``,
  ``item_scores``, ``word_assessments``) from each entry in
  ``activities[*].result``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_ACTIVITY_RESULT_PPI_KEYS = (
    "student_answer",
    "student_answers",
    "recognized_text",
    "feedback",
    "item_scores",
    "word_assessments",
)


async def run(db) -> None:
    drill_res = await db["drill_attempts"].update_many(
        {"student_answer": {"$exists": True}},
        {"$unset": {"student_answer": ""}},
    )
    logger.info("0012: cleaned %d drill_attempts", drill_res.modified_count)

    event_res = await db["learning_events"].update_many(
        {"$or": [{"student_text": {"$exists": True}}, {"feedback": {"$exists": True}}]},
        {"$unset": {"student_text": "", "feedback": ""}},
    )
    logger.info("0012: cleaned %d learning_events", event_res.modified_count)

    lessons = db["lessons"]
    summary_res = await lessons.update_many(
        {"feedback_summary": {"$exists": True}},
        {"$unset": {"feedback_summary": ""}},
    )
    logger.info(
        "0012: unset feedback_summary on %d lessons", summary_res.modified_count
    )

    scrubbed = 0
    async for doc in lessons.find({"activities": {"$exists": True, "$ne": []}}):
        activities = doc.get("activities") or []
        changed = False
        for activity in activities:
            result = activity.get("result")
            if not isinstance(result, dict):
                continue
            for key in _ACTIVITY_RESULT_PPI_KEYS:
                if key in result:
                    result.pop(key, None)
                    changed = True
        if changed:
            await lessons.update_one(
                {"_id": doc["_id"]}, {"$set": {"activities": activities}}
            )
            scrubbed += 1

    logger.info("0012: scrubbed activity results on %d lessons", scrubbed)
