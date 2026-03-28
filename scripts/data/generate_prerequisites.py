"""Generate grammar prerequisite DAG via LLM and write into grammar_points.json.

Usage: uv run python scripts/data/generate_prerequisites.py

Loads all A1 grammar point codes and labels, sends them to Claude asking
for prerequisite relationships, and writes the `prerequisites` field back
into each grammar point entry in grammar_points.json for hand-review.
"""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic
import yaml


GP_PATH = Path(__file__).parent.parent / "data" / "it" / "grammar_points.yaml"


def _load_a1_grammar_points() -> list[dict]:
    """Load A1 grammar points from grammar_points.yaml."""
    with open(GP_PATH) as f:
        all_gps = yaml.safe_load(f)
    return [
        {"code": gp["code"], "label": gp.get("label", gp["code"])}
        for gp in all_gps
        if gp.get("cefr_level") == "A1"
    ]


def _build_prompt(gps: list[dict]) -> str:
    gp_list = "\n".join(f"- {gp['code']}: {gp['label']}" for gp in gps)
    return f"""You are an expert Italian language curriculum designer.

Below is a list of A1-level grammar points (code: label) for an Italian language course.

{gp_list}

For each grammar point, identify which OTHER grammar points from this list are
direct prerequisites — i.e., concepts a student MUST understand before they can
meaningfully learn this grammar point.

Rules:
- Only list DIRECT prerequisites, not transitive ones.
- A grammar point may have 0, 1, or 2 prerequisites. Most will have 0-1.
- Prerequisites must come from the list above (use exact codes).
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


def main() -> None:
    gps = _load_a1_grammar_points()
    if not gps:
        print("No A1 grammar points found in grammar_points.yaml")
        sys.exit(1)

    print(f"Found {len(gps)} A1 grammar points. Sending to Claude...")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": _build_prompt(gps)}],
    )
    raw = response.content[0].text.strip()

    # Parse and validate
    try:
        result = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        print(f"Failed to parse LLM output as YAML:\n{raw}\n\nError: {e}")
        sys.exit(1)

    prereqs = result.get("prerequisites", {})
    valid_codes = {gp["code"] for gp in gps}

    # Validate all codes exist
    warnings = []
    for code, deps in prereqs.items():
        if code not in valid_codes:
            warnings.append(f"  WARNING: key '{code}' not in grammar points")
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
    with open(GP_PATH) as f:
        all_gps = yaml.safe_load(f)

    updated = 0
    for gp in all_gps:
        code = gp["code"]
        if code in prereqs:
            gp["prerequisites"] = prereqs[code]
            updated += 1
        elif gp.get("cefr_level") == "A1":
            # Explicitly clear prerequisites for A1 GPs not in the DAG
            gp.pop("prerequisites", None)

    with open(GP_PATH, "w") as f:
        yaml.dump(
            all_gps, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    print(f"\nUpdated {updated} grammar points with prerequisites in {GP_PATH}")
    print("Please review the file before committing.")


if __name__ == "__main__":
    main()
