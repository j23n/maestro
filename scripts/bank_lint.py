"""
Validate content bank files and report curriculum coverage.

Hard failures (exit 1): schema-invalid files, unknown GP/CF/scenario codes,
empty prompts/answers, depth keys outside the scenario's depth range.

Coverage gaps (missing scenarios, depths, drill pools, CF speaking prompts)
are warnings by default — the bank is allowed to be partial because the
planner falls back to LLM generation. Pass --strict to fail on gaps too:
once a level's bank is meant to be complete, wire --strict into CI so a
student can never hit a graduation gate the bank can't serve.

Run with:
  uv run python scripts/bank_lint.py --lang it --level A1 [--strict]
"""

import argparse
import json
import sys

import yaml

from maestro.lessons.bank import (
    BankDrillFile,
    BankScenarioFile,
    bank_dir,
)
from maestro.utils import data_dir

MIN_DRILL_ITEMS = 6  # one lesson's worth per GP (one drill activity)


def _load_curriculum(lang: str, level: str):
    with open(data_dir(lang) / f"scenarios_{level.lower()}.yaml") as f:
        scenarios = {s["slug"]: s for s in yaml.safe_load(f)["scenarios"]}
    with open(data_dir(lang) / "grammar_points.yaml") as f:
        gp_codes = {g["code"] for g in yaml.safe_load(f)}
    with open(data_dir(lang) / "comm_functions.json") as f:
        cf_codes = {c["code"] for c in json.load(f)}
    return scenarios, gp_codes, cf_codes


def lint(lang: str, level: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    scenarios, gp_codes, cf_codes = _load_curriculum(lang, level)
    root = bank_dir(lang, level)

    # --- Drill files ---
    drill_counts: dict[str, int] = {}
    for path in sorted((root / "drills").glob("*.yaml")):
        try:
            with open(path) as f:
                parsed = BankDrillFile.model_validate(yaml.safe_load(f))
        except Exception as exc:
            errors.append(f"{path.name}: invalid schema: {exc}")
            continue
        if parsed.grammar_point_code != path.stem:
            errors.append(
                f"{path.name}: grammar_point_code {parsed.grammar_point_code!r} "
                f"doesn't match filename"
            )
        if parsed.grammar_point_code not in gp_codes:
            errors.append(f"{path.name}: unknown GP code")
        for i, item in enumerate(parsed.items):
            if not item.prompt.strip() or not item.correct_answer.strip():
                errors.append(f"{path.name}: item {i} has empty prompt/answer")
        drill_counts[parsed.grammar_point_code] = len(parsed.items)

    # --- Text files ---
    text_files: dict[str, BankScenarioFile] = {}
    for path in sorted((root / "texts").glob("*.yaml")):
        try:
            with open(path) as f:
                parsed = BankScenarioFile.model_validate(yaml.safe_load(f))
        except Exception as exc:
            errors.append(f"{path.name}: invalid schema: {exc}")
            continue
        scenario = scenarios.get(parsed.scenario)
        if scenario is None:
            errors.append(f"{path.name}: unknown scenario {parsed.scenario!r}")
            continue
        text_files[parsed.scenario] = parsed
        max_depth = len(scenario.get("depths", []))
        for depth, content in parsed.depths.items():
            if not 1 <= depth <= max_depth:
                errors.append(
                    f"{path.name}: depth {depth} outside 1..{max_depth}"
                )
            for kind, texts in (
                ("listening", content.listenings),
                ("reading", content.readings),
            ):
                for i, t in enumerate(texts):
                    if not t.text.strip():
                        errors.append(f"{path.name}: empty {kind} {i} at depth {depth}")
                    for q in t.questions:
                        for code in q.grammar_point_codes:
                            if code not in gp_codes:
                                errors.append(
                                    f"{path.name}: question references unknown GP {code}"
                                )
            for i, w in enumerate(content.writings):
                if not w.prompt.strip():
                    errors.append(f"{path.name}: empty writing {i} at depth {depth}")
        scenario_cfs = set(scenario.get("cf_codes", []))
        for s in parsed.speakings:
            if s.cf_code not in cf_codes:
                errors.append(f"{path.name}: unknown CF code {s.cf_code}")
            elif s.cf_code not in scenario_cfs:
                warnings.append(
                    f"{path.name}: speaking CF {s.cf_code} not in scenario cf_codes"
                )
            if not s.prompt.strip():
                errors.append(f"{path.name}: empty speaking prompt ({s.cf_code})")

    # --- Coverage (a lesson needs texts at the depth, drills for every
    # scenario GP, and a speaking prompt for every scenario CF) ---
    for slug, scenario in scenarios.items():
        parsed = text_files.get(slug)
        if parsed is None:
            warnings.append(f"coverage: scenario {slug} has no text bank file")
            continue
        for depth in range(1, len(scenario.get("depths", [])) + 1):
            content = parsed.depths.get(depth)
            if content is None:
                warnings.append(f"coverage: {slug} missing depth {depth}")
                continue
            if not content.listenings:
                warnings.append(f"coverage: {slug} depth {depth} has no listenings")
            if not content.readings:
                warnings.append(f"coverage: {slug} depth {depth} has no readings")
            if not content.writings:
                warnings.append(f"coverage: {slug} depth {depth} has no writings")
        covered_cfs = {s.cf_code for s in parsed.speakings}
        for cf in scenario.get("cf_codes", []):
            if cf not in covered_cfs:
                warnings.append(f"coverage: {slug} missing speaking prompt for {cf}")
        for gp in scenario.get("gp_codes", []):
            if drill_counts.get(gp, 0) < MIN_DRILL_ITEMS:
                warnings.append(
                    f"coverage: {slug} GP {gp} has "
                    f"{drill_counts.get(gp, 0)}/{MIN_DRILL_ITEMS} drill items"
                )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Lint content bank files")
    parser.add_argument("--lang", required=True)
    parser.add_argument("--level", default="A1")
    parser.add_argument(
        "--strict", action="store_true", help="treat coverage warnings as errors"
    )
    args = parser.parse_args()

    errors, warnings = lint(args.lang, args.level.upper())
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    if errors or (args.strict and warnings):
        sys.exit(1)


if __name__ == "__main__":
    main()
