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

    # Migration 0003 iterates several collections — empty cursors so nothing needs remapping
    def _empty_coll():
        coll = MagicMock()
        coll.find.return_value = _empty_cursor()
        coll.bulk_write = AsyncMock(return_value=MagicMock(modified_count=0))
        coll.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
        coll.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
        return coll

    grammar_points_coll = MagicMock()
    grammar_points_coll.find.return_value = _empty_cursor()
    grammar_points_coll.update_many = AsyncMock(
        return_value=MagicMock(modified_count=0)
    )

    vocabulary_words_coll = MagicMock()
    vocabulary_words_coll.drop_index = AsyncMock()
    vocabulary_words_coll.create_index = AsyncMock()
    vocabulary_words_coll.delete_many = AsyncMock(
        return_value=MagicMock(deleted_count=0)
    )
    vocabulary_words_coll.update_many = AsyncMock(
        return_value=MagicMock(modified_count=0)
    )

    # aggregate() is a coroutine returning an async cursor — no duplicates in test data
    async def _empty_agg_cursor():
        return
        yield  # makes this an async generator

    vocabulary_words_coll.aggregate = AsyncMock(return_value=_empty_agg_cursor())

    _coll_cache = {
        "_migrations": migrations_coll,
        "drill_templates": drill_templates_coll,
        "generated_drills": generated_drills_coll,
        "grammar_points": grammar_points_coll,
        "vocabulary_words": vocabulary_words_coll,
        "vocabulary_word_definitions": _empty_coll(),
        "learning_profile": _empty_coll(),
        "learning_events": _empty_coll(),
        "curriculum_scenarios": _empty_coll(),
        "lessons": _empty_coll(),
        "user_vocabulary_cards": _empty_coll(),
    }

    def _get_coll(name):
        return _coll_cache.get(name, MagicMock())

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

    # Runner should have recorded all twelve migrations as applied
    assert migrations_coll.insert_one.await_count == 12
    recorded_names = [
        call.args[0]["name"] for call in migrations_coll.insert_one.call_args_list
    ]
    assert recorded_names == [
        "0001_remove_free_form_drills",
        "0002_drop_drill_templates",
        "0003_short_codes",
        "0004_vocab_compound_unique",
        "0005_backfill_grammar_introduced",
        "0006_mastery_scores",
        "0007_remove_stale_a0_vocab_dupes",
        "0008_remove_html_tagged_definitions",
        "0009_fix_stuck_pending_lessons",
        "0010_vocab_language_unique",
        "0011_multi_language_progress",
        "0012_storyline_fields",
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
            "0004_vocab_compound_unique",
            "0005_backfill_grammar_introduced",
            "0006_mastery_scores",
            "0007_remove_stale_a0_vocab_dupes",
            "0008_remove_html_tagged_definitions",
            "0009_fix_stuck_pending_lessons",
            "0010_vocab_language_unique",
            "0011_multi_language_progress",
            "0012_storyline_fields",
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


# ---------------------------------------------------------------------------
# Migration 0005 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_0005_backfills_grammar_introduced():
    """Migration 0005 sets grammar_introduced from grammar_recent_outcomes keys."""
    from bson import ObjectId

    profile_id = ObjectId()
    profile_doc = {
        "_id": profile_id,
        "grammar_recent_outcomes": {"pres_ind": [True, False], "def_art": [True]},
    }

    updated_docs = {}

    async def _profile_cursor():
        yield profile_doc

    profile_coll = MagicMock()
    profile_coll.find.return_value = _profile_cursor()

    async def _capture_update(filter_doc, update_doc):
        updated_docs[filter_doc["_id"]] = update_doc

    profile_coll.update_one = AsyncMock(side_effect=_capture_update)

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=profile_coll)

    import importlib

    m = importlib.import_module("maestro.migrations.0005_backfill_grammar_introduced")

    await m.run(db)

    assert profile_id in updated_docs
    introduced = updated_docs[profile_id]["$set"]["grammar_introduced"]
    assert set(introduced) == {"pres_ind", "def_art"}


@pytest.mark.asyncio
async def test_0005_skips_profiles_with_empty_outcomes():
    """Migration 0005 sets empty grammar_introduced when no outcomes exist."""
    from bson import ObjectId

    profile_id = ObjectId()
    profile_doc = {"_id": profile_id}  # no grammar_recent_outcomes

    updated_docs = {}

    async def _profile_cursor():
        yield profile_doc

    profile_coll = MagicMock()
    profile_coll.find.return_value = _profile_cursor()

    async def _capture_update(filter_doc, update_doc):
        updated_docs[filter_doc["_id"]] = update_doc

    profile_coll.update_one = AsyncMock(side_effect=_capture_update)

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=profile_coll)

    import importlib

    m = importlib.import_module("maestro.migrations.0005_backfill_grammar_introduced")

    await m.run(db)

    assert profile_id in updated_docs
    assert updated_docs[profile_id]["$set"]["grammar_introduced"] == []


@pytest.mark.asyncio
async def test_0012_adds_storyline_defaults_per_language():
    """Migration 0012 backfills storyline fields under every progress.<lang> key."""
    from bson import ObjectId

    profile_id = ObjectId()
    profile_doc = {
        "_id": profile_id,
        "progress": {
            "it": {"cefr_estimate": "A1"},
            "de": {"cefr_estimate": "A0", "storyline": "already set"},
        },
    }

    updated: dict = {}

    async def _cursor():
        yield profile_doc

    profile_coll = MagicMock()
    profile_coll.find.return_value = _cursor()

    async def _capture_update(filter_doc, update_doc):
        updated[filter_doc["_id"]] = update_doc

    profile_coll.update_one = AsyncMock(side_effect=_capture_update)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=profile_coll)

    import importlib

    m = importlib.import_module("maestro.migrations.0012_storyline_fields")
    await m.run(db)

    assert profile_id in updated
    set_ops = updated[profile_id]["$set"]
    # Italian progress had no storyline — all three added.
    assert set_ops["progress.it.storyline"] == ""
    assert set_ops["progress.it.storyline_lessons_since_evolve"] == 0
    assert set_ops["progress.it.storyline_updated_at"] is None
    # German progress already had storyline — only the missing two added.
    assert "progress.de.storyline" not in set_ops
    assert set_ops["progress.de.storyline_lessons_since_evolve"] == 0
    assert set_ops["progress.de.storyline_updated_at"] is None


@pytest.mark.asyncio
async def test_0012_is_idempotent():
    """Running 0012 twice does not re-$set fields that are already present."""
    from bson import ObjectId

    profile_id = ObjectId()
    profile_doc = {
        "_id": profile_id,
        "progress": {
            "it": {
                "cefr_estimate": "A1",
                "storyline": "existing",
                "storyline_lessons_since_evolve": 2,
                "storyline_updated_at": None,
            }
        },
    }

    calls: list = []

    async def _cursor():
        yield profile_doc

    profile_coll = MagicMock()
    profile_coll.find.return_value = _cursor()

    async def _capture(filter_doc, update_doc):
        calls.append((filter_doc, update_doc))

    profile_coll.update_one = AsyncMock(side_effect=_capture)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=profile_coll)

    import importlib

    m = importlib.import_module("maestro.migrations.0012_storyline_fields")
    await m.run(db)

    # No update issued because all three fields were already present.
    assert calls == []
