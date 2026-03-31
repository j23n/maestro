"""Unit tests for gp_sync.sync_if_changed."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(stored_hash: str | None = None):
    """Return a mock db whose _data_versions collection has the given stored hash."""
    doc = {"key": "grammar_points", "hash": stored_hash} if stored_hash else None

    data_versions_coll = MagicMock()
    data_versions_coll.find_one = AsyncMock(return_value=doc)
    data_versions_coll.update_one = AsyncMock()

    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: {"_data_versions": data_versions_coll}.get(
            name, MagicMock()
        )
    )
    return db, data_versions_coll


# ---------------------------------------------------------------------------
# sync_if_changed tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_skips_when_up_to_date():
    """No ingest runs when the combined lock hash matches what is stored in the DB."""
    db, data_versions_coll = _make_db(stored_hash="abc123")

    with (
        patch("maestro.sync.grammar._combined_lock_hash", return_value="abc123"),
        patch(
            "maestro.sync.ingest.upsert_grammar_points", new_callable=AsyncMock
        ) as mock_upsert,
    ):
        from maestro.sync.grammar import sync_if_changed

        await sync_if_changed(db)

    mock_upsert.assert_not_called()
    data_versions_coll.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_runs_on_first_deploy():
    """Ingest runs and hash is stored when there is no existing DB record."""
    db, data_versions_coll = _make_db(stored_hash=None)
    mock_gps = [MagicMock(), MagicMock()]

    with (
        patch("maestro.sync.grammar._combined_lock_hash", return_value="deadbeef"),
        patch(
            "maestro.sync.ingest.upsert_grammar_points",
            new_callable=AsyncMock,
            return_value=mock_gps,
        ),
    ):
        from maestro.sync.grammar import sync_if_changed

        await sync_if_changed(db)

    data_versions_coll.update_one.assert_awaited_once()
    stored = data_versions_coll.update_one.call_args
    assert stored.args[0] == {"key": "grammar_points"}
    assert stored.args[1]["$set"]["hash"] == "deadbeef"
    assert stored.kwargs["upsert"] is True


@pytest.mark.asyncio
async def test_sync_runs_when_hash_changed():
    """Ingest runs and stored hash is updated when the lock hash differs from the DB."""
    db, data_versions_coll = _make_db(stored_hash="old_hash")
    mock_gps = [MagicMock()]

    with (
        patch("maestro.sync.grammar._combined_lock_hash", return_value="new_hash"),
        patch(
            "maestro.sync.ingest.upsert_grammar_points",
            new_callable=AsyncMock,
            return_value=mock_gps,
        ) as mock_upsert,
    ):
        from maestro.sync.grammar import sync_if_changed

        await sync_if_changed(db)

    mock_upsert.assert_awaited_once()
    stored_hash = data_versions_coll.update_one.call_args.args[1]["$set"]["hash"]
    assert stored_hash == "new_hash"


@pytest.mark.asyncio
async def test_sync_skips_when_lock_missing(caplog):
    """No ingest runs when no lock files are found; a warning is logged."""
    db, data_versions_coll = _make_db()

    with (
        patch("maestro.sync.grammar._combined_lock_hash", return_value=None),
        patch(
            "maestro.sync.ingest.upsert_grammar_points", new_callable=AsyncMock
        ) as mock_upsert,
    ):
        import logging

        with caplog.at_level(logging.WARNING, logger="maestro.sync.grammar"):
            from maestro.sync.grammar import sync_if_changed

            await sync_if_changed(db)

    mock_upsert.assert_not_called()
    data_versions_coll.update_one.assert_not_awaited()
    assert any("lock" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# combined_lock_hash tests
# ---------------------------------------------------------------------------


def test_combined_lock_hash_returns_hash(tmp_path):
    """Returns a combined hash when lock files exist."""
    lang_dir = tmp_path / "it"
    lang_dir.mkdir()
    lock_file = lang_dir / "grammar_points.lock"
    lock_file.write_text(json.dumps({"sha256": "cafebabe", "gp_count": 10}))

    with patch("maestro.utils.iter_language_dirs", return_value=iter([lang_dir])):
        from maestro.utils import combined_lock_hash

        result = combined_lock_hash("grammar_points.lock")
    assert result is not None
    assert len(result) == 64  # sha256 hex


def test_combined_lock_hash_returns_none_when_missing(tmp_path):
    """Returns None when no lock files exist."""
    lang_dir = tmp_path / "it"
    lang_dir.mkdir()

    with patch("maestro.utils.iter_language_dirs", return_value=iter([lang_dir])):
        from maestro.utils import combined_lock_hash

        assert combined_lock_hash("grammar_points.lock") is None


def test_combined_lock_hash_skips_corrupt_files(tmp_path):
    """Skips corrupt lock files gracefully."""
    lang_dir = tmp_path / "it"
    lang_dir.mkdir()
    lock_file = lang_dir / "grammar_points.lock"
    lock_file.write_text("not valid json {{")

    with patch("maestro.utils.iter_language_dirs", return_value=iter([lang_dir])):
        from maestro.utils import combined_lock_hash

        assert combined_lock_hash("grammar_points.lock") is None
