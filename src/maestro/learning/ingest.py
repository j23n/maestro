"""
One-off ingest script:
  1. Replace all GrammarPoint documents from grammar_points.json (full replace)
  2. Set chunk_ref on each GP from the static mapping file
  3. Replace all CommunicativeFunction documents from comm_functions.json
  4. Create empty LearningProfile if none exists

Run with:
  python -m maestro.learning.ingest
"""

import asyncio
import json
import logging

import yaml
from bson import DBRef

from maestro.config import settings
from maestro.db import init_db

from maestro.models import (
    CefrSense,
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    Sense,
    VocabularyWord,
    VocabularyWordDefinition,
)
from maestro.utils import data_dir, utcnow

logger = logging.getLogger(__name__)


async def upsert_grammar_points() -> list[GrammarPoint]:
    with open(data_dir() / "grammar_points.json") as f:
        items = json.load(f)
    new_codes = {item["code"] for item in items}
    # Remove GPs that no longer exist in the data file
    existing = await GrammarPoint.find_all().to_list()
    for gp in existing:
        if gp.code not in new_codes:
            await gp.delete()
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
                await CurriculumScenario(
                    **item, language=settings.TARGET_LANGUAGE
                ).insert()
        total += len(scenarios)
    logger.info(f"Scenarios: upserted {total} records")


async def seed_a0_vocab() -> None:
    """Upsert A0 vocabulary words from vocab_a0.json and create A0-level definitions."""
    vocab_file = data_dir() / "vocab_a0.json"
    if not vocab_file.exists():
        logger.warning(f"A0 vocab file not found: {vocab_file}")
        return

    with open(vocab_file) as f:
        items = json.load(f)

    count = 0
    def_count = 0
    for item in items:
        item_pos = item.get("part_of_speech", "")
        query = {"word": item["word"]}
        if item_pos:
            query["part_of_speech"] = item_pos
        existing = await VocabularyWord.find_one(query)
        now = utcnow()
        if existing:
            existing.cefr_level = item.get("cefr_level", "A0")
            existing.part_of_speech = item.get(
                "part_of_speech", existing.part_of_speech
            )
            existing.updated_at = now
            await existing.save()
            word_doc = existing
        else:
            senses = [
                Sense(**{k: v for k, v in s.items() if k in ("definition", "examples")})
                for s in item.get("senses", [])
            ]
            word_doc = VocabularyWord(
                word=item["word"],
                part_of_speech=item.get("part_of_speech", ""),
                cefr_level=item.get("cefr_level", "A0"),
                senses=senses,
                language=settings.TARGET_LANGUAGE,
                created_at=now,
                updated_at=now,
            )
            await word_doc.insert()
            count += 1

        # Create A0-level VocabularyWordDefinition from enriched sense data
        raw_senses = item.get("senses", [])
        cefr_senses = [
            CefrSense(
                definition=s.get("definition", ""),
                translation=s.get("translation", ""),
                examples=[],
            )
            for s in raw_senses
            if s.get("definition")
        ]
        if cefr_senses:
            # Aggregate translations for top-level
            translations = [s.translation for s in cefr_senses if s.translation]
            top_translation = "; ".join(translations) if translations else ""

            existing_def = await VocabularyWordDefinition.find_one(
                {
                    "word": DBRef(VocabularyWord.Settings.name, word_doc.id),
                    "student_level": "A0",
                }
            )
            if existing_def:
                existing_def.senses = cefr_senses
                existing_def.translation = top_translation
                existing_def.updated_at = utcnow()
                await existing_def.save()
            else:
                await VocabularyWordDefinition(
                    word=word_doc,
                    student_level="A0",
                    senses=cefr_senses,
                    translation=top_translation,
                    language=settings.TARGET_LANGUAGE,
                    created_at=utcnow(),
                ).insert()
                def_count += 1

    logger.info(
        f"A0 vocab: {count} new words inserted, {def_count} new definitions ({len(items)} total)"
    )


async def ingest():
    await init_db()

    logger.info("=== Ingesting grammar points ===")
    await upsert_grammar_points()

    logger.info("=== Ingesting communicative functions ===")
    await upsert_comm_functions()

    logger.info("=== Seeding curriculum scenarios ===")
    await seed_scenarios()

    logger.info("=== Seeding A0 vocabulary ===")
    await seed_a0_vocab()

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(ingest())
