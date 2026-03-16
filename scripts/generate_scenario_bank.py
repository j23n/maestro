"""
One-off script: use Claude to cluster A1 CFs and GPs into curriculum scenarios.

Outputs data/scenarios_a1.yaml.

Run with:  uv run python scripts/generate_scenario_bank.py
"""

import json
import logging

import yaml

from maestro.llm import get_client
from maestro.utils import data_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT = data_dir() / "scenarios_a1.yaml"


def main():
    with open(data_dir() / "grammar_points.yaml") as f:
        all_gps = yaml.safe_load(f)
    with open(data_dir() / "comm_functions.json") as f:
        all_cfs = json.load(f)

    a1_gps = [g for g in all_gps if g["cefr_level"] == "A1"]
    a1_cfs = [c for c in all_cfs if c["cefr_level"] == "A1"]
    logger.info(f"A1 GPs: {len(a1_gps)}, A1 CFs: {len(a1_cfs)}")

    gp_lines = []
    for gp in a1_gps:
        gp_lines.append(
            f"  {gp['code']}  |  {gp['label']}  |  category: {gp['category']}"
        )

    cf_lines = []
    for cf in a1_cfs:
        desc = cf.get("description", cf["label"])
        cf_lines.append(
            f"  {cf['code']}  |  {cf['label']}  |  macro: {cf['macro_category']}  |  {desc[:80]}"
        )

    prompt = f"""You are an expert Italian language curriculum designer.

Below are ALL A1-level communicative functions (CFs) and grammar points (GPs) from the CEFR Italian curriculum.

COMMUNICATIVE FUNCTIONS ({len(a1_cfs)} items):
{chr(10).join(cf_lines)}

GRAMMAR POINTS ({len(a1_gps)} items):
{chr(10).join(gp_lines)}

Cluster these into 15-20 real-world SCENARIOS for A1 Italian learners. Each scenario is a concrete, everyday situation (ordering at a bar, asking for directions, introducing yourself, etc.).

Rules:
- Each scenario maps to 3-6 CF codes and 3-8 GP codes that are naturally exercised in that situation
- CFs and GPs CAN appear in multiple scenarios (real life overlaps)
- EVERY CF code and EVERY GP code must appear in at least one scenario — no orphans
- Each scenario has 3 depth levels: 1=introduction, 2=developing, 3=consolidating
- Slugs must be URL-safe (lowercase, hyphens, no accents)
- Labels should be short Italian phrases
- Descriptions in English

Output ONLY valid YAML matching this exact structure (no markdown fences):
scenarios:
  - slug: al-bar
    label: "Al bar"
    description: "Ordering drinks and snacks at an Italian cafe"
    cefr_level: A1
    cf_codes:
      - code_1
      - code_2
    gp_codes:
      - code_1
      - code_2
    depths:
      - "Depth 1: ordering a coffee — basic requests, greetings, numbers for paying"
      - "Depth 2: asking what's available, expressing preferences, small talk"
      - "Depth 3: handling a misunderstanding, asking about ingredients"

Output ALL scenarios now."""

    client = get_client()
    logger.info("Calling Claude to generate scenario bank...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.error(f"YAML parse error: {e}")
        logger.error(f"Raw output:\n{raw}")
        return

    scenarios = data.get("scenarios", [])
    logger.info(f"Generated {len(scenarios)} scenarios")

    # Validate coverage
    all_gp_codes = {g["code"] for g in a1_gps}
    all_cf_codes = {c["code"] for c in a1_cfs}
    used_gp_codes: set[str] = set()
    used_cf_codes: set[str] = set()
    for s in scenarios:
        used_gp_codes.update(s.get("gp_codes", []))
        used_cf_codes.update(s.get("cf_codes", []))

    orphan_gps = all_gp_codes - used_gp_codes
    orphan_cfs = all_cf_codes - used_cf_codes
    if orphan_gps:
        logger.warning(f"Orphan GPs ({len(orphan_gps)}): {orphan_gps}")
    if orphan_cfs:
        logger.warning(f"Orphan CFs ({len(orphan_cfs)}): {orphan_cfs}")

    invalid_gps = used_gp_codes - all_gp_codes
    invalid_cfs = used_cf_codes - all_cf_codes
    if invalid_gps:
        logger.warning(f"Invalid GP codes ({len(invalid_gps)}): {invalid_gps}")
    if invalid_cfs:
        logger.warning(f"Invalid CF codes ({len(invalid_cfs)}): {invalid_cfs}")

    if not orphan_gps and not orphan_cfs:
        logger.info(
            "Full coverage: all GPs and CFs are assigned to at least one scenario"
        )

    with open(OUTPUT, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, width=200)
    logger.info(f"Written to {OUTPUT}")


if __name__ == "__main__":
    main()
