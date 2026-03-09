#!/usr/bin/env python3
"""Compare eval results across prompt versions.

Each row in results.jsonl represents one eval run: prompt file, version,
timestamp, and metrics (precision/recall/accuracy/etc.).

Usage:
    python evals/compare.py                        # all prompts, all history
    python evals/compare.py --prompt analyzer      # filter by prompt file name
    python evals/compare.py --last 5               # last N runs per prompt+version
    python evals/compare.py --prompt analyzer --last 3
    python evals/compare.py --model claude-sonnet-4-6
    python evals/compare.py --subtest scoring
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "results.jsonl"

METRIC_COLS = [
    "precision",
    "recall",
    "fp_rate",
    "accuracy",
    "output_syntax",
    "content_quality",
    "agreement",
    "n",
    "test",
]

# Metrics where "worse" means higher (not lower)
_HIGHER_IS_WORSE = {"fp_rate"}


def load_results(
    prompt_filter: str | None = None,
    model_filter: str | None = None,
    subtest_filter: str | None = None,
) -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    rows = []
    for line in RESULTS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if prompt_filter and row.get("prompt") != prompt_filter:
            continue
        if model_filter and row.get("model") != model_filter:
            continue
        if subtest_filter and row.get("subtest") != subtest_filter:
            continue
        rows.append(row)
    return rows


def _fmt(val) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.2%}" if val <= 1.0 else f"{val:.4f}"
    return str(val)


def _group_key(row: dict) -> tuple:
    """Build group key including model/subtest when present."""
    key = (row.get("prompt", "?"), row.get("version", "?"))
    model = row.get("model")
    subtest = row.get("subtest")
    if model is not None:
        key = key + (model,)
    if subtest is not None:
        key = key + (subtest,)
    return key


def _check_regression(
    prev_row: dict, curr_row: dict, present_metrics: list[str]
) -> list[str]:
    """Return list of regression warning strings comparing prev to curr."""
    warnings = []
    for metric in present_metrics:
        prev_val = prev_row.get(metric)
        curr_val = curr_row.get(metric)
        if not isinstance(prev_val, (int, float)) or not isinstance(
            curr_val, (int, float)
        ):
            continue
        if metric == "n":
            continue
        if metric in _HIGHER_IS_WORSE:
            if curr_val > prev_val:
                warnings.append(
                    f"  \u26a0 REGRESSION: {metric} {prev_val:.2%} \u2192 {curr_val:.2%}"
                )
        else:
            if curr_val < prev_val:
                warnings.append(
                    f"  \u26a0 REGRESSION: {metric} {prev_val:.2%} \u2192 {curr_val:.2%}"
                )
    return warnings


def print_table(rows: list[dict], last: int | None) -> None:
    if not rows:
        print("No results found.")
        return

    # Determine if any row has model/subtest fields
    has_model = any("model" in row for row in rows)
    has_subtest = any("subtest" in row for row in rows)

    # Group by extended key
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = _group_key(row)
        groups[key].append(row)

    # Determine which metric columns are present
    present_metrics = []
    for col in METRIC_COLS:
        if any(col in row for row in rows):
            present_metrics.append(col)

    # Build header columns
    header_cols = ["prompt", "version"]
    if has_model:
        header_cols.append("model")
    if has_subtest:
        header_cols.append("subtest")
    header_cols += ["ts"] + present_metrics

    col_widths = {c: len(c) for c in header_cols}

    all_display_rows: list[tuple[tuple, dict]] = []
    for key, group in sorted(groups.items()):
        group_sorted = sorted(group, key=lambda r: r.get("ts", ""))
        if last:
            group_sorted = group_sorted[-last:]
        for row in group_sorted:
            display: dict = {
                "prompt": row.get("prompt", "?"),
                "version": row.get("version", "?"),
                "ts": row.get("ts", "")[:19].replace("T", " "),
            }
            if has_model:
                display["model"] = row.get("model", "-") or "-"
            if has_subtest:
                display["subtest"] = row.get("subtest", "-") or "-"
            for col in present_metrics:
                display[col] = _fmt(row.get(col))
            all_display_rows.append((key, display))
            for c, v in display.items():
                col_widths[c] = max(col_widths[c], len(str(v)))

    # Print header
    sep = "  "
    header = sep.join(c.ljust(col_widths[c]) for c in header_cols)
    divider = sep.join("-" * col_widths[c] for c in header_cols)
    print(header)
    print(divider)

    prev_key = None
    # Track raw rows per group for regression comparison
    group_raw: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        group_raw[_group_key(row)].append(row)

    # Sort groups the same way and apply last filter for regression detection
    sorted_group_raw: dict[tuple, list[dict]] = {}
    for key, group in group_raw.items():
        group_sorted = sorted(group, key=lambda r: r.get("ts", ""))
        if last:
            group_sorted = group_sorted[-last:]
        sorted_group_raw[key] = group_sorted

    # Track which rows we've printed per group for regression detection
    printed_per_group: dict[tuple, list[dict]] = defaultdict(list)

    for key, display in all_display_rows:
        if prev_key and key != prev_key:
            # Regression check: compare last two printed raw rows of previous group
            prev_group_rows = printed_per_group[prev_key]
            if len(prev_group_rows) >= 2:
                reg_warnings = _check_regression(
                    prev_group_rows[-2], prev_group_rows[-1], present_metrics
                )
                for w in reg_warnings:
                    print(w)
            print()  # blank line between groups
        prev_key = key

        # Find the matching raw row for this display row
        raw_rows = sorted_group_raw.get(key, [])
        # Match by ts
        ts_val = display.get("ts", "")
        matching_raw = next(
            (r for r in raw_rows if r.get("ts", "")[:19].replace("T", " ") == ts_val),
            None,
        )
        if matching_raw:
            printed_per_group[key].append(matching_raw)

        print(
            sep.join(str(display.get(c, "-")).ljust(col_widths[c]) for c in header_cols)
        )

    # Regression check for the last group
    if prev_key:
        prev_group_rows = printed_per_group[prev_key]
        if len(prev_group_rows) >= 2:
            reg_warnings = _check_regression(
                prev_group_rows[-2], prev_group_rows[-1], present_metrics
            )
            for w in reg_warnings:
                print(w)

    print()
    print(f"Total runs: {len(all_display_rows)}  |  Results file: {RESULTS_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare eval results across prompt versions"
    )
    parser.add_argument("--prompt", help="Filter by prompt file name (e.g. analyzer)")
    parser.add_argument("--last", type=int, help="Show last N runs per prompt+version")
    parser.add_argument("--model", help="Filter by model name")
    parser.add_argument("--subtest", help="Filter by subtest name")
    args = parser.parse_args()

    rows = load_results(
        prompt_filter=args.prompt,
        model_filter=args.model,
        subtest_filter=args.subtest,
    )
    if not rows:
        msg = "No results"
        if args.prompt:
            msg += f" for prompt '{args.prompt}'"
        if args.model:
            msg += f" for model '{args.model}'"
        if args.subtest:
            msg += f" for subtest '{args.subtest}'"
        msg += ". Run eval tests first: uv run pytest -m llm_eval tests/eval/"
        print(msg)
        sys.exit(0)

    print_table(rows, last=args.last)


if __name__ == "__main__":
    main()
