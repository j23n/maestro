"""A0 vocabulary data versioning: sync vocab_a0.yaml → MongoDB on startup.

How it works:
  1. scripts/update_vocab_lock.py writes vocab_a0.lock (SHA256 of vocab_a0.yaml)
     whenever the YAML changes. This file is committed to the repo.
  2. At app startup, sync_if_changed() reads the lock hash and compares it against
     the hash stored in the _data_versions collection in MongoDB.
  3. If the hashes differ (new deploy with updated YAML), a full ingest runs and
     the stored hash is updated.

This means vocab_a0.yaml is the single source of truth: edit the YAML, update the
lock, deploy — the database catches up automatically on the next startup.
"""

import json
import logging
from pathlib import Path

from maestro.utils import DATA_DIR_ROOT, utcnow

logger = logging.getLogger(__name__)

_VERSIONS_COLL = "_data_versions"


def _read_lock_hash(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())["sha256"]
    except Exception:
        return None


def _language_dirs_with_vocab() -> list[tuple[str, Path]]:
    """Return (language, dir) pairs for every language that has a vocab_a0.yaml."""
    results = []
    if not DATA_DIR_ROOT.is_dir():
        return results
    for child in sorted(DATA_DIR_ROOT.iterdir()):
        if child.is_dir() and (child / "vocab_a0.yaml").exists():
            results.append((child.name, child))
    return results


async def sync_if_changed(db) -> None:
    """Compare vocab_a0.lock against DB for every language; sync those that changed."""
    lang_dirs = _language_dirs_with_vocab()
    if not lang_dirs:
        logger.info("vocab_sync: no vocab_a0.yaml found in any language directory")
        return

    for lang, lang_dir in lang_dirs:
        await _sync_language(db, lang, lang_dir)


async def _sync_language(db, lang: str, lang_dir: Path) -> None:
    lock_path = lang_dir / "vocab_a0.lock"
    lock_sha = _read_lock_hash(lock_path)
    db_key = f"vocab_a0_{lang}"

    if lock_sha is None:
        logger.warning(
            "vocab_sync [%s]: vocab_a0.lock not found — "
            "run: uv run python scripts/update_vocab_lock.py",
            lang,
        )
        return

    doc = await db[_VERSIONS_COLL].find_one({"key": db_key})
    db_sha = doc["hash"] if doc else None

    if lock_sha == db_sha:
        logger.info("vocab_sync [%s]: vocab_a0 up to date (%s)", lang, lock_sha[:16])
        return

    logger.info(
        "vocab_sync [%s]: hash changed (%s → %s), syncing vocab_a0",
        lang,
        (db_sha or "none")[:16],
        lock_sha[:16],
    )

    from maestro.sync.ingest import seed_a0_vocab

    await seed_a0_vocab(language=lang)

    await db[_VERSIONS_COLL].update_one(
        {"key": db_key},
        {"$set": {"hash": lock_sha, "applied_at": utcnow()}},
        upsert=True,
    )
    logger.info("vocab_sync [%s]: synced vocab_a0", lang)
