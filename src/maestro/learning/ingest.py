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

from maestro.config import settings
from maestro.db import init_db

logger = logging.getLogger(__name__)
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    DrillTemplate,
    ExerciseType,
    GrammarPoint,
    GrammarPointExplanation,
    Sense,
    VocabularyWord,
)
from maestro.utils import data_dir

EXERCISE_TYPES = (ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION, ExerciseType.FREE_FORM)


async def upsert_grammar_points() -> list[GrammarPoint]:
    with open(data_dir() / "grammar_points.json") as f:
        items = json.load(f)
    new_codes = {item["code"] for item in items}
    # Remove GPs (and their explanations) that no longer exist in the data file
    existing = await GrammarPoint.find_all().to_list()
    for gp in existing:
        if gp.code not in new_codes:
            await GrammarPointExplanation.find({"grammar_point.$id": gp.id}).delete()
            await gp.delete()
    # Upsert by code — preserves _id so explanations stay linked
    gp_fields = set(GrammarPoint.model_fields.keys()) - {"id"}
    for item in items:
        gp = await GrammarPoint.find_one({"code": item["code"]})
        if gp:
            for key, val in item.items():
                if key in gp_fields:
                    setattr(gp, key, val)
            await gp.save()
        else:
            filtered = {k: v for k, v in item.items() if k in gp_fields}
            await GrammarPoint(**filtered, language=settings.TARGET_LANGUAGE).insert()
    inserted = await GrammarPoint.find_all().to_list()
    logger.info(f"Grammar points: upserted {len(inserted)} records")
    return inserted


async def link_grammar_points_to_chunks(grammar_points: list[GrammarPoint]) -> None:
    """Set chunk_ref on each GP from the static mapping file."""
    CHUNK_MAPPING_FILE = data_dir() / "grammar_point_chunks.yaml"
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
    with open(data_dir() / "comm_functions.json") as f:
        items = json.load(f)
    await CommunicativeFunction.find().delete()
    docs = []
    for item in items:
        if not item.get("description"):
            patterns = item.get("patterns", [])
            item["description"] = "; ".join(patterns[:3]) if patterns else item["label"]
        docs.append(CommunicativeFunction(**item, language=settings.TARGET_LANGUAGE))
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
                language=settings.TARGET_LANGUAGE,
            )
            await t.insert()
            total_new += 1
    logger.info(f"Drill templates: inserted {total_new} new spec records")


async def seed_scenarios() -> None:
    """Upsert CurriculumScenario documents from scenario YAML files."""
    total = 0
    for filename in ("scenarios_a0.yaml", "scenarios_a1.yaml"):
        scenario_file = data_dir() / filename
        if not scenario_file.exists():
            logger.warning(f"Scenario file not found: {scenario_file}")
            continue

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
                await CurriculumScenario(**item, language=settings.TARGET_LANGUAGE).insert()
        total += len(scenarios)
    logger.info(f"Scenarios: upserted {total} records")


async def seed_a0_vocab() -> None:
    """Upsert A0 vocabulary words from vocab_a0.json."""
    vocab_file = data_dir() / "vocab_a0.json"
    if not vocab_file.exists():
        logger.warning(f"A0 vocab file not found: {vocab_file}")
        return

    with open(vocab_file) as f:
        items = json.load(f)

    count = 0
    for item in items:
        existing = await VocabularyWord.find_one({"word": item["word"]})
        if existing:
            existing.cefr_level = item.get("cefr_level", "A0")
            existing.part_of_speech = item.get("part_of_speech", existing.part_of_speech)
            await existing.save()
        else:
            senses = [Sense(**s) for s in item.get("senses", [])]
            await VocabularyWord(
                word=item["word"],
                part_of_speech=item.get("part_of_speech", ""),
                cefr_level=item.get("cefr_level", "A0"),
                senses=senses,
                language=settings.TARGET_LANGUAGE,
            ).insert()
            count += 1
    logger.info(f"A0 vocab: {count} new words inserted ({len(items)} total)")


async def seed_a0_grammar_explanations(grammar_points: list[GrammarPoint]) -> None:
    """Seed static A0 grammar explanations from JSON file."""
    expl_file = data_dir() / "a0_grammar_explanations.json"
    if not expl_file.exists():
        logger.warning(f"A0 grammar explanations file not found: {expl_file}")
        return

    with open(expl_file) as f:
        data = json.load(f)

    gp_by_code = {gp.code: gp for gp in grammar_points if gp.cefr_level == "A0"}
    count = 0
    for code, texts in data.items():
        gp = gp_by_code.get(code)
        if not gp:
            logger.warning(f"  A0 GP not found for code: {code}")
            continue
        existing = await GrammarPointExplanation.find_one(
            {"grammar_point.$id": gp.id, "student_level": "A0"}
        )
        if existing:
            existing.title = texts["title"]
            existing.explanation = texts["explanation"]
            await existing.save()
        else:
            await GrammarPointExplanation(
                grammar_point=gp,
                student_level="A0",
                title=texts["title"],
                explanation=texts["explanation"],
                language=settings.TARGET_LANGUAGE,
            ).insert()
            count += 1
    logger.info(f"A0 grammar explanations: {count} new, {len(data)} total")


async def ingest():
    await init_db()

    logger.info("=== Ingesting grammar points ===")
    grammar_points = await upsert_grammar_points()

    logger.info("=== Linking grammar points to chunks ===")
    await link_grammar_points_to_chunks(grammar_points)

    logger.info("=== Seeding A0 grammar explanations ===")
    await seed_a0_grammar_explanations(grammar_points)

    logger.info("=== Ingesting communicative functions ===")
    await upsert_comm_functions()

    logger.info("=== Seeding drill template specs ===")
    await upsert_drill_templates(grammar_points)

    logger.info("=== Seeding curriculum scenarios ===")
    await seed_scenarios()

    logger.info("=== Seeding A0 vocabulary ===")
    await seed_a0_vocab()

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(ingest())
