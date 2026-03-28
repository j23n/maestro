"""A0 lesson + scenario data versioning: sync on startup when files change.

How it works:
  1. scripts/update_a0_lessons_lock.py writes a0_lessons.lock (combined SHA256 of
     a0_lessons.yaml + scenarios_a0.yaml) whenever either file changes.
     This file is committed to the repo.
  2. At app startup, sync_if_changed() reads the lock hash and compares it against
     the hash stored in the _data_versions collection in MongoDB.
  3. If the hashes differ (new deploy with updated YAML), scenarios are re-ingested
     and the stored hash is updated.
  4. Before ingesting, slug alignment is validated: every scenario slug must have a
     matching key in a0_lessons.yaml, preventing the "empty activities" bug.

This means a0_lessons.yaml + scenarios_a0.yaml are the source of truth: edit them,
update the lock, deploy — the database catches up automatically on the next startup.
"""

import json
import logging
from pathlib import Path

import yaml

from maestro.utils import data_dir, utcnow

logger = logging.getLogger(__name__)

_VERSIONS_COLL = "_data_versions"
_A0_LESSONS_KEY = "a0_lessons"


def _read_lock_hash(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())["sha256"]
    except Exception:
        return None


def _validate_slug_alignment() -> list[str]:
    """Return scenario slugs that have no matching key in a0_lessons.yaml."""
    lessons_path = data_dir() / "a0_lessons.yaml"
    scenarios_path = data_dir() / "scenarios_a0.yaml"
    if not lessons_path.exists() or not scenarios_path.exists():
        return []
    with open(lessons_path) as f:
        lessons_data = yaml.safe_load(f)
    with open(scenarios_path) as f:
        scenarios_data = yaml.safe_load(f)
    lesson_keys = set(lessons_data.keys()) if lessons_data else set()
    scenario_slugs = [s["slug"] for s in (scenarios_data or {}).get("scenarios", [])]
    return [slug for slug in scenario_slugs if slug not in lesson_keys]


async def sync_if_changed(db) -> None:
    """Compare a0_lessons.lock against DB; re-ingest scenarios if hash differs."""
    lock_path = data_dir() / "a0_lessons.lock"
    lock_sha = _read_lock_hash(lock_path)

    if lock_sha is None:
        logger.warning(
            "a0_lessons_sync: a0_lessons.lock not found — "
            "run: uv run python scripts/update_a0_lessons_lock.py"
        )
        return

    doc = await db[_VERSIONS_COLL].find_one({"key": _A0_LESSONS_KEY})
    db_sha = doc["hash"] if doc else None

    if lock_sha == db_sha:
        logger.info("a0_lessons_sync: a0_lessons up to date (%s)", lock_sha[:16])
        return

    # Validate slug alignment before ingesting
    missing = _validate_slug_alignment()
    if missing:
        logger.error(
            "a0_lessons_sync: scenario slugs missing from a0_lessons.yaml: %s — "
            "fix the YAML files and re-run: uv run python scripts/update_a0_lessons_lock.py",
            missing,
        )
        return

    logger.info(
        "a0_lessons_sync: hash changed (%s → %s), syncing scenarios",
        (db_sha or "none")[:16],
        lock_sha[:16],
    )

    from maestro.sync.ingest import seed_scenarios

    await seed_scenarios()

    # Regenerate missing listening audio for updated lessons
    from maestro.tts import sync_a0_listening_audio

    await sync_a0_listening_audio()

    await db[_VERSIONS_COLL].update_one(
        {"key": _A0_LESSONS_KEY},
        {"$set": {"hash": lock_sha, "applied_at": utcnow()}},
        upsert=True,
    )
    logger.info("a0_lessons_sync: synced a0 lessons + scenarios")
