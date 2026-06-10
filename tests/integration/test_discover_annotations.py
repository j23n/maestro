"""Integration tests for the pre-annotated discover() path.

With verified annotations supplied, runtime NLP matching is skipped: only
the verified mappings are annotated in the HTML and only they can create
UserVocabularyCards — unverified words can never pollute the vocabulary.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from beanie import PydanticObjectId

from maestro.models import UserVocabularyCard, VocabAnnotation, VocabularyWord
from maestro.vocab import cache as _vocab_cache

pytestmark = pytest.mark.integration

_FAKE_STUDENT_ID = PydanticObjectId()


@pytest.fixture(autouse=True)
def reset_pending_def_gen():
    from maestro.vocab import discover

    discover._pending_def_gen.clear()
    yield
    discover._pending_def_gen.clear()
    _vocab_cache.invalidate("it")


async def _seed_words():
    mangiare = VocabularyWord(
        word="mangiare", part_of_speech="v.tr.", cefr_level="A1", senses=[]
    )
    pizza = VocabularyWord(
        word="pizza", part_of_speech="s.f.", cefr_level="A1", senses=[]
    )
    await mangiare.insert()
    await pizza.insert()
    _vocab_cache.seed(
        words={"mangiare": [mangiare], "pizza": [pizza]}, defs={}, language="it"
    )
    return mangiare, pizza


async def test_annotated_path_skips_nlp_and_annotates_verified_words(db):
    from maestro.vocab.discover import discover

    await _seed_words()
    annotations = [
        VocabAnnotation(surface_forms=["Mangio"], lemma="mangiare", upos="VERB")
    ]

    with (
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A1",
        ),
        patch("maestro.vocab.discover.match_vocab_words") as mock_nlp,
    ):
        result = await discover(
            '<span lang="it">Mangio una pizza enorme.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=annotations,
        )

    # NLP matching never runs on the pre-annotated path
    mock_nlp.assert_not_called()

    # Only the verified word is annotated — "pizza" is in the dictionary but
    # wasn't verified for this content, so it gets no popover and no card.
    assert 'data-word="mangiare"' in result
    assert 'data-word="pizza"' not in result
    cards = await UserVocabularyCard.find_all().to_list()
    assert [c.word.ref.id for c in cards] == [
        (await VocabularyWord.find_one(VocabularyWord.word == "mangiare")).id
    ]


async def test_annotated_path_skips_unresolvable_lemmas(db):
    from maestro.vocab.discover import discover

    await _seed_words()
    annotations = [
        # Bad lemma (not a dictionary headword) — must never create a card
        VocabAnnotation(surface_forms=["capisco"], lemma="capiscare", upos="VERB"),
        VocabAnnotation(surface_forms=["pizza"], lemma="pizza", upos="NOUN"),
    ]

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Capisco, una pizza.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=annotations,
        )

    assert 'data-word="pizza"' in result
    assert "capiscare" not in result
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1


async def test_empty_annotations_annotate_nothing(db):
    from maestro.vocab.discover import discover

    await _seed_words()
    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Mangio una pizza.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
            annotations=[],
        )

    assert "vocab-word" not in result
    assert await UserVocabularyCard.find_all().to_list() == []


async def test_none_annotations_keep_legacy_nlp_path(db):
    """annotations=None (default) must preserve the existing NLP behavior."""
    from maestro.vocab.discover import discover

    await _seed_words()
    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Voglio mangiare la pizza.</span>',
            student_id=_FAKE_STUDENT_ID,
            language="it",
        )

    assert 'data-word="mangiare"' in result
    assert 'data-word="pizza"' in result
