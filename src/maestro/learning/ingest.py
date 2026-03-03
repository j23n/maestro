"""
One-off ingest script (idempotent):
  1. Upsert GrammarPoint documents from grammar_points.json
  2. Upsert CommunicativeFunction documents from comm_functions.json
  3. Seed DrillTemplate specs (44 grammar points × 3 exercise types = 132 records)
  4. Create empty LearningProfile if none exists

Run with:
  python -m maestro.learning.ingest
"""
import asyncio
import json
import logging

from maestro.db import init_db

logger = logging.getLogger(__name__)
from maestro.models import (
    CommunicativeFunction,
    DrillTemplate,
    GrammarPoint,
    LearningProfile,
)
from maestro.rag.retrieve import retrieve_for_grammar_point
from maestro.utils import DATA_DIR

EXERCISE_TYPES = ("fill_blank", "error_correction", "free_form")


async def upsert_grammar_points() -> list[GrammarPoint]:
    with open(DATA_DIR / "grammar_points.json") as f:
        items = json.load(f)
    points = []
    for item in items:
        existing = await GrammarPoint.find_one(GrammarPoint.code == item["code"])
        if existing:
            points.append(existing)
            continue
        gp = GrammarPoint(**item)
        await gp.insert()
        logger.info(f"  [grammar] inserted {gp.code}")
        points.append(gp)
    logger.info(f"Grammar points: {len(points)} total")
    return points


async def link_grammar_points_to_rag(grammar_points: list[GrammarPoint]) -> None:
    """Semantic-search the RAG index for each grammar point and persist the top chunk refs.

    Prints an audit line per grammar point so matches can be manually reviewed.
    Raises RuntimeError if any grammar point returns no RAG results (RAG not ingested?).
    """
    failed: list[str] = []
    for gp in grammar_points:
        results = await retrieve_for_grammar_point(gp.label, gp.description, top_k=3)
        if not results:
            failed.append(gp.code)
            logger.error(f"  [ERROR] No RAG match for: {gp.code} ({gp.label})")
            continue
        gp.rag_refs = [r.chunk.ref for r in results]
        await gp.save()
        logger.info(f"  [RAG] {gp.code}: {gp.label}")
        for r in results:
            heading = r.chunk.chunk_metadata.get("heading", r.chunk.ref)
            logger.info(f"    → '{heading}'  (score: {r.similarity:.2f})")

    if failed:
        raise RuntimeError(
            f"No RAG chunks found for {len(failed)} grammar point(s): {', '.join(failed)}. "
            "Run 'python -m maestro.rag.ingest' first."
        )


async def upsert_comm_functions() -> None:
    with open(DATA_DIR / "comm_functions.json") as f:
        items = json.load(f)
    count = 0
    for item in items:
        existing = await CommunicativeFunction.find_one(
            CommunicativeFunction.code == item["code"]
        )
        if existing:
            continue
        cf = CommunicativeFunction(**item)
        await cf.insert()
        count += 1
    logger.info(f"Communicative functions: inserted {count} new items")


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


async def ingest():
    await init_db()

    logger.info("=== Ingesting grammar points ===")
    grammar_points = await upsert_grammar_points()

    logger.info("=== Linking grammar points to RAG rules ===")
    await link_grammar_points_to_rag(grammar_points)

    logger.info("=== Ingesting communicative functions ===")
    await upsert_comm_functions()

    logger.info("=== Seeding drill template specs ===")
    await upsert_drill_templates(grammar_points)

    logger.info("=== Ensuring LearningProfile exists ===")
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()
        logger.info("  Created empty LearningProfile")
    else:
        logger.info("  LearningProfile already exists")

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(ingest())
