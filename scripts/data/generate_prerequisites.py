"""Generate grammar prerequisite DAG via LLM and write into grammar_points.yaml.

Usage:
  uv run python scripts/data/generate_prerequisites.py --lang it
  uv run python scripts/data/generate_prerequisites.py --lang de --level A1

Loads grammar point codes and labels for the requested language (and
optionally a single CEFR level), sends them to Claude asking for
prerequisite relationships, and writes the `prerequisites` field back
into each grammar point entry in grammar_points.yaml for hand-review.

When --level is given, only GPs at that level are assigned prerequisites,
but GPs from all *lower* levels are included as valid prerequisite targets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic
import yaml

from _shared import CEFR_ORDER, LANGUAGE_NAMES, write_gp_yaml

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"


def _gp_path(lang: str) -> Path:
    return DATA_ROOT / lang / "grammar_points.yaml"


def _load_grammar_points(
    all_gps: list[dict], level: str | None
) -> tuple[list[dict], list[dict]]:
    """Return (targets, valid_prereq_pool).

    targets:  GPs that will be assigned prerequisites (filtered by --level, or all non-A0).
    pool:     GPs that may appear as prerequisite values (targets + all lower-level GPs).
    """
    if level:
        level_idx = CEFR_ORDER.index(level)
        lower_levels = set(CEFR_ORDER[:level_idx])
        targets = [
            {"code": gp["code"], "label": gp.get("label", gp["code"])}
            for gp in all_gps
            if gp.get("cefr_level") == level
        ]
        pool_extra = [
            {"code": gp["code"], "label": gp.get("label", gp["code"])}
            for gp in all_gps
            if gp.get("cefr_level") in lower_levels
        ]
        return targets, targets + pool_extra
    else:
        # All non-A0 GPs
        gps = [
            {"code": gp["code"], "label": gp.get("label", gp["code"])}
            for gp in all_gps
            if gp.get("cefr_level", "A0") != "A0"
        ]
        return gps, gps


def _build_prompt(
    targets: list[dict],
    pool: list[dict],
    language_name: str,
    level: str | None,
) -> str:
    level_desc = f"{level}-level" if level else "all"

    pool_list = "\n".join(f"- {gp['code']}: {gp['label']}" for gp in pool)
    target_codes = {gp["code"] for gp in targets}
    target_list = "\n".join(
        f"- {gp['code']}: {gp['label']}" for gp in pool if gp["code"] in target_codes
    )

    # If targeting a single level with lower-level prereqs available, explain both lists
    if level and len(pool) > len(targets):
        pool_section = f"""Below are ALL grammar points that may serve as prerequisites (from levels below {level}
and from {level} itself):

{pool_list}

The grammar points you must assign prerequisites FOR are only the {level} ones:

{target_list}"""
    else:
        pool_section = f"""Below is a list of {level_desc} grammar points (code: label) for a {language_name} language course.

{pool_list}"""

    return f"""You are an expert {language_name} language curriculum designer.

{pool_section}

For each {level or ""} grammar point in the target list, identify which OTHER grammar points
from the full list are direct prerequisites — i.e., concepts a student MUST understand
before they can meaningfully learn this grammar point.

Rules:
- Only list DIRECT prerequisites, not transitive ones.
- A grammar point may have 0, 1, or 2 prerequisites. Most will have 0-1.
- Prerequisites must come from the full list above (use exact codes).
- Think about what grammatical knowledge is truly required, not just thematic similarity.
- For example, possessive adjectives require knowing articles and noun gender/number.
- Basic concepts like subject pronouns and present tense conjugation have no prerequisites.

Return ONLY valid YAML in this exact format (no markdown fences):

prerequisites:
  code_that_has_prereqs:
    - prerequisite_code_1
    - prerequisite_code_2
  another_code:
    - its_prerequisite

Only include grammar points that HAVE prerequisites. Omit codes with no prerequisites."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate grammar prerequisite DAG via LLM."
    )
    parser.add_argument(
        "--lang",
        required=True,
        choices=sorted(LANGUAGE_NAMES),
        help="Target language ISO code (e.g. it, de)",
    )
    parser.add_argument(
        "--level",
        default=None,
        choices=CEFR_ORDER,
        help="CEFR level to generate prerequisites for (default: all non-A0 levels)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    lang: str = args.lang
    level: str | None = args.level
    language_name = LANGUAGE_NAMES[lang]
    gp_path = _gp_path(lang)

    if not gp_path.exists():
        print(f"Grammar points file not found: {gp_path}")
        sys.exit(1)

    with open(gp_path) as f:
        all_gps = yaml.safe_load(f)

    targets, pool = _load_grammar_points(all_gps, level)
    if not targets:
        level_desc = f"{level} " if level else ""
        print(f"No {level_desc}grammar points found in {gp_path}")
        sys.exit(1)

    level_desc = f" {level}" if level else ""
    print(
        f"Found {len(targets)}{level_desc} {language_name} grammar points "
        f"({len(pool)} in prerequisite pool). Sending to Claude..."
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": _build_prompt(targets, pool, language_name, level),
            }
        ],
    )
    raw = response.content[0].text.strip()

    # Parse and validate
    try:
        result = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        print(f"Failed to parse LLM output as YAML:\n{raw}\n\nError: {e}")
        sys.exit(1)

    prereqs = result.get("prerequisites", {})
    valid_codes = {gp["code"] for gp in pool}
    target_codes = {gp["code"] for gp in targets}

    # Validate all codes exist
    warnings = []
    for code, deps in prereqs.items():
        if code not in target_codes:
            warnings.append(f"  WARNING: key '{code}' not in target grammar points")
        for dep in deps:
            if dep not in valid_codes:
                warnings.append(
                    f"  WARNING: dep '{dep}' (for '{code}') not in grammar points"
                )

    if warnings:
        print("\nValidation warnings:")
        for w in warnings:
            print(w)

    # Write prerequisites back into grammar_points.yaml
    with open(gp_path) as f:
        all_gps = yaml.safe_load(f)

    targeted_levels = {level} if level else set(CEFR_ORDER) - {"A0"}

    updated = 0
    for gp in all_gps:
        code = gp["code"]
        if code in prereqs:
            gp["prerequisites"] = prereqs[code]
            updated += 1
        elif gp.get("cefr_level") in targeted_levels:
            # Clear prerequisites for targeted GPs not in the DAG
            gp.pop("prerequisites", None)

    write_gp_yaml(gp_path, all_gps)

    print(f"\nUpdated {updated} grammar points with prerequisites in {gp_path}")
    print("Please review the file before committing.")


if __name__ == "__main__":
    main()
