#!/usr/bin/env python3
"""Print a coverage matrix: GP code × activity type for A0 lessons.

Parses a0_lessons.yaml, scenarios_a0.yaml, and grammar_points.yaml.
Outputs a table showing how each GP code is exercised across activity types.

Usage: uv run python scripts/a0_coverage.py
"""

from collections import defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LESSONS_YAML = REPO_ROOT / "src/maestro/data/it/a0_lessons.yaml"
SCENARIOS_YAML = REPO_ROOT / "src/maestro/data/it/scenarios_a0.yaml"
GRAMMAR_POINTS_YAML = REPO_ROOT / "src/maestro/data/it/grammar_points.yaml"

COLUMNS = [
    "grammar",
    "drill-primary",
    "drill-review",
    "reading",
    "listening",
    "writing",
    "speaking",
    "scenario",
]


def main() -> None:
    with open(LESSONS_YAML) as f:
        lessons = yaml.safe_load(f)
    with open(SCENARIOS_YAML) as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(GRAMMAR_POINTS_YAML) as f:
        gps = yaml.safe_load(f)

    # Build set of A0 GP codes
    a0_gp_codes = set()
    for s in scenarios:
        a0_gp_codes.update(s.get("gp_codes", []))

    gp_labels = {gp["code"]: gp["label"] for gp in gps}

    # coverage[gp_code][column] = count
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for slug, lesson_data in lessons.items():
        for act in lesson_data.get("activities", []):
            act_type = act.get("type")

            if act_type == "grammar":
                code = act.get("grammar_point_code")
                if code:
                    coverage[code]["grammar"] += 1

            elif act_type == "drill":
                drill_gp = act.get("grammar_point_code", "")
                items = act.get("items", [])
                for item in items:
                    item_gp = item.get("grammar_point_code") or drill_gp
                    if item_gp:
                        # Primary = item GP matches drill GP or has no override
                        # Review = item has explicit GP different from drill
                        if (
                            item.get("grammar_point_code")
                            and item["grammar_point_code"] != drill_gp
                        ):
                            coverage[item_gp]["drill-review"] += 1
                        else:
                            coverage[item_gp]["drill-primary"] += 1

            elif act_type in ("reading", "listening"):
                col = act_type
                for q in act.get("questions", []):
                    if isinstance(q, dict):
                        for gp in q.get("grammar_point_codes", []):
                            coverage[gp][col] += 1

            elif act_type == "writing":
                for gp in act.get("grammar_point_codes", []):
                    coverage[gp]["writing"] += 1

            elif act_type == "speaking":
                for gp in act.get("grammar_point_codes", []):
                    coverage[gp]["speaking"] += 1

    # Scenario-level GP mapping
    for s in scenarios:
        for gp in s.get("gp_codes", []):
            coverage[gp]["scenario"] += 1

    # Print table
    all_codes = sorted(a0_gp_codes | set(coverage.keys()))
    header = f"{'GP code':<16} {'label':<24} " + " ".join(f"{c:>13}" for c in COLUMNS)
    print(header)
    print("-" * len(header))
    for code in all_codes:
        label = gp_labels.get(code, "?")[:23]
        row = coverage[code]
        vals = " ".join(f"{row.get(c, 0):>13}" for c in COLUMNS)
        print(f"{code:<16} {label:<24} {vals}")

    # Summary
    print()
    total_gps = len(all_codes)
    covered = sum(
        1 for c in all_codes if any(coverage[c].get(col, 0) > 0 for col in COLUMNS[:7])
    )
    print(f"Total GP codes: {total_gps}, covered in lessons: {covered}")

    # Flag any GP codes with zero lesson coverage
    uncovered = [
        c
        for c in all_codes
        if not any(coverage[c].get(col, 0) > 0 for col in COLUMNS[:7])
    ]
    if uncovered:
        print(f"\nGP codes with NO lesson coverage: {', '.join(uncovered)}")


if __name__ == "__main__":
    main()
