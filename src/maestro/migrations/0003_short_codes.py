"""
Migration 0003 — Remap grammar point references from verbose unistr_codes to short codes.

Prerequisites:
  1. Run `uv run python scripts/data/generate_short_codes.py` to populate short `code` and
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

import json
import logging

from pymongo import UpdateOne

from maestro.utils import data_dir

logger = logging.getLogger(__name__)


async def run(db) -> None:
    # ── Step 0: Build unistr_code → short code mapping ─────────────────────
    # Primary source: grammar_points.json (reliable even after unistr_code is
    # removed from the Beanie model, because the field lives in the JSON file).
    with open(data_dir() / "grammar_points.json") as f:
        gp_items = json.load(f)

    unistr_to_code: dict[str, str] = {
        item["unistr_code"]: item["code"]
        for item in gp_items
        if item.get("unistr_code") and item["unistr_code"] != item["code"]
    }

    # Pre-JSON-era codes that existed in the DB before the unistr_code scheme
    # was introduced. Verified by comparing old GP labels against new GP labels
    # in grammar_points.json at migration time (March 2026).
    # Re-run the migration (it is idempotent) if any mapping is incorrect.
    _LEGACY_MAP = {
        "presente_indicativo": "ind_pres",
        "aggettivi_qualificativi": "qual_o_a_e",
        "aggettivi_dimostrativi": "dem_questo",
        "condizionale_vorrei": "vorrei",
        "preposizioni_semplici": "prep_place",
        "verbi_modali_lessicali": "percez_sig",
        "imperativo_formale": "imper_form",
    }
    unistr_to_code.update(_LEGACY_MAP)

    # Guard: warn if any _LEGACY_MAP target code is not in the current GP set.
    current_codes = {item["code"] for item in gp_items}
    for old, new in _LEGACY_MAP.items():
        if new not in current_codes:
            logger.warning(
                "0003: _LEGACY_MAP target %r not found in grammar_points.json "
                "(old code %r) — verify the mapping is still correct",
                new,
                old,
            )

    if not unistr_to_code:
        logger.info("0003: unistr_to_code map is empty — nothing to remap, skipping")
        return

    logger.info(
        "0003: built unistr→short map for %d grammar points", len(unistr_to_code)
    )

    # ── Step 1: Migrate learning_profile dict keys ──────────────────────────
    ops: list[UpdateOne] = []
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
            ops.append(UpdateOne({"_id": doc["_id"]}, update))

    if ops:
        result = await db["learning_profile"].bulk_write(ops)
        logger.info(
            "0003: remapped profile dicts in %d learning_profile docs",
            result.modified_count,
        )
    else:
        logger.info("0003: no learning_profile docs needed remapping")

    # ── Step 2: Migrate learning_events lists ───────────────────────────────
    ops = []
    async for doc in db["learning_events"].find({}):
        set_ops = {}

        for field in ("grammar_correct", "grammar_errors"):
            old_list: list = doc.get(field) or []
            if old_list and isinstance(old_list[0], str):
                new_list = [unistr_to_code.get(c, c) for c in old_list]
                if new_list != old_list:
                    set_ops[field] = new_list

        if set_ops:
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_ops}))

    if ops:
        result = await db["learning_events"].bulk_write(ops)
        logger.info(
            "0003: remapped grammar lists in %d learning_event docs",
            result.modified_count,
        )
    else:
        logger.info("0003: no learning_event docs needed remapping")

    # ── Step 3: Migrate curriculum_scenarios gp_codes ───────────────────────
    ops = []
    async for doc in db["curriculum_scenarios"].find({}):
        old_codes: list = doc.get("gp_codes") or []
        if not old_codes:
            continue
        new_codes = [unistr_to_code.get(c, c) for c in old_codes]
        if new_codes != old_codes:
            ops.append(
                UpdateOne({"_id": doc["_id"]}, {"$set": {"gp_codes": new_codes}})
            )

    if ops:
        result = await db["curriculum_scenarios"].bulk_write(ops)
        logger.info(
            "0003: remapped gp_codes in %d curriculum_scenario docs",
            result.modified_count,
        )
    else:
        logger.info("0003: no curriculum_scenario docs needed remapping")

    # ── Step 4: Migrate generated_drills ────────────────────────────────────
    ops = []
    async for doc in db["generated_drills"].find({}):
        old_code = doc.get("grammar_point_code")
        if not old_code or not isinstance(old_code, str):
            continue
        new_code = unistr_to_code.get(old_code)
        if new_code:
            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"grammar_point_code": new_code}},
                )
            )

    if ops:
        result = await db["generated_drills"].bulk_write(ops)
        logger.info(
            "0003: remapped grammar_point_code in %d generated_drill docs",
            result.modified_count,
        )
    else:
        logger.info("0003: no generated_drill docs needed remapping")

    # ── Step 5: Migrate lessons (embedded activities) ───────────────────────
    ops = []
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
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_ops}))

    if ops:
        result = await db["lessons"].bulk_write(ops)
        logger.info(
            "0003: remapped grammar_point_code in %d lesson docs", result.modified_count
        )
    else:
        logger.info("0003: no lesson docs needed remapping")

    # ── Step 6: Remove stale description field from grammar_points ──────────
    result = await db["grammar_points"].update_many({}, {"$unset": {"description": ""}})
    logger.info(
        "0003: unset description field on %d grammar_point docs", result.modified_count
    )

    logger.info("0003: migration complete")
