"""Communicative function data versioning: sync comm_functions.json → MongoDB on startup.

How it works:
  1. scripts/update_cf_lock.py writes comm_functions.lock (SHA256 of comm_functions.json)
     whenever the JSON changes. This file is committed to the repo.
  2. At app startup, sync_if_changed() reads the lock hash and compares it against
     the hash stored in the _data_versions collection in MongoDB.
  3. If the hashes differ (new deploy with updated JSON), a full ingest runs and
     the stored hash is updated.

This means comm_functions.json is the single source of truth: edit the JSON, update the
lock, deploy — the database catches up automatically on the next startup.
"""

import hashlib
import json
import logging
from pathlib import Path

from maestro.utils import DATA_DIR_ROOT, utcnow

logger = logging.getLogger(__name__)

_VERSIONS_COLL = "_data_versions"
_CF_KEY = "comm_functions"


def _read_lock_hash(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())["sha256"]
    except Exception:
        return None


def _combined_lock_hash() -> str | None:
    """Combine lock hashes from all language directories."""
    h = hashlib.sha256()
    found = False
    for lang_dir in sorted(DATA_DIR_ROOT.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name in ("seed", "images"):
            continue
        lock_sha = _read_lock_hash(lang_dir / "comm_functions.lock")
        if lock_sha:
            h.update(f"{lang_dir.name}:{lock_sha}".encode())
            found = True
    return h.hexdigest() if found else None


async def sync_if_changed(db) -> None:
    """Compare comm_functions.lock against DB; run full CF ingest if hash differs."""
    combined_sha = _combined_lock_hash()

    if combined_sha is None:
        logger.warning(
            "cf_sync: no comm_functions.lock found in any language dir — "
            "run: uv run python scripts/update_cf_lock.py"
        )
        return

    doc = await db[_VERSIONS_COLL].find_one({"key": _CF_KEY})
    db_sha = doc["hash"] if doc else None

    if combined_sha == db_sha:
        logger.info("cf_sync: comm_functions up to date (%s)", combined_sha[:16])
        return

    logger.info(
        "cf_sync: hash changed (%s → %s), syncing comm_functions",
        (db_sha or "none")[:16],
        combined_sha[:16],
    )

    from maestro.sync.ingest import upsert_comm_functions

    await upsert_comm_functions()

    await db[_VERSIONS_COLL].update_one(
        {"key": _CF_KEY},
        {"$set": {"hash": combined_sha, "applied_at": utcnow()}},
        upsert=True,
    )
    logger.info("cf_sync: synced comm_functions")
