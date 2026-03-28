#!/usr/bin/env python3
"""Recompute data/it/a0_lessons.lock after modifying a0_lessons.yaml or scenarios_a0.yaml.

The lock file stores a combined SHA256 hash of both files (they must stay in sync)
and is committed to the repo. At app startup, a0_lessons_sync compares this hash
against what's stored in the database and re-runs scenario ingest if they differ —
ensuring the DB always matches the committed YAML.

It also validates that every scenario slug in scenarios_a0.yaml has a matching
top-level key in a0_lessons.yaml (the exact bug this lock prevents).

Usage: uv run python scripts/update_a0_lessons_lock.py
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LESSONS_YAML = REPO_ROOT / "data/it/a0_lessons.yaml"
SCENARIOS_YAML = REPO_ROOT / "data/it/scenarios_a0.yaml"
LOCK_FILE = REPO_ROOT / "data/it/a0_lessons.lock"

# Bump this to force a re-sync even when source files haven't changed
# (e.g. to regenerate audio after a TTS fix).
LOCK_VERSION = 3


def combined_sha(lessons_bytes: bytes, scenarios_bytes: bytes) -> str:
    h = hashlib.sha256()
    h.update(f"v{LOCK_VERSION}:".encode())
    h.update(lessons_bytes)
    h.update(scenarios_bytes)
    return h.hexdigest()


def validate_slugs(lessons_data: dict, scenarios_data: dict) -> list[str]:
    """Return list of scenario slugs that have no matching key in a0_lessons.yaml."""
    lesson_keys = set(lessons_data.keys())
    scenario_slugs = [s["slug"] for s in scenarios_data.get("scenarios", [])]
    return [slug for slug in scenario_slugs if slug not in lesson_keys]


def compute_lock(lessons_data: dict, scenarios_data: dict, sha: str) -> dict:
    scenario_slugs = [s["slug"] for s in scenarios_data.get("scenarios", [])]
    activity_counts = {}
    for key, lesson in lessons_data.items():
        activity_counts[key] = len(lesson.get("activities", []))
    return {
        "sha256": sha,
        "lesson_count": len(lessons_data),
        "scenario_count": len(scenario_slugs),
        "activities_per_lesson": activity_counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    for path, name in [
        (LESSONS_YAML, "a0_lessons.yaml"),
        (SCENARIOS_YAML, "scenarios_a0.yaml"),
    ]:
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    lessons_bytes = LESSONS_YAML.read_bytes()
    scenarios_bytes = SCENARIOS_YAML.read_bytes()
    sha = combined_sha(lessons_bytes, scenarios_bytes)

    lessons_data = yaml.safe_load(lessons_bytes)
    scenarios_data = yaml.safe_load(scenarios_bytes)

    # Validate slug alignment
    missing = validate_slugs(lessons_data, scenarios_data)
    if missing:
        print(
            "ERROR: scenario slugs with no matching lesson key in a0_lessons.yaml:",
            file=sys.stderr,
        )
        for slug in missing:
            print(f"  - {slug}", file=sys.stderr)
        sys.exit(1)

    old_sha = None
    if LOCK_FILE.exists():
        try:
            old_sha = json.loads(LOCK_FILE.read_text())["sha256"]
        except Exception:
            pass

    lock = compute_lock(lessons_data, scenarios_data, sha)
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n")

    if old_sha is None:
        print(
            f"  + a0_lessons.lock: created (lessons={lock['lesson_count']}, scenarios={lock['scenario_count']})"
        )
    elif old_sha != sha:
        print(
            f"  ~ a0_lessons: hash changed (lessons={lock['lesson_count']}, scenarios={lock['scenario_count']})"
        )
    else:
        print(f"  . a0_lessons: unchanged (hash={sha[:16]})")

    for key, count in lock["activities_per_lesson"].items():
        print(f"    {key}: {count} activities")

    print(f"\nLock file written: {LOCK_FILE}")


if __name__ == "__main__":
    main()
