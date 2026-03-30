#!/usr/bin/env python3
"""Recompute comm_functions.lock after modifying comm_functions.json.

The lock file stores the SHA256 hash of comm_functions.json and is committed to the repo.
At app startup, cf_sync compares this hash against what's stored in the database and
re-runs ingest if they differ — ensuring the DB always matches the committed JSON.

Usage:
  uv run python scripts/update_cf_lock.py             # Italian (default)
  uv run python scripts/update_cf_lock.py --language de
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _data_dir(language: str) -> Path:
    return REPO_ROOT / "data" / language


def compute_lock(data: list, sha: str) -> dict:
    by_level: dict[str, int] = {}
    for item in data:
        level = item.get("cefr_level", "?")
        by_level[level] = by_level.get(level, 0) + 1
    return {
        "sha256": sha,
        "cf_count": len(data),
        "by_cefr_level": dict(sorted(by_level.items())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Update comm_functions.lock")
    parser.add_argument("--language", default="it", help="Language code (default: it)")
    args = parser.parse_args()

    data_dir = _data_dir(args.language)
    cf_json = data_dir / "comm_functions.json"
    lock_file = data_dir / "comm_functions.lock"

    if not cf_json.exists():
        print(f"ERROR: {cf_json} not found", file=sys.stderr)
        sys.exit(1)

    content = cf_json.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    data = json.loads(content)

    old_sha = None
    if lock_file.exists():
        try:
            old_sha = json.loads(lock_file.read_text())["sha256"]
        except Exception:
            pass

    lock = compute_lock(data, sha)
    lock_file.write_text(json.dumps(lock, indent=2) + "\n")

    if old_sha is None:
        print(f"  + comm_functions.lock: created (cfs={lock['cf_count']})")
    elif old_sha != sha:
        print(f"  ~ comm_functions.json: hash changed (cfs={lock['cf_count']})")
    else:
        print(f"  . comm_functions.json: unchanged (hash={sha[:16]})")

    for level, count in lock["by_cefr_level"].items():
        print(f"    {level}: {count}")

    print(f"\nLock file written: {lock_file}")


if __name__ == "__main__":
    main()
