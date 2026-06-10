"""Integration tests for vocab/discover.py — annotations-driven discover() flow."""

import pytest
from unittest.mock import AsyncMock, patch

from beanie import PydanticObjectId
from maestro.models import Sense, VocabAnnotation, VocabularyWord, UserVocabularyCard
from maestro.vocab import cache as _vocab_cache

_FAKE_STUDENT_ID = PydanticObjectId()


@pytest.fixture(autouse=True)
def reset_pending_def_gen():
    """Reset discover's deduplication set between tests."""
    from maestro.vocab import discover

    discover._pending_def_gen.clear()
    yield
    discover._pending_def_gen.clear()
    _vocab_cache.invalidate()


def _ann(lemma, surfaces, upos=""):
    return VocabAnnotation(surface_forms=list(surfaces), lemma=lemma, upos=upos)


@pytest.mark.integration
async def test_discover_creates_cards_for_new_words(db):
    """discover() should create UserVocabularyCards for annotated words not yet in the user's collection."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="mangiare",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-TEST",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Voglio mangiare la pizza.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=[_ann("mangiare", ["mangiare"], "VERB")],
        )

    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1
    assert cards[0].student_id == _FAKE_STUDENT_ID
    assert "vocab-word" in result


@pytest.mark.integration
async def test_discover_annotates_known_words(db):
    """discover() should annotate words even if a card already exists."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="bere",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-BERE",
        senses=[],
    )
    await word.insert()
    await UserVocabularyCard(student_id=_FAKE_STUDENT_ID, word=word).insert()

    _vocab_cache.seed(words={"bere": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Voglio bere acqua.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=[_ann("bere", ["bere"], "VERB")],
        )

    assert "vocab-word" in result
    assert 'data-word="bere"' in result
    # No duplicate card
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1


@pytest.mark.integration
async def test_discover_skips_non_target_lang(db):
    """discover() should not annotate text outside target-language elements."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="house",
        part_of_speech="n.",
        cefr_level="A1",
        entry_id="LM-HOUSE",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"house": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="en">The house is big.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=[_ann("house", ["house"], "NOUN")],
        )

    # No annotation because the text is in English, not target language (it)
    assert "vocab-word" not in result


def _word_with_senses(**kwargs) -> VocabularyWord:
    """Create a VocabularyWord with at least one sense (triggers def generation)."""
    defaults = dict(
        word="mangiare",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-TEST",
        senses=[Sense(definition="consumare cibo")],
    )
    defaults.update(kwargs)
    return VocabularyWord(**defaults)


_MANGIARE_ANNS = [_ann("mangiare", ["mangiare"], "VERB")]


@pytest.mark.integration
async def test_anonymous_discover_triggers_definition_generation(db):
    """discover() with create_cards=False should still fire background def generation."""
    from maestro.vocab.discover import discover

    word = _word_with_senses()
    await word.insert()

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="it">mangiare</span>',
            student_id=None,
            create_cards=False,
            language="it",
            annotations=_MANGIARE_ANNS,
        )

    # No cards created for anonymous user
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 0

    # But background task was fired for definition generation
    assert mock_bg.called
    bg_names = [c.kwargs.get("name", "") for c in mock_bg.call_args_list]
    assert any("vocab-defs-" in n for n in bg_names)


@pytest.mark.integration
async def test_deduplication_prevents_duplicate_tasks(db):
    """discover() should not fire a background task for words already being generated."""
    from maestro.vocab.discover import discover, _pending_def_gen

    word = _word_with_senses()
    await word.insert()

    # Simulate word already being generated by a concurrent request
    _pending_def_gen.add(str(word.id))

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="it">mangiare</span>',
            student_id=None,
            create_cards=False,
            language="it",
            annotations=_MANGIARE_ANNS,
        )

    # Definition task should NOT be fired — word is already in _pending_def_gen
    bg_names = [c.kwargs.get("name", "") for c in mock_bg.call_args_list]
    assert not any("vocab-defs-" in n for n in bg_names)


@pytest.mark.integration
async def test_generate_and_cache_cleans_up_pending_set(db):
    """_generate_and_cache should remove word IDs from _pending_def_gen on completion."""
    from maestro.vocab.discover import _generate_and_cache, _pending_def_gen

    word = _word_with_senses()
    await word.insert()

    word_id_str = str(word.id)
    _pending_def_gen.add(word_id_str)

    with patch(
        "maestro.vocab.discover.generate_definitions_for_word",
        new_callable=AsyncMock,
    ):
        await _generate_and_cache([word])

    assert word_id_str not in _pending_def_gen


@pytest.mark.integration
async def test_generate_and_cache_cleans_up_on_failure(db):
    """_generate_and_cache should remove word IDs from _pending_def_gen even on failure."""
    from maestro.vocab.discover import _generate_and_cache, _pending_def_gen

    word = _word_with_senses()
    await word.insert()

    word_id_str = str(word.id)
    _pending_def_gen.add(word_id_str)

    with patch(
        "maestro.vocab.discover.generate_definitions_for_word",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM error"),
    ):
        await _generate_and_cache([word])

    # Should still be cleaned up despite failure
    assert word_id_str not in _pending_def_gen


@pytest.mark.integration
async def test_authenticated_discover_creates_cards_and_triggers_defs(db):
    """discover() with create_cards=True should create cards AND fire def generation."""
    from maestro.vocab.discover import discover

    word = _word_with_senses()
    await word.insert()

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    with (
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A1",
        ),
        patch("maestro.vocab.discover.create_background_task") as mock_bg,
    ):
        await discover(
            '<span lang="it">mangiare</span>',
            student_id=_FAKE_STUDENT_ID,
            create_cards=True,
            language="it",
            annotations=_MANGIARE_ANNS,
        )

    # Cards created
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1

    # Background task also fired
    assert mock_bg.called


@pytest.mark.integration
async def test_de_discover_triggers_dwds_enrichment(db):
    """German words without senses should fire the DWDS enrich+generate task."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="trinken",
        part_of_speech="V.",
        cefr_level=None,
        senses=[],
        language="de",
    )
    await word.insert()

    _vocab_cache.seed(words={"trinken": [word]}, defs={}, language="de")

    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="de">Ich möchte etwas trinken.</span>',
            student_id=None,
            create_cards=False,
            language="de",
            annotations=[_ann("trinken", ["trinken"], "VERB")],
        )

    bg_names = [c.kwargs.get("name", "") for c in mock_bg.call_args_list]
    assert any("vocab-enrich-" in n for n in bg_names)
