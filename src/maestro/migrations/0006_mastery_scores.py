"""
Migration 0006 — Backfill evidence_type on LearningEvents and bootstrap
grammar_mastery_scores on LearningProfiles.

1. Sets evidence_type on existing per-activity LearningEvents based on their
   activity_type (drill→targeted, writing/speaking→productive,
   reading/listening→receptive).
2. Bootstraps grammar_mastery_scores on profiles from grammar_recent_outcomes
   using a simple ratio (no decay/weighting — approximation for existing data).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_ACTIVITY_TO_EVIDENCE = {
    "drill": "targeted",
    "writing": "productive",
    "speaking": "productive",
    "reading": "receptive",
    "listening": "receptive",
}


async def run(db) -> None:
    events_coll = db["learning_events"]
    profile_coll = db["learning_profile"]

    # --- 1. Backfill evidence_type on per-activity events ---
    total_updated = 0
    for activity_type, evidence_type in _ACTIVITY_TO_EVIDENCE.items():
        result = await events_coll.update_many(
            {
                "activity_type": activity_type,
                "evidence_type": {"$exists": False},
            },
            {"$set": {"evidence_type": evidence_type}},
        )
        if result.modified_count:
            total_updated += result.modified_count
            logger.info(
                "0006: set evidence_type=%s on %d %s events",
                evidence_type,
                result.modified_count,
                activity_type,
            )
    if total_updated:
        logger.info("0006: backfilled evidence_type on %d events total", total_updated)
    else:
        logger.info("0006: no events needed evidence_type backfill")

    # --- 2. Bootstrap grammar_mastery_scores from grammar_recent_outcomes ---
    profiles_updated = 0
    async for doc in profile_coll.find(
        {"grammar_recent_outcomes": {"$exists": True, "$ne": {}}}
    ):
        recent = doc.get("grammar_recent_outcomes", {})
        scores: dict[str, float] = {}
        for code, outcomes in recent.items():
            if outcomes:
                # Handle both old bool format and new dict format {ok: bool, ts: str}
                _ok = lambda o: o["ok"] if isinstance(o, dict) else o  # noqa: E731
                scores[code] = sum(1 if _ok(o) else -1 for o in outcomes) / len(
                    outcomes
                )
        if scores:
            await profile_coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"grammar_mastery_scores": scores}},
            )
            profiles_updated += 1
    logger.info(
        "0006: bootstrapped grammar_mastery_scores on %d profiles", profiles_updated
    )
