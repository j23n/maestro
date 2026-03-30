#!/usr/bin/env python3
"""Recompute vocab_a0.lock for all languages that have vocab_a0.yaml.

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
DATA_DIR = REPO_ROOT / "data"


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


def process_language(lang_dir: Path) -> None:
    vocab_yaml = lang_dir / "vocab_a0.yaml"
    lock_file = lang_dir / "vocab_a0.lock"
    lang = lang_dir.name

    content = vocab_yaml.read_bytes()
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
        print(f"  [{lang}] + vocab_a0.lock: created (words={lock['word_count']})")
    elif old_sha != sha:
        print(f"  [{lang}] ~ vocab_a0.yaml: hash changed (words={lock['word_count']})")
    else:
        print(f"  [{lang}] . vocab_a0.yaml: unchanged (hash={sha[:16]})")

    for pos, count in lock["by_part_of_speech"].items():
        print(f"    {pos}: {count}")


def main() -> None:
    vocab_files = sorted(DATA_DIR.glob("*/vocab_a0.yaml"))
    if not vocab_files:
        print("ERROR: no vocab_a0.yaml found in data/*/", file=sys.stderr)
        sys.exit(1)

    for vocab_yaml in vocab_files:
        process_language(vocab_yaml.parent)


if __name__ == "__main__":
    main()
