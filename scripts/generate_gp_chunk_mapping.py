"""
One-off script: use Claude to match each GrammarPoint to its best ItalianChunk ref.

Outputs data/grammar_point_chunks.yaml.

Run with:  uv run python scripts/generate_gp_chunk_mapping.py
"""
import asyncio
import json
import logging

import yaml

from maestro.config import settings
from maestro.db import init_db
from maestro.llm import get_client
from maestro.models import ItalianChunk
from maestro.utils import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT = DATA_DIR / "grammar_point_chunks.yaml"


async def main():
    await init_db()

    # Load GPs
    with open(DATA_DIR / "grammar_points.json") as f:
        gps = json.load(f)
    logger.info(f"Loaded {len(gps)} grammar points")

    # Load chunk refs + headings
    chunks = await ItalianChunk.find_all().to_list()
    chunk_lines = []
    for c in sorted(chunks, key=lambda c: c.ref):
        heading = c.chunk_metadata.get("heading", c.ref)
        chapter = c.chunk_metadata.get("chapter", "")
        chunk_lines.append(f"  {c.ref}  |  {heading}  |  chapter: {chapter}")
    chunk_list = "\n".join(chunk_lines)
    logger.info(f"Loaded {len(chunks)} chunks")

    client = get_client()

    # Process in batches by category to keep prompts focused
    by_category: dict[str, list] = {}
    for gp in gps:
        by_category.setdefault(gp["category"], []).append(gp)

    mapping: dict[str, str | None] = {}

    for category, cat_gps in by_category.items():
        gp_lines = []
        for gp in cat_gps:
            gp_lines.append(
                f"  {gp['code']}  |  {gp['label']}  |  {gp['cefr_level']}  |  {gp['description']}"
            )
        gp_list = "\n".join(gp_lines)

        prompt = f"""You are matching Italian grammar learning objectives to textbook chapter sections.

Below are GRAMMAR POINTS (learning objectives from a CEFR curriculum):
{gp_list}

Below are CHUNK REFS (sections from an Italian grammar textbook):
{chunk_list}

For each grammar point, pick the SINGLE best matching chunk ref.
Some grammar points may not have a good match — use "null" for those.

Output ONLY a YAML mapping, one line per grammar point:
grammar_point_code: chunk_ref
grammar_point_code: null

No other text. Output ALL {len(cat_gps)} grammar points in category "{category}"."""

        logger.info(f"Calling Claude for category '{category}' ({len(cat_gps)} GPs)...")
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]

        try:
            batch = yaml.safe_load(raw)
            if isinstance(batch, dict):
                for code, ref in batch.items():
                    if ref == "null" or ref is None:
                        mapping[code] = None
                    else:
                        mapping[code] = ref
                logger.info(f"  Parsed {len(batch)} mappings for '{category}'")
            else:
                logger.error(f"  Unexpected YAML structure for '{category}': {type(batch)}")
                logger.error(f"  Raw: {raw[:500]}")
        except yaml.YAMLError as e:
            logger.error(f"  YAML parse error for '{category}': {e}")
            logger.error(f"  Raw: {raw[:500]}")

    # Validate
    valid_refs = {c.ref for c in chunks}
    all_codes = {gp["code"] for gp in gps}
    missing = all_codes - set(mapping.keys())
    if missing:
        logger.warning(f"{len(missing)} GP codes missing from mapping: {missing}")

    invalid_refs = {
        code: ref for code, ref in mapping.items()
        if ref is not None and ref not in valid_refs
    }
    if invalid_refs:
        logger.warning(f"{len(invalid_refs)} mappings point to non-existent chunk refs:")
        for code, ref in invalid_refs.items():
            logger.warning(f"  {code}: {ref}")

    null_count = sum(1 for v in mapping.values() if v is None)
    logger.info(f"Total mappings: {len(mapping)}, null: {null_count}, valid: {len(mapping) - null_count - len(invalid_refs)}")

    # Write output
    with open(OUTPUT, "w") as f:
        yaml.dump(
            {k: v for k, v in sorted(mapping.items())},
            f,
            default_flow_style=False,
            allow_unicode=True,
            width=200,
        )
    logger.info(f"Written to {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
