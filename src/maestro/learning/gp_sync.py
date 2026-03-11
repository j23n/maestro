"""Grammar point data versioning: sync grammar_points.json → MongoDB on startup.

How it works:
  1. scripts/update_gp_lock.py writes grammar_points.lock (SHA256 of grammar_points.json)
     whenever the JSON changes. This file is committed to the repo.
  2. At app startup, sync_if_changed() reads the lock hash and compares it against
     the hash stored in the _data_versions collection in MongoDB.
  3. If the hashes differ (new deploy with updated JSON), a full ingest runs and
     the stored hash is updated.

This means grammar_points.json is the single source of truth: edit the JSON
(or run generate_explanations.py which edits it), update the lock, deploy —
the database catches up automatically on the next startup.
"""

import json
import logging
from pathlib import Path

from maestro.utils import data_dir, utcnow

logger = logging.getLogger(__name__)

_VERSIONS_COLL = "_data_versions"
_GP_KEY = "grammar_points"


def _read_lock_hash(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())["sha256"]
    except Exception:
        return None


async def sync_if_changed(db) -> None:
    """Compare grammar_points.lock against DB; run full GP ingest if hash differs."""
    lock_path = data_dir() / "grammar_points.lock"
    lock_sha = _read_lock_hash(lock_path)

    if lock_sha is None:
        logger.warning(
            "gp_sync: grammar_points.lock not found — "
            "run: uv run python scripts/update_gp_lock.py"
        )
        return

    doc = await db[_VERSIONS_COLL].find_one({"key": _GP_KEY})
    db_sha = doc["hash"] if doc else None

    if lock_sha == db_sha:
        logger.info("gp_sync: grammar_points up to date (%s)", lock_sha[:16])
        return

    logger.info(
        "gp_sync: hash changed (%s → %s), syncing grammar_points",
        (db_sha or "none")[:16],
        lock_sha[:16],
    )

    from maestro.learning.ingest import upsert_grammar_points

    grammar_points = await upsert_grammar_points()

    await db[_VERSIONS_COLL].update_one(
        {"key": _GP_KEY},
        {"$set": {"hash": lock_sha, "applied_at": utcnow()}},
        upsert=True,
    )
    logger.info("gp_sync: synced %d grammar points", len(grammar_points))
