"""
Generate A1 curriculum scenarios by clustering CFs and GPs with an LLM.

Uses the Italian A1 scenarios as structural reference when generating for
other languages, so themes can be reused where appropriate.

Run with:
  uv run python scripts/generate_scenario_bank.py --lang de
  uv run python scripts/generate_scenario_bank.py --lang it
"""

import argparse
import json
import logging

import httpx
import yaml

from maestro.language import LANGUAGES
from maestro.llm import get_client
from maestro.utils import data_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IT_SCENARIOS = data_dir("it") / "scenarios_a1.yaml"


def _build_reference_block(lang: str) -> str:
    """Return Italian A1 scenarios as structural reference (only for non-Italian)."""
    if lang == "it" or not IT_SCENARIOS.exists():
        return ""
    with open(IT_SCENARIOS) as f:
        it_data = yaml.safe_load(f)
    lines = []
    for s in it_data["scenarios"]:
        lines.append(
            f"  phase {s['phase']}  {s['slug']:30s}  "
            f"GPs: {len(s['gp_codes'])}  CFs: {len(s['cf_codes'])}  "
            f"— {s['description']}"
        )
    return (
        "\n\nREFERENCE — Italian A1 scenarios (reuse themes where they fit, "
        "adapt or replace where German culture differs):\n" + "\n".join(lines)
    )


def _language_prompt(lang: str, lang_name: str) -> str:
    """Return language-specific guidance for the LLM prompt."""
    if lang == "de":
        return """
Language-specific guidance for German:
- Labels should be short German phrases (e.g. "Sich vorstellen", "Im Café")
- Slugs must be URL-safe (lowercase, hyphens, no umlauts — use ae/oe/ue/ss)
- Scenarios should reflect life in a German-speaking city (Munich flavour is fine)
- German-specific situations to consider: Bäckerei, Biergarten, Mülltrennung,
  Anmeldung (city registration), Deutsche Bahn, Wochenmarkt
- The case system (Nominativ/Akkusativ/Dativ) and sentence bracket (Satzklammer)
  are central to German — spread these across multiple scenarios
- Some Italian scenarios overlap with German A0 (café, hotel) — make the A1 versions
  substantially more complex, or replace with fresh scenarios if the theme is exhausted
"""
    if lang == "it":
        return """
Language-specific guidance for Italian:
- Labels should be short Italian phrases (e.g. "Al bar", "Presentarsi")
- Slugs must be URL-safe (lowercase, hyphens, no accents)
"""
    return f"\nLabels should be in {lang_name}. Slugs must be URL-safe.\n"


def main():
    parser = argparse.ArgumentParser(description="Generate A1 curriculum scenarios")
    parser.add_argument(
        "--lang",
        required=True,
        choices=sorted(LANGUAGES),
        help="Target language code (e.g. de, it)",
    )
    args = parser.parse_args()

    lang = args.lang
    lang_name = LANGUAGES[lang].name

    with open(data_dir(lang) / "grammar_points.yaml") as f:
        all_gps = yaml.safe_load(f)
    with open(data_dir(lang) / "comm_functions.json") as f:
        all_cfs = json.load(f)

    a1_gps = [g for g in all_gps if g["cefr_level"] == "A1"]
    a1_cfs = [c for c in all_cfs if c["cefr_level"] == "A1"]
    logger.info(f"{lang_name} A1 GPs: {len(a1_gps)}, A1 CFs: {len(a1_cfs)}")

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

    reference = _build_reference_block(lang)

    prompt = f"""You are an expert {lang_name} language curriculum designer.

Below are ALL A1-level communicative functions (CFs) and grammar points (GPs) from the CEFR {lang_name} curriculum.

COMMUNICATIVE FUNCTIONS ({len(a1_cfs)} items):
{chr(10).join(cf_lines)}

GRAMMAR POINTS ({len(a1_gps)} items):
{chr(10).join(gp_lines)}
{reference}
{_language_prompt(lang, lang_name)}
Cluster these into 20-24 real-world SCENARIOS for A1 {lang_name} learners.
Each scenario is a concrete, everyday situation.

Rules:
- Assign each scenario to a phase (1, 2, or 3). Phase 1 = survival basics done first,
  phase 2 = daily life, phase 3 = more abstract/complex. Aim for ~8 scenarios per phase.
- Each scenario maps to 4-8 CF codes and 4-8 GP codes naturally exercised in that situation
- CFs and GPs CAN appear in multiple scenarios (real life overlaps)
- EVERY CF code and EVERY GP code must appear in at least one scenario — no orphans
- Only use codes from the lists above — do not invent new codes
- Each scenario has 3 depth levels: 1=introduction, 2=developing, 3=consolidating
- Descriptions in English

Output ONLY valid YAML matching this exact structure (no markdown fences):
scenarios:
  - slug: example-slug
    label: "Example Label"
    description: "English description of the scenario"
    cefr_level: A1
    phase: 1
    cf_codes:
      - code_1
      - code_2
    gp_codes:
      - code_1
      - code_2
    depths:
      - "Depth 1: basic introduction to the situation"
      - "Depth 2: developing competence, more variety"
      - "Depth 3: consolidating, handling complications"

Output ALL scenarios now."""

    client = get_client()
    client = client.with_options(
        timeout=httpx.Timeout(300.0, connect=10.0),
    )
    logger.info(f"Calling Claude to generate {lang_name} A1 scenario bank...")
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

    if not orphan_gps and not orphan_cfs and not invalid_gps and not invalid_cfs:
        logger.info("Full coverage: all GPs and CFs assigned, no invalid codes")

    output = data_dir(lang) / "scenarios_a1.yaml"
    with open(output, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, width=200)
    logger.info(f"Written to {output}")


if __name__ == "__main__":
    main()
