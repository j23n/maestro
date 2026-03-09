"""
Migration runner for Maestro.

Migrations are Python modules inside this package named <NNN>_<description>.py.
Each module must expose:

    async def run(db: AsyncIOMotorDatabase) -> None: ...

The runner tracks applied migrations in the ``_migrations`` collection:

    { name: str, applied_at: datetime, duration_ms: int }

Migrations are discovered and run in lexicographic order (by filename).
A migration is skipped if its name already appears in ``_migrations``.

Raw PyMongo (not Beanie) is used deliberately so that migrations can
operate on documents that may not conform to current model schemas.
"""

from __future__ import annotations

import importlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATIONS_COLLECTION = "_migrations"


async def run_pending(db) -> None:
    """Discover and run all not-yet-applied migrations in order."""
    coll = db[_MIGRATIONS_COLLECTION]

    applied: set[str] = {doc["name"] async for doc in coll.find({}, {"name": 1})}

    migration_files = sorted(p for p in Path(__file__).parent.glob("[0-9]*.py"))

    for path in migration_files:
        name = path.stem
        if name in applied:
            logger.debug("migration already applied: %s", name)
            continue

        logger.info("applying migration: %s", name)
        module = importlib.import_module(f"maestro.migrations.{name}")

        t0 = time.monotonic()
        await module.run(db)
        duration_ms = round((time.monotonic() - t0) * 1000)

        await coll.insert_one(
            {
                "name": name,
                "applied_at": datetime.now(timezone.utc),
                "duration_ms": duration_ms,
            }
        )
        logger.info("migration applied: %s (%d ms)", name, duration_ms)

    logger.debug("migrations up to date")
