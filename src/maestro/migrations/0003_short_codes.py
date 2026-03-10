"""
Migration 0003 — Remap grammar point references from verbose unistr_codes to short codes.

Prerequisites:
  1. Run `python -m maestro.grammar.generate_short_codes` to populate short `code` and
     `unistr_code` fields in grammar_points.json.
  2. Run `python -m maestro.learning.ingest` so all grammar_points documents have both
     `code` (short) and `unistr_code` (original verbose) fields.

This migration then remaps all collections that reference grammar point codes by their
old verbose string to the new short codes.

Collections affected:
  - learning_profile          (remap dict keys in grammar_correct/error/recent_outcomes)
  - learning_events           (remap list values in grammar_correct, grammar_errors)
  - curriculum_scenarios      (remap values in gp_codes list)
  - generated_drills          (remap grammar_point_code field)
  - lessons                   (remap activities[].grammar_point_code)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(db) -> None:
    # ── Step 0: Build unistr_code → short code mapping ─────────────────────
    unistr_to_code: dict[str, str] = {}
    async for doc in db["grammar_points"].find(
        {"unistr_code": {"$exists": True}},
        {"code": 1, "unistr_code": 1},
    ):
        old = doc.get("unistr_code")
        new = doc.get("code")
        if old and new and old != new:
            unistr_to_code[old] = new

    if not unistr_to_code:
        logger.info(
            "0003: no unistr_code fields found in grammar_points — "
            "run generate_short_codes + ingest first, skipping"
        )
        return

    logger.info(
        "0003: built unistr→short map for %d grammar points", len(unistr_to_code)
    )

    # ── Step 1: Migrate learning_profile dict keys ──────────────────────────
    profile_updated = 0
    async for doc in db["learning_profile"].find({}):
        set_ops: dict = {}
        unset_ops: dict = {}

        for field in (
            "grammar_correct_counts",
            "grammar_error_counts",
            "grammar_recent_outcomes",
        ):
            old_dict: dict = doc.get(field) or {}
            for old_code, value in old_dict.items():
                new_code = unistr_to_code.get(old_code)
                if new_code:
                    set_ops[f"{field}.{new_code}"] = value
                    unset_ops[f"{field}.{old_code}"] = ""

        if set_ops or unset_ops:
            update: dict = {}
            if set_ops:
                update["$set"] = set_ops
            if unset_ops:
                update["$unset"] = unset_ops
            await db["learning_profile"].update_one({"_id": doc["_id"]}, update)
            profile_updated += 1

    logger.info(
        "0003: remapped profile dicts in %d learning_profile docs", profile_updated
    )

    # ── Step 2: Migrate learning_events lists ───────────────────────────────
    event_updated = 0
    async for doc in db["learning_events"].find({}):
        set_ops = {}

        for field in ("grammar_correct", "grammar_errors"):
            old_list: list = doc.get(field) or []
            if old_list and isinstance(old_list[0], str):
                new_list = [unistr_to_code.get(c, c) for c in old_list]
                if new_list != old_list:
                    set_ops[field] = new_list

        if set_ops:
            await db["learning_events"].update_one(
                {"_id": doc["_id"]}, {"$set": set_ops}
            )
            event_updated += 1

    logger.info("0003: remapped grammar lists in %d learning_event docs", event_updated)

    # ── Step 3: Migrate curriculum_scenarios gp_codes ───────────────────────
    scenario_updated = 0
    async for doc in db["curriculum_scenarios"].find({}):
        old_codes: list = doc.get("gp_codes") or []
        if not old_codes:
            continue
        new_codes = [unistr_to_code.get(c, c) for c in old_codes]
        if new_codes != old_codes:
            await db["curriculum_scenarios"].update_one(
                {"_id": doc["_id"]}, {"$set": {"gp_codes": new_codes}}
            )
            scenario_updated += 1

    logger.info(
        "0003: remapped gp_codes in %d curriculum_scenario docs", scenario_updated
    )

    # ── Step 4: Migrate generated_drills ────────────────────────────────────
    drill_updated = 0
    async for doc in db["generated_drills"].find({}):
        old_code = doc.get("grammar_point_code")
        if not old_code or not isinstance(old_code, str):
            continue
        new_code = unistr_to_code.get(old_code)
        if new_code:
            await db["generated_drills"].update_one(
                {"_id": doc["_id"]},
                {"$set": {"grammar_point_code": new_code}},
            )
            drill_updated += 1

    logger.info(
        "0003: remapped grammar_point_code in %d generated_drill docs", drill_updated
    )

    # ── Step 5: Migrate lessons (embedded activities) ───────────────────────
    lesson_updated = 0
    async for doc in db["lessons"].find({}):
        activities: list = doc.get("activities") or []
        set_ops = {}

        for idx, act in enumerate(activities):
            old_code = act.get("grammar_point_code")
            if old_code and isinstance(old_code, str):
                new_code = unistr_to_code.get(old_code)
                if new_code:
                    set_ops[f"activities.{idx}.grammar_point_code"] = new_code

        if set_ops:
            await db["lessons"].update_one({"_id": doc["_id"]}, {"$set": set_ops})
            lesson_updated += 1

    logger.info("0003: remapped grammar_point_code in %d lesson docs", lesson_updated)

    logger.info("0003: migration complete")
