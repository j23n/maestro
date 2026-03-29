#!/usr/bin/env python3
"""Recompute grammar_points.lock after modifying grammar_points.yaml.

The lock file stores the SHA256 hash of grammar_points.yaml and is committed to the repo.
At app startup, gp_sync compares this hash against what's stored in the database and
re-runs ingest if they differ — ensuring the DB always matches the committed YAML.

Usage:
  uv run python scripts/update_gp_lock.py             # Italian (default)
  uv run python scripts/update_gp_lock.py --language de
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _data_dir(language: str) -> Path:
    return REPO_ROOT / "data" / language


CEFR_ORDER = ["A0", "A1", "A2", "B1", "B2"]


def compute_lock(data: list, sha: str) -> dict:
    # Per-level counts: {level: {lang: count}}
    by_level: dict[str, dict[str, int]] = {}
    for gp in data:
        level = gp.get("cefr_level", "?")
        counts = by_level.setdefault(level, {})
        for lang in gp.get("explanations", {}):
            counts[lang] = counts.get(lang, 0) + 1
    return {
        "sha256": sha,
        "gp_count": len(data),
        "explanations_by_level": by_level,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _format_level_summary(by_level: dict[str, dict[str, int]], data: list) -> list[str]:
    """Return lines like  A1  en=59/59  it=0/59"""
    gp_counts: dict[str, int] = {}
    for gp in data:
        level = gp.get("cefr_level", "?")
        gp_counts[level] = gp_counts.get(level, 0) + 1

    lines = []
    levels = [lvl for lvl in CEFR_ORDER if lvl in gp_counts] + sorted(
        lvl for lvl in gp_counts if lvl not in CEFR_ORDER
    )
    for level in levels:
        total = gp_counts[level]
        counts = by_level.get(level, {})
        en = counts.get("en", 0)
        it = counts.get("it", 0)
        lines.append(f"    {level}  en={en}/{total}  it={it}/{total}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Update grammar_points.lock")
    parser.add_argument("--language", default="it", help="Language code (default: it)")
    args = parser.parse_args()

    data_dir = _data_dir(args.language)
    gp_yaml = data_dir / "grammar_points.yaml"
    lock_file = data_dir / "grammar_points.lock"

    if not gp_yaml.exists():
        print(f"ERROR: {gp_yaml} not found", file=sys.stderr)
        sys.exit(1)

    content = gp_yaml.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    data = yaml.safe_load(content)

    old_sha = None
    if lock_file.exists():
        try:
            old_sha = json.loads(lock_file.read_text())["sha256"]
        except Exception:
            pass

    lock = compute_lock(data, sha)
    lock_file.write_text(json.dumps(lock, indent=2) + "\n")

    if old_sha is None:
        print(f"  + grammar_points.lock: created (gps={lock['gp_count']})")
    elif old_sha != sha:
        print(f"  ~ grammar_points.yaml: hash changed (gps={lock['gp_count']})")
    else:
        print(f"  . grammar_points.yaml: unchanged (hash={sha[:16]})")

    for line in _format_level_summary(lock["explanations_by_level"], data):
        print(line)

    print(f"\nLock file written: {lock_file}")


if __name__ == "__main__":
    main()
