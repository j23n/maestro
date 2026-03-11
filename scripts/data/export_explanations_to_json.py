"""
Export existing GrammarPointExplanation documents from MongoDB into grammar_points.json.

Run this ONCE before switching to the inline explanations model, to capture all
LLM-generated content from the separate collection into the JSON source of truth.

After running, execute `python -m maestro.learning.ingest` to sync to MongoDB.

Run with:  uv run python scripts/data/export_explanations_to_json.py
"""

from __future__ import annotations

import asyncio
import json
import logging

from maestro.db import init_db
from maestro.utils import data_dir

logger = logging.getLogger(__name__)


async def export() -> None:
    await init_db()

    json_path = data_dir() / "grammar_points.json"
    with open(json_path) as f:
        items = json.load(f)

    # Index JSON items by code for O(1) lookup
    items_by_code: dict[str, dict] = {item["code"]: item for item in items}

    # Use raw motor/pymongo to avoid Beanie Link resolution overhead
    from maestro.db import get_db

    db = get_db()

    # Fetch all GrammarPointExplanation docs with their grammar_point reference
    expls = await db["grammar_point_explanations"].find({}).to_list(length=None)
    gp_ids = list(
        {doc["grammar_point"].id for doc in expls if doc.get("grammar_point")}
    )

    # Build map: gp ObjectId → GP code
    gp_docs = (
        await db["grammar_points"]
        .find({"_id": {"$in": gp_ids}}, {"code": 1})
        .to_list(length=None)
    )
    id_to_code = {doc["_id"]: doc["code"] for doc in gp_docs}

    exported = 0
    skipped = 0
    for doc in expls:
        ref = doc.get("grammar_point")
        if not ref:
            continue
        gp_id = ref.id
        code = id_to_code.get(gp_id)
        if not code:
            logger.warning("GP not found for explanation id=%s", doc["_id"])
            continue
        item = items_by_code.get(code)
        if item is None:
            logger.warning("GP code %r not in grammar_points.json", code)
            continue

        level = doc.get("student_level")
        title = doc.get("title", "")
        explanation = doc.get("explanation", "")
        translation = doc.get("translation", "")

        if not explanation:
            skipped += 1
            continue

        if "explanations" not in item:
            item["explanations"] = {}

        # Don't overwrite if already present (prefer existing)
        if level not in item["explanations"]:
            item["explanations"][level] = {
                "title": title,
                "explanation": explanation,
                "translation": translation,
            }
            exported += 1
        else:
            skipped += 1

    with open(json_path, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
        f.write("\n")

    logger.info(
        "Exported %d explanations to grammar_points.json (%d skipped/already present)",
        exported,
        skipped,
    )


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(export())
