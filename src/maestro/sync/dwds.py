"""DWDS headwords data versioning: sync dwds_headwords.json → MongoDB on startup.

How it works:
  1. scripts/update_dwds_lock.py writes dwds_headwords.lock (SHA256 of dwds_headwords.json)
     whenever the JSON changes. This file is committed to the repo.
  2. At app startup, sync_if_changed() reads the lock hash and compares it against
     the hash stored in the _data_versions collection in MongoDB.
  3. If the hashes differ (new deploy with updated JSON), bare VocabularyWord documents
     are inserted for every headword and the stored hash is updated.

This means dwds_headwords.json is the single source of truth: update the file, update the
lock, deploy — the database catches up automatically on the next startup.
"""

import json
import logging
from pathlib import Path

from maestro.utils import data_dir, utcnow

logger = logging.getLogger(__name__)

_VERSIONS_COLL = "_data_versions"
_DWDS_KEY = "dwds_headwords"


def _read_lock_hash(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())["sha256"]
    except Exception:
        return None


async def sync_if_changed(db) -> None:
    """Compare dwds_headwords.lock against DB; run headword ingest if hash differs."""
    lock_path = data_dir("de") / "dwds_headwords.lock"
    lock_sha = _read_lock_hash(lock_path)

    if lock_sha is None:
        logger.warning(
            "dwds_sync: dwds_headwords.lock not found — "
            "run: uv run python scripts/update_dwds_lock.py"
        )
        return

    doc = await db[_VERSIONS_COLL].find_one({"key": _DWDS_KEY})
    db_sha = doc["hash"] if doc else None

    if lock_sha == db_sha:
        logger.info("dwds_sync: dwds_headwords up to date (%s)", lock_sha[:16])
        return

    logger.info(
        "dwds_sync: hash changed (%s → %s), syncing dwds_headwords",
        (db_sha or "none")[:16],
        lock_sha[:16],
    )

    from maestro.sync.ingest import seed_dwds_headwords

    await seed_dwds_headwords()

    await db[_VERSIONS_COLL].update_one(
        {"key": _DWDS_KEY},
        {"$set": {"hash": lock_sha, "applied_at": utcnow()}},
        upsert=True,
    )
    logger.info("dwds_sync: synced dwds_headwords")
