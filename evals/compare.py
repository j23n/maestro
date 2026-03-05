#!/usr/bin/env python3
"""Compare eval results across prompt versions.

Each row in results.jsonl represents one eval run: prompt file, version,
timestamp, and metrics (precision/recall/accuracy/etc.).

Usage:
    python evals/compare.py                        # all prompts, all history
    python evals/compare.py --prompt analyzer      # filter by prompt file name
    python evals/compare.py --last 5               # last N runs per prompt+version
    python evals/compare.py --prompt analyzer --last 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "results.jsonl"

METRIC_COLS = ["precision", "recall", "fp_rate", "accuracy", "output_syntax", "content_quality", "n", "test"]


def load_results(prompt_filter: str | None = None) -> list[dict]:
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
        rows.append(row)
    return rows


def _fmt(val) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.2%}" if val <= 1.0 else f"{val:.4f}"
    return str(val)


def print_table(rows: list[dict], last: int | None) -> None:
    if not rows:
        print("No results found.")
        return

    # Group by (prompt, version)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row.get("prompt", "?"), row.get("version", "?"))
        groups[key].append(row)

    # Determine which metric columns are present
    present_metrics = []
    for col in METRIC_COLS:
        if any(col in row for row in rows):
            present_metrics.append(col)

    header_cols = ["prompt", "version", "ts"] + present_metrics
    col_widths = {c: len(c) for c in header_cols}

    all_display_rows = []
    for (prompt, version), group in sorted(groups.items()):
        group_sorted = sorted(group, key=lambda r: r.get("ts", ""))
        if last:
            group_sorted = group_sorted[-last:]
        for row in group_sorted:
            display = {
                "prompt": prompt,
                "version": version,
                "ts": row.get("ts", "")[:19].replace("T", " "),
            }
            for col in present_metrics:
                display[col] = _fmt(row.get(col))
            all_display_rows.append(display)
            for c, v in display.items():
                col_widths[c] = max(col_widths[c], len(str(v)))

    # Print header
    sep = "  "
    header = sep.join(c.ljust(col_widths[c]) for c in header_cols)
    divider = sep.join("-" * col_widths[c] for c in header_cols)
    print(header)
    print(divider)

    prev_key = None
    for display in all_display_rows:
        key = (display["prompt"], display["version"])
        if prev_key and key != prev_key:
            print()  # blank line between groups
        prev_key = key
        print(sep.join(str(display.get(c, "-")).ljust(col_widths[c]) for c in header_cols))

    print()
    print(f"Total runs: {len(all_display_rows)}  |  Results file: {RESULTS_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare eval results across prompt versions")
    parser.add_argument("--prompt", help="Filter by prompt file name (e.g. analyzer)")
    parser.add_argument("--last", type=int, help="Show last N runs per prompt+version")
    args = parser.parse_args()

    rows = load_results(prompt_filter=args.prompt)
    if not rows:
        msg = f"No results"
        if args.prompt:
            msg += f" for prompt '{args.prompt}'"
        msg += f". Run eval tests first: uv run pytest -m llm_eval tests/eval/"
        print(msg)
        sys.exit(0)

    print_table(rows, last=args.last)


if __name__ == "__main__":
    main()
