"""Check completeness of GP and CF explanation fields.

Reads grammar_points.yaml and comm_functions.json for each language and
reports which items are missing explanation sub-fields (title, tip,
why_this_matters, explanation).

Usage:
  uv run python scripts/data/check_completeness.py --lang de
  uv run python scripts/data/check_completeness.py --lang it --type gp --level A1
  uv run python scripts/data/check_completeness.py          # all langs, A0+A1
"""

from __future__ import annotations

import argparse
import json

import yaml

from maestro.utils import data_dir, iter_language_dirs

_EXPLANATION_SUBFIELDS = ("title", "tip", "why_this_matters", "explanation")
_DEFAULT_LEVELS = ["A0", "A1"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_gps(lang: str) -> list[dict]:
    path = data_dir(lang) / "grammar_points.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        return yaml.safe_load(f) or []


def _load_cfs(lang: str) -> list[dict]:
    path = data_dir(lang) / "comm_functions.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _check_item(item: dict, kind: str) -> dict:
    """Return a report dict for a single GP or CF."""
    code = item.get("code", "?")
    level = item.get("cefr_level", "?")
    missing_top: list[str] = []
    missing_expl: dict[str, list[str]] = {}

    # Top-level fields
    if not item.get("description"):
        missing_top.append("description")
    if not item.get("examples"):
        missing_top.append("examples")
    if kind == "gp" and not item.get("subcategory"):
        missing_top.append("subcategory")

    # Explanation sub-fields (A0 skips explanations by design)
    if level != "A0":
        explanations = item.get("explanations") or {}
        if not explanations:
            missing_expl["*"] = ["no explanations at all"]
        else:
            for lang, expl in explanations.items():
                gaps = []
                for field in _EXPLANATION_SUBFIELDS:
                    if not expl.get(field):
                        gaps.append(field)
                if gaps:
                    missing_expl[lang] = gaps

    return {
        "code": code,
        "level": level,
        "missing_top": missing_top,
        "missing_expl": missing_expl,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_report(
    items: list[dict],
    kind: str,
    lang: str,
    levels: list[str] | None,
) -> int:
    """Print per-item report, return count of items with issues."""
    filtered = items
    if levels:
        filtered = [i for i in items if i.get("cefr_level") in levels]
    if not filtered:
        return 0

    label = "Grammar Points" if kind == "gp" else "Communicative Functions"
    print(f"\n{'=' * 60}")
    print(f"  {label}  [{lang}]  ({len(filtered)} items)")
    print(f"{'=' * 60}")

    reports = [_check_item(item, kind) for item in filtered]
    issues = [r for r in reports if r["missing_top"] or r["missing_expl"]]
    complete = len(reports) - len(issues)

    # Summary counters
    no_tip = sum(
        1 for r in reports if any("tip" in gaps for gaps in r["missing_expl"].values())
    )
    no_wtm = sum(
        1
        for r in reports
        if any("why_this_matters" in gaps for gaps in r["missing_expl"].values())
    )
    no_expl_at_all = sum(1 for r in reports if "*" in r["missing_expl"])
    non_a0 = sum(1 for item in filtered if item.get("cefr_level") != "A0")

    print(f"\n  {complete}/{len(reports)} fully complete")
    if non_a0:
        print(f"  {no_expl_at_all}/{non_a0} non-A0 items missing all explanations")
        print(f"  {no_tip}/{non_a0} non-A0 items missing tip")
        print(f"  {no_wtm}/{non_a0} non-A0 items missing why_this_matters")

    if not issues:
        print("  All items complete!")
        return 0

    print()
    for r in issues:
        parts = []
        if r["missing_top"]:
            parts.append(f"top: {', '.join(r['missing_top'])}")
        for expl_lang, gaps in r["missing_expl"].items():
            parts.append(f"expl[{expl_lang}]: {', '.join(gaps)}")
        suffix = "  |  ".join(parts)
        print(f"  [ ] {r['code']:35s} {r['level']:4s}  {suffix}")

    return len(issues)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Check GP/CF data completeness")
    parser.add_argument("--lang", help="Language code (e.g. de, it). Default: all")
    parser.add_argument(
        "--type",
        choices=["gp", "cf"],
        help="Only check grammar points or comm functions",
    )
    parser.add_argument(
        "--level",
        action="append",
        help="CEFR level(s) to check (repeatable). Default: A0, A1",
    )
    args = parser.parse_args()

    levels = args.level or _DEFAULT_LEVELS

    # Discover languages
    if args.lang:
        langs = [args.lang]
    else:
        langs = [d.name for d in iter_language_dirs()]

    total_issues = 0
    for lang in langs:
        if not args.type or args.type == "gp":
            gps = _load_gps(lang)
            total_issues += _print_report(gps, "gp", lang, levels)

        if not args.type or args.type == "cf":
            cfs = _load_cfs(lang)
            total_issues += _print_report(cfs, "cf", lang, levels)

    print(f"\n{'─' * 60}")
    if total_issues:
        print(f"  {total_issues} item(s) with gaps")
    else:
        print("  All checked items are complete!")
    print()


if __name__ == "__main__":
    main()
