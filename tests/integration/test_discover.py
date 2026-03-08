"""Integration tests for vocab/discover.py — discover() flow."""

import pytest
from unittest.mock import AsyncMock, patch

from beanie import PydanticObjectId
from maestro.models import VocabularyWord, UserVocabularyCard
from maestro.vocab import cache as _vocab_cache
from maestro.vocab.discover import lang_wrap

_FAKE_STUDENT_ID = PydanticObjectId()


@pytest.mark.integration
async def test_discover_creates_cards_for_new_words(db):
    """discover() should create UserVocabularyCards for words not yet in the user's collection."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="mangiare",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-TEST",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"mangiare": word}, defs={})

    with (
        patch("maestro.vocab.discover._lemmatize", return_value=["mangiare"]),
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A1",
        ),
    ):
        result = await discover(
            lang_wrap("Voglio mangiare la pizza.", "it"), student_id=_FAKE_STUDENT_ID
        )

    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1
    assert cards[0].student_id == _FAKE_STUDENT_ID
    assert "vocab-word" in result


@pytest.mark.integration
async def test_discover_annotates_known_words(db):
    """discover() should annotate words found in the vocab cache, even if a card already exists."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="bere",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-BERE",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"bere": word}, defs={})

    with (
        patch("maestro.vocab.discover._lemmatize", return_value=["bere"]),
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A1",
        ),
    ):
        result = await discover(
            lang_wrap("Voglio bere acqua.", "it"), student_id=_FAKE_STUDENT_ID
        )

    assert "vocab-word" in result
    assert 'data-word="bere"' in result


@pytest.mark.integration
async def test_discover_skips_non_target_lang(db):
    """discover() should skip text in non-target language elements."""
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="house",
        part_of_speech="n.",
        cefr_level="A1",
        entry_id="LM-HOUSE",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"house": word}, defs={})

    with (
        patch("maestro.vocab.discover._lemmatize", return_value=["house"]),
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A1",
        ),
    ):
        result = await discover(
            lang_wrap("The house is big.", "en"), student_id=_FAKE_STUDENT_ID
        )

    # No annotation because the text is in English, not target language (it)
    assert "vocab-word" not in result


@pytest.mark.integration
async def test_discover_no_lang_returns_unchanged(db):
    """discover() returns text unchanged when no lang attributes are present."""
    from maestro.vocab.discover import discover

    text = "Some plain text without lang tags."
    result = await discover(text, student_id=_FAKE_STUDENT_ID)
    assert result == text
