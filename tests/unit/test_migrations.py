"""Unit tests for the migration runner and migration 0001."""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _empty_cursor():
    """Async generator yielding nothing — simulates an empty MongoDB cursor."""
    return
    yield  # makes this an async generator


def _make_db(applied_names: list[str] = None):
    """Return a mock db whose _migrations collection contains applied_names."""
    applied_names = applied_names or []

    # Async cursor that yields {"name": n} for each applied name
    async def _cursor_iter():
        for name in applied_names:
            yield {"name": name}

    migrations_coll = MagicMock()
    migrations_coll.find.return_value = _cursor_iter()
    migrations_coll.insert_one = AsyncMock()

    drill_templates_coll = MagicMock()
    drill_templates_coll.delete_many = AsyncMock(
        return_value=MagicMock(deleted_count=3)
    )
    drill_templates_coll.drop = AsyncMock()

    generated_drills_coll = MagicMock()
    generated_drills_coll.delete_many = AsyncMock(
        return_value=MagicMock(deleted_count=7)
    )
    generated_drills_coll.update_many = AsyncMock(
        return_value=MagicMock(modified_count=5)
    )

    # Migration 0003 iterates grammar_points — empty cursor causes early return
    grammar_points_coll = MagicMock()
    grammar_points_coll.find.return_value = _empty_cursor()
    grammar_points_coll.update_many = AsyncMock(
        return_value=MagicMock(modified_count=0)
    )

    def _get_coll(name):
        return {
            "_migrations": migrations_coll,
            "drill_templates": drill_templates_coll,
            "generated_drills": generated_drills_coll,
            "grammar_points": grammar_points_coll,
        }.get(name, MagicMock())

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=_get_coll)
    return db, migrations_coll, drill_templates_coll, generated_drills_coll


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_applies_pending_migration():
    """Runner inserts a record into _migrations after running each migration."""
    db, migrations_coll, drill_templates_coll, generated_drills_coll = _make_db()

    from maestro.migrations import run_pending

    await run_pending(db)

    # 0001 should have deleted free_form docs from both collections
    drill_templates_coll.delete_many.assert_awaited_once()
    generated_drills_coll.delete_many.assert_awaited_once()

    # 0002 should have dropped the collection and unset template fields
    drill_templates_coll.drop.assert_awaited_once()
    generated_drills_coll.update_many.assert_awaited_once()

    # Runner should have recorded all three migrations as applied
    assert migrations_coll.insert_one.await_count == 3
    recorded_names = [
        call.args[0]["name"] for call in migrations_coll.insert_one.call_args_list
    ]
    assert recorded_names == [
        "0001_remove_free_form_drills",
        "0002_drop_drill_templates",
        "0003_short_codes",
    ]
    for call in migrations_coll.insert_one.call_args_list:
        record = call.args[0]
        assert "applied_at" in record
        assert "duration_ms" in record


@pytest.mark.asyncio
async def test_runner_skips_already_applied():
    """Runner does not re-run a migration that is already recorded."""
    db, migrations_coll, drill_templates_coll, generated_drills_coll = _make_db(
        applied_names=[
            "0001_remove_free_form_drills",
            "0002_drop_drill_templates",
            "0003_short_codes",
        ]
    )

    from maestro.migrations import run_pending

    await run_pending(db)

    drill_templates_coll.delete_many.assert_not_awaited()
    drill_templates_coll.drop.assert_not_awaited()
    generated_drills_coll.delete_many.assert_not_awaited()
    generated_drills_coll.update_many.assert_not_awaited()
    migrations_coll.insert_one.assert_not_awaited()


# ---------------------------------------------------------------------------
# Migration 0001 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_0001_deletes_free_form_docs():
    """Migration 0001 deletes free_form docs from both collections."""
    db, _, drill_templates_coll, generated_drills_coll = _make_db()

    import importlib

    m = importlib.import_module("maestro.migrations.0001_remove_free_form_drills")

    await m.run(db)

    drill_templates_coll.delete_many.assert_awaited_once_with(
        {"exercise_type": "free_form"}
    )
    generated_drills_coll.delete_many.assert_awaited_once_with(
        {"exercise_type": "free_form"}
    )


@pytest.mark.asyncio
async def test_0001_is_idempotent():
    """Running migration 0001 twice does not raise and calls delete_many each time."""
    db, _, drill_templates_coll, generated_drills_coll = _make_db()
    # Second call returns 0 deleted (already clean)
    drill_templates_coll.delete_many = AsyncMock(
        return_value=MagicMock(deleted_count=0)
    )
    generated_drills_coll.delete_many = AsyncMock(
        return_value=MagicMock(deleted_count=0)
    )

    import importlib

    m = importlib.import_module("maestro.migrations.0001_remove_free_form_drills")

    await m.run(db)
    await m.run(db)

    assert drill_templates_coll.delete_many.await_count == 2
    assert generated_drills_coll.delete_many.await_count == 2


# ---------------------------------------------------------------------------
# Migration 0002 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_0002_drops_collection_and_unsets_field():
    """Migration 0002 drops drill_templates and unsets template from generated_drills."""
    db, _, drill_templates_coll, generated_drills_coll = _make_db()

    import importlib

    m = importlib.import_module("maestro.migrations.0002_drop_drill_templates")

    await m.run(db)

    drill_templates_coll.drop.assert_awaited_once()
    generated_drills_coll.update_many.assert_awaited_once_with(
        {}, {"$unset": {"template": ""}}
    )
