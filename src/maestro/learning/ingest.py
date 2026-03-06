"""
One-off ingest script:
  1. Replace all GrammarPoint documents from grammar_points.json (full replace)
  2. Set chunk_ref on each GP from the static mapping file
  3. Replace all CommunicativeFunction documents from comm_functions.json
  4. Seed DrillTemplate specs (grammar points × 3 exercise types)
  5. Create empty LearningProfile if none exists

Run with:
  python -m maestro.learning.ingest
"""
import asyncio
import json
import logging

import yaml

from maestro.db import init_db

logger = logging.getLogger(__name__)
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    DrillTemplate,
    GrammarPoint,
    GrammarPointExplanation,
)
from maestro.profile import get_or_create_profile
from maestro.utils import DATA_DIR

EXERCISE_TYPES = ("fill_blank", "error_correction", "free_form")
CHUNK_MAPPING_FILE = DATA_DIR / "grammar_point_chunks.yaml"


async def upsert_grammar_points() -> list[GrammarPoint]:
    with open(DATA_DIR / "grammar_points.json") as f:
        items = json.load(f)
    await GrammarPointExplanation.find().delete()
    await GrammarPoint.find().delete()
    docs = [GrammarPoint(**item) for item in items]
    await GrammarPoint.insert_many(docs)
    # Re-fetch so documents have their _id set (insert_many doesn't mutate the originals)
    inserted = await GrammarPoint.find_all().to_list()
    logger.info(f"Grammar points: replaced with {len(inserted)} records")
    return inserted


async def link_grammar_points_to_chunks(grammar_points: list[GrammarPoint]) -> None:
    """Set chunk_ref on each GP from the static mapping file."""
    if not CHUNK_MAPPING_FILE.exists():
        logger.warning(f"Chunk mapping file not found: {CHUNK_MAPPING_FILE}")
        return

    with open(CHUNK_MAPPING_FILE) as f:
        mapping = yaml.safe_load(f) or {}

    for gp in grammar_points:
        ref = mapping.get(gp.code)
        if ref:
            gp.chunk_ref = ref
            await gp.save()
        else:
            logger.warning(f"  No chunk mapping for GP: {gp.code}")

    mapped = sum(1 for gp in grammar_points if gp.chunk_ref)
    logger.info(f"Chunk refs set: {mapped}/{len(grammar_points)}")


async def upsert_comm_functions() -> None:
    with open(DATA_DIR / "comm_functions.json") as f:
        items = json.load(f)
    await CommunicativeFunction.find().delete()
    docs = []
    for item in items:
        if not item.get("description"):
            patterns = item.get("patterns", [])
            item["description"] = "; ".join(patterns[:3]) if patterns else item["label"]
        docs.append(CommunicativeFunction(**item))
    await CommunicativeFunction.insert_many(docs)
    logger.info(f"Communicative functions: inserted {len(docs)} items")


async def upsert_drill_templates(grammar_points: list[GrammarPoint]) -> None:
    """Seed spec-only DrillTemplate records (no content, no Claude calls)."""
    total_new = 0
    for gp in grammar_points:
        for exercise_type in EXERCISE_TYPES:
            existing = await DrillTemplate.find_one(
                DrillTemplate.grammar_point_code == gp.code,
                DrillTemplate.exercise_type == exercise_type,
            )
            if existing:
                continue
            t = DrillTemplate(
                grammar_point_code=gp.code,
                cefr_level=gp.cefr_level,
                exercise_type=exercise_type,
            )
            await t.insert()
            total_new += 1
    logger.info(f"Drill templates: inserted {total_new} new spec records")


async def seed_scenarios() -> None:
    """Upsert CurriculumScenario documents from scenarios_a1.yaml."""
    scenario_file = DATA_DIR / "scenarios_a1.yaml"
    if not scenario_file.exists():
        logger.warning(f"Scenario file not found: {scenario_file}")
        return

    with open(scenario_file) as f:
        data = yaml.safe_load(f)

    scenarios = data.get("scenarios", [])
    for item in scenarios:
        existing = await CurriculumScenario.find_one({"slug": item["slug"]})
        if existing:
            for key, val in item.items():
                setattr(existing, key, val)
            await existing.save()
        else:
            await CurriculumScenario(**item).insert()
    logger.info(f"Scenarios: upserted {len(scenarios)} records")


async def ingest():
    await init_db()

    logger.info("=== Ingesting grammar points ===")
    grammar_points = await upsert_grammar_points()

    logger.info("=== Linking grammar points to chunks ===")
    await link_grammar_points_to_chunks(grammar_points)

    logger.info("=== Ingesting communicative functions ===")
    await upsert_comm_functions()

    logger.info("=== Seeding drill template specs ===")
    await upsert_drill_templates(grammar_points)

    logger.info("=== Seeding curriculum scenarios ===")
    await seed_scenarios()

    logger.info("=== Ensuring LearningProfile exists ===")
    await get_or_create_profile()
    logger.info("  LearningProfile ensured")

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(ingest())
