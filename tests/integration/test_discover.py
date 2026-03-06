"""Integration tests for vocab/discover.py — discover() flow."""
import pytest
from unittest.mock import AsyncMock, patch

from maestro.models import VocabularyWord, UserVocabularyCard
from maestro.vocab import cache as _vocab_cache


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

    with patch("maestro.vocab.discover._lemmatize", return_value=["mangiare"]), \
         patch("maestro.vocab.discover.get_cefr_level", new_callable=AsyncMock, return_value="A1"):
        result = await discover("Voglio mangiare la pizza.")

    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1
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

    with patch("maestro.vocab.discover._lemmatize", return_value=["bere"]), \
         patch("maestro.vocab.discover.get_cefr_level", new_callable=AsyncMock, return_value="A1"):
        result = await discover("Voglio bere acqua.")

    assert "vocab-word" in result
    assert 'data-word="bere"' in result
