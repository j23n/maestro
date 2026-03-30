#!/usr/bin/env python3
"""Print coverage matrices for A0 lessons: GP × activity type and CF × scenario.

Parses a0_lessons.yaml, scenarios_a0.yaml, grammar_points.yaml, and
comm_functions.json.

Usage:
  uv run python scripts/a0_coverage.py           # Italian (default)
  uv run python scripts/a0_coverage.py --lang de  # German
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

GP_COLUMNS = [
    "grammar",
    "drill-primary",
    "drill-review",
    "reading",
    "listening",
    "writing",
    "speaking",
    "scenario",
]

# Activity types that count as "lesson coverage" (excludes scenario-only)
GP_LESSON_COLS = GP_COLUMNS[:7]


def _collect_gp_coverage(
    lessons: dict, scenarios: list[dict]
) -> tuple[dict[str, dict[str, int]], set[str]]:
    """Build GP coverage[code][column] = count."""
    a0_gp_codes: set[str] = set()
    for s in scenarios:
        a0_gp_codes.update(s.get("gp_codes", []))

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
                for item in act.get("items", []):
                    item_gp = item.get("grammar_point_code") or drill_gp
                    if item_gp:
                        if (
                            item.get("grammar_point_code")
                            and item["grammar_point_code"] != drill_gp
                        ):
                            coverage[item_gp]["drill-review"] += 1
                        else:
                            coverage[item_gp]["drill-primary"] += 1

            elif act_type in ("reading", "listening"):
                for q in act.get("questions", []):
                    if isinstance(q, dict):
                        for gp in q.get("grammar_point_codes", []):
                            coverage[gp][act_type] += 1

            elif act_type == "writing":
                for gp in act.get("grammar_point_codes", []):
                    coverage[gp]["writing"] += 1

            elif act_type == "speaking":
                for gp in act.get("grammar_point_codes", []):
                    coverage[gp]["speaking"] += 1

    for s in scenarios:
        for gp in s.get("gp_codes", []):
            coverage[gp]["scenario"] += 1

    return coverage, a0_gp_codes


def _collect_cf_coverage(
    lessons: dict, scenarios: list[dict], cf_labels: dict[str, str]
) -> dict[str, dict[str, int]]:
    """Build CF coverage. Currently CFs are only at scenario level for A0."""
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Scenario-level: which CFs each scenario claims
    scenario_by_slug = {s["slug"]: s for s in scenarios}
    for s in scenarios:
        for cf in s.get("cf_codes", []):
            coverage[cf]["scenario"] += 1

    # Per-lesson: map lesson slug → scenario, then check if lesson activities
    # exercise the scenario's CFs. We infer coverage from activity GP tags and
    # the GP↔CF overlap defined in the scenario.
    # Also count activity types per lesson for the summary.
    for slug, lesson_data in lessons.items():
        scenario = scenario_by_slug.get(slug, {})
        scenario_cfs = set(scenario.get("cf_codes", []))
        acts = lesson_data.get("activities", [])

        # Count activity types that exercise language skills
        has_reading = any(a.get("type") == "reading" for a in acts)
        has_listening = any(a.get("type") == "listening" for a in acts)
        has_writing = any(a.get("type") == "writing" for a in acts)
        has_speaking = any(a.get("type") == "speaking" for a in acts)
        has_drill = any(a.get("type") == "drill" for a in acts)

        # If a lesson has these activity types, the scenario's CFs get credit
        for cf in scenario_cfs:
            if has_drill:
                coverage[cf]["drill"] += 1
            if has_reading:
                coverage[cf]["reading"] += 1
            if has_listening:
                coverage[cf]["listening"] += 1
            if has_writing:
                coverage[cf]["writing"] += 1
            if has_speaking:
                coverage[cf]["speaking"] += 1

    return coverage


def _print_gp_table(
    coverage: dict[str, dict[str, int]],
    a0_gp_codes: set[str],
    gp_labels: dict[str, str],
) -> None:
    """Print GP coverage matrix."""
    print("=" * 80)
    print("GRAMMAR POINT COVERAGE")
    print("=" * 80)
    all_codes = sorted(a0_gp_codes | set(coverage.keys()))
    header = f"{'GP code':<16} {'label':<24} " + " ".join(
        f"{c:>13}" for c in GP_COLUMNS
    )
    print(header)
    print("-" * len(header))
    for code in all_codes:
        label = gp_labels.get(code, "?")[:23]
        row = coverage[code]
        vals = " ".join(f"{row.get(c, 0):>13}" for c in GP_COLUMNS)
        print(f"{code:<16} {label:<24} {vals}")

    print()
    total_gps = len(all_codes)
    covered = sum(
        1
        for c in all_codes
        if any(coverage[c].get(col, 0) > 0 for col in GP_LESSON_COLS)
    )
    print(f"Total GP codes: {total_gps}, covered in lessons: {covered}")

    uncovered = [
        c
        for c in all_codes
        if not any(coverage[c].get(col, 0) > 0 for col in GP_LESSON_COLS)
    ]
    if uncovered:
        print(f"GP codes with NO lesson coverage: {', '.join(uncovered)}")

    # Flag GPs with thin coverage (only 1-2 activity types)
    thin = []
    for c in all_codes:
        types_hit = sum(1 for col in GP_LESSON_COLS if coverage[c].get(col, 0) > 0)
        if 1 <= types_hit <= 2:
            hit_cols = [col for col in GP_LESSON_COLS if coverage[c].get(col, 0) > 0]
            thin.append((c, hit_cols))
    if thin:
        print("\nGP codes with thin coverage (1-2 activity types only):")
        for code, cols in thin:
            print(f"  {code:<16} only in: {', '.join(cols)}")


def _print_cf_table(
    coverage: dict[str, dict[str, int]],
    cf_labels: dict[str, str],
    scenarios: list[dict],
) -> None:
    """Print CF coverage matrix."""
    cf_columns = ["scenario", "drill", "reading", "listening", "writing", "speaking"]
    cf_lesson_cols = cf_columns[1:]

    # Collect all A0 CF codes from scenarios
    a0_cf_codes: set[str] = set()
    for s in scenarios:
        a0_cf_codes.update(s.get("cf_codes", []))

    all_codes = sorted(a0_cf_codes)

    print()
    print("=" * 80)
    print("COMMUNICATIVE FUNCTION COVERAGE")
    print("=" * 80)
    header = f"{'CF code':<32} {'label':<24} " + " ".join(
        f"{c:>10}" for c in cf_columns
    )
    print(header)
    print("-" * len(header))
    for code in all_codes:
        label = cf_labels.get(code, "?")[:23]
        row = coverage[code]
        vals = " ".join(f"{row.get(c, 0):>10}" for c in cf_columns)
        print(f"{code:<32} {label:<24} {vals}")

    print()
    total_cfs = len(all_codes)
    covered = sum(
        1
        for c in all_codes
        if any(coverage[c].get(col, 0) > 0 for col in cf_lesson_cols)
    )
    print(f"Total A0 CF codes: {total_cfs}, covered in lessons: {covered}")

    # CFs only at scenario level with no lesson activities
    scenario_only = [
        c
        for c in all_codes
        if coverage[c].get("scenario", 0) > 0
        and not any(coverage[c].get(col, 0) > 0 for col in cf_lesson_cols)
    ]
    if scenario_only:
        print(
            f"CF codes with scenario refs but NO lesson coverage: {', '.join(scenario_only)}"
        )


def _print_per_lesson_summary(lessons: dict, scenarios: list[dict]) -> None:
    """Print a per-lesson activity count summary."""
    scenario_by_slug = {s["slug"]: s for s in scenarios}

    print()
    print("=" * 80)
    print("PER-LESSON SUMMARY")
    print("=" * 80)
    act_types = [
        "grammar",
        "drill",
        "reading",
        "listening",
        "writing",
        "speaking",
        "vocab_review",
        "info",
        "onboarding",
    ]
    header = (
        f"{'lesson':<28} {'#act':>4} "
        + " ".join(f"{t[:7]:>7}" for t in act_types)
        + "  GPs                    CFs"
    )
    print(header)
    print("-" * len(header))

    for slug, lesson_data in lessons.items():
        acts = lesson_data.get("activities", [])
        counts = defaultdict(int)
        for a in acts:
            counts[a.get("type", "?")] += 1

        scenario = scenario_by_slug.get(slug, {})
        gp_codes = scenario.get("gp_codes", [])
        cf_codes = scenario.get("cf_codes", [])

        seq = scenario.get("sequence", "?")
        label = scenario.get("label", slug)[:22]
        total = len(acts)
        vals = " ".join(f"{counts.get(t, 0):>7}" for t in act_types)
        gp_str = ",".join(gp_codes)[:24]
        cf_str = ",".join(c.replace("a0_", "") for c in cf_codes)[:30]
        print(f"{f'{seq:>2}. {label}':<28} {total:>4} {vals}  {gp_str:<24} {cf_str}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print A0 coverage matrices")
    parser.add_argument(
        "--lang",
        default="it",
        help="Language code (default: it)",
    )
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data" / args.lang
    with open(data_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)
    with open(data_dir / "scenarios_a0.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(data_dir / "grammar_points.yaml") as f:
        gps = yaml.safe_load(f)
    with open(data_dir / "comm_functions.json") as f:
        cfs = json.load(f)

    gp_labels = {gp["code"]: gp["label"] for gp in gps}
    cf_labels = {cf["code"]: cf["label"] for cf in cfs}

    print(f"Language: {args.lang}")

    # GP coverage
    gp_coverage, a0_gp_codes = _collect_gp_coverage(lessons, scenarios)
    _print_gp_table(gp_coverage, a0_gp_codes, gp_labels)

    # CF coverage
    cf_coverage = _collect_cf_coverage(lessons, scenarios, cf_labels)
    _print_cf_table(cf_coverage, cf_labels, scenarios)

    # Per-lesson summary
    _print_per_lesson_summary(lessons, scenarios)


if __name__ == "__main__":
    main()
