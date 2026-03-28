#!/usr/bin/env python3
"""Recompute data/it/vocab_a0.lock after modifying vocab_a0.yaml.

The lock file stores the SHA256 hash of vocab_a0.yaml and is committed to the repo.
At app startup, vocab_sync compares this hash against what's stored in the database and
re-runs ingest if they differ — ensuring the DB always matches the committed YAML.

Usage: uv run python scripts/update_vocab_lock.py
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VOCAB_YAML = REPO_ROOT / "data/it/vocab_a0.yaml"
LOCK_FILE = REPO_ROOT / "data/it/vocab_a0.lock"


def compute_lock(data: list, sha: str) -> dict:
    # Count by part of speech
    by_pos: dict[str, int] = {}
    for item in data:
        pos = item.get("part_of_speech", "?")
        by_pos[pos] = by_pos.get(pos, 0) + 1
    return {
        "sha256": sha,
        "word_count": len(data),
        "by_part_of_speech": dict(sorted(by_pos.items())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    if not VOCAB_YAML.exists():
        print(f"ERROR: {VOCAB_YAML} not found", file=sys.stderr)
        sys.exit(1)

    content = VOCAB_YAML.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    data = yaml.safe_load(content)

    old_sha = None
    if LOCK_FILE.exists():
        try:
            old_sha = json.loads(LOCK_FILE.read_text())["sha256"]
        except Exception:
            pass

    lock = compute_lock(data, sha)
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n")

    if old_sha is None:
        print(f"  + vocab_a0.lock: created (words={lock['word_count']})")
    elif old_sha != sha:
        print(f"  ~ vocab_a0.yaml: hash changed (words={lock['word_count']})")
    else:
        print(f"  . vocab_a0.yaml: unchanged (hash={sha[:16]})")

    for pos, count in lock["by_part_of_speech"].items():
        print(f"    {pos}: {count}")

    print(f"\nLock file written: {LOCK_FILE}")


if __name__ == "__main__":
    main()
