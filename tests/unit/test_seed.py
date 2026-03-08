"""Unit tests for maestro.seed.seed_if_empty()."""

import logging

import bson
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.seed import SEED_COLLECTIONS, seed_if_empty


def _make_db(count=0):
    """Create a mock db where every collection returns `count` for count_documents."""
    db = MagicMock()
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=count)
    collection.insert_many = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db, collection


@pytest.mark.unit
async def test_skips_when_db_has_data():
    db, col = _make_db(count=1)
    await seed_if_empty(db)
    col.insert_many.assert_not_called()


@pytest.mark.unit
async def test_seeds_when_db_is_empty(tmp_path):
    db, col = _make_db(count=0)
    # Create BSON seed files
    for name in SEED_COLLECTIONS:
        raw = bson.encode({"_id": bson.ObjectId(), "name": "fake"})
        (tmp_path / f"{name}.bson").write_bytes(raw)

    with patch("maestro.seed.SEED_DIR", tmp_path):
        await seed_if_empty(db)

    assert col.insert_many.call_count == len(SEED_COLLECTIONS)


@pytest.mark.unit
async def test_handles_missing_seed_dir(caplog):
    db, col = _make_db(count=0)
    with (
        patch("maestro.seed.SEED_DIR", MagicMock(exists=MagicMock(return_value=False))),
        caplog.at_level(logging.WARNING, logger="maestro.seed"),
    ):
        await seed_if_empty(db)

    assert "Seed directory not found" in caplog.text
    col.insert_many.assert_not_called()
