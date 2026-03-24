"""Integration tests for vocab/discover.py — discover() flow."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from beanie import PydanticObjectId
from maestro.models import Sense, VocabularyWord, UserVocabularyCard
from maestro.vocab import cache as _vocab_cache

_FAKE_STUDENT_ID = PydanticObjectId()


@pytest.fixture(autouse=True)
def reset_pending_def_gen():
    """Reset discover's deduplication set between tests."""
    from maestro.vocab import discover

    discover._pending_def_gen.clear()
    yield
    discover._pending_def_gen.clear()


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

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Voglio mangiare la pizza.</span>',
            student_id=_FAKE_STUDENT_ID,
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

    _vocab_cache.seed(words={"bere": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="it">Voglio bere acqua.</span>', student_id=_FAKE_STUDENT_ID
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

    _vocab_cache.seed(words={"house": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        result = await discover(
            '<span lang="en">The house is big.</span>', student_id=_FAKE_STUDENT_ID
        )

    # No annotation because the text is in English, not target language (it)
    assert "vocab-word" not in result


@pytest.mark.integration
async def test_discover_simplemma_fallback(db):
    """discover() should find words via simplemma when spaCy's lemma misses the word_index.

    NOTE: relies on spaCy it_core_news_md returning "parlo" (surface) as the
    lemma for "Parlo".  If a future model update fixes this, the test still
    passes but no longer exercises the fallback path.
    """
    from maestro.vocab.discover import discover

    word = VocabularyWord(
        word="parlare",
        part_of_speech="v.intr.",
        cefr_level="A1",
        entry_id="LM-PARLARE",
        senses=[],
    )
    await word.insert()

    _vocab_cache.seed(words={"parlare": [word]}, defs={})

    with patch(
        "maestro.vocab.discover.get_cefr_level",
        new_callable=AsyncMock,
        return_value="A1",
    ):
        # spaCy returns "parlo" as the lemma for "Parlo" (a known failure);
        # simplemma should correct it to "parlare" and find the word_index entry.
        result = await discover(
            '<span lang="it">Parlo italiano.</span>',
            student_id=_FAKE_STUDENT_ID,
        )

    assert "vocab-word" in result
    assert 'data-word="parlare"' in result


@pytest.mark.integration
async def test_discover_no_lang_returns_unchanged(db):
    """discover() returns text unchanged when no lang attributes are present."""
    from maestro.vocab.discover import discover

    text = "Some plain text without lang tags."
    result = await discover(text, student_id=_FAKE_STUDENT_ID)
    assert result == text


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


@pytest.mark.integration
async def test_anonymous_discover_triggers_definition_generation(db):
    """discover() with create_cards=False should still fire background def generation."""
    from maestro.vocab.discover import discover

    word = _word_with_senses()
    await word.insert()

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    mock_nlp = MagicMock()
    mock_token = MagicMock()
    mock_token.lemma_ = "mangiare"
    mock_token.pos_ = "VERB"
    mock_token.text = "mangiare"
    mock_token.is_alpha = True
    mock_nlp.return_value = [mock_token]

    with (
        patch("maestro.vocab.discover.get_nlp", return_value=mock_nlp),
        patch("maestro.vocab.discover.create_background_task") as mock_bg,
    ):
        await discover(
            '<span lang="it">mangiare</span>',
            student_id=None,
            create_cards=False,
        )

    # No cards created for anonymous user
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 0

    # But background task was fired for definition generation
    assert mock_bg.called
    assert "vocab-defs-" in mock_bg.call_args.kwargs.get("name", "")


@pytest.mark.integration
async def test_deduplication_prevents_duplicate_tasks(db):
    """discover() should not fire a background task for words already being generated."""
    from maestro.vocab.discover import discover, _pending_def_gen

    word = _word_with_senses()
    await word.insert()

    # Simulate word already being generated by a concurrent request
    _pending_def_gen.add(str(word.id))

    _vocab_cache.seed(words={"mangiare": [word]}, defs={})

    mock_nlp = MagicMock()
    mock_token = MagicMock()
    mock_token.lemma_ = "mangiare"
    mock_token.pos_ = "VERB"
    mock_token.text = "mangiare"
    mock_token.is_alpha = True
    mock_nlp.return_value = [mock_token]

    with (
        patch("maestro.vocab.discover.get_nlp", return_value=mock_nlp),
        patch("maestro.vocab.discover.create_background_task") as mock_bg,
    ):
        await discover(
            '<span lang="it">mangiare</span>',
            student_id=None,
            create_cards=False,
        )

    # Background task should NOT be fired — word is already in _pending_def_gen
    assert not mock_bg.called


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

    mock_nlp = MagicMock()
    mock_token = MagicMock()
    mock_token.lemma_ = "mangiare"
    mock_token.pos_ = "VERB"
    mock_token.text = "mangiare"
    mock_token.is_alpha = True
    mock_nlp.return_value = [mock_token]

    with (
        patch("maestro.vocab.discover.get_nlp", return_value=mock_nlp),
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
        )

    # Cards created
    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1

    # Background task also fired
    assert mock_bg.called


# ---------------------------------------------------------------------------
# Vocabulary coverage — match_vocab_words against real production dictionary
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _make_vocab_obj(word: str, pos: str) -> SimpleNamespace:
    """Lightweight stand-in for VocabularyWord (no DB required)."""
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization="",
        entry_id=f"LM-{word.upper()[:10]}",
        senses=[],
        id=f"fixture-{word}-{pos}",
        audio_url=None,
    )


@pytest.fixture(scope="module")
def prod_word_index() -> dict[str, list]:
    """Build a word_index from the production vocabulary fixture.

    The fixture (tests/fixtures/vocab_headwords.json) is generated from the
    EPUB dictionary — the ground truth source for production vocabulary.
    Loading it here lets us test match_vocab_words against the real
    vocabulary without needing MongoDB or the EPUB on disk.
    """
    fixture_path = _FIXTURES_DIR / "vocab_headwords.json"
    if not fixture_path.exists():
        pytest.skip(
            "vocab_headwords.json fixture not found — run scripts/dump_vocab_fixture.py"
        )
    with open(fixture_path) as f:
        raw = json.load(f)
    idx: dict[str, list] = {}
    for word, pos in raw:
        idx.setdefault(word, []).append(_make_vocab_obj(word, pos))
    return idx


@pytest.mark.integration
@pytest.mark.parametrize(
    "text, expected_words",
    [
        # -- Basic sentences: content words + function words --
        pytest.param(
            "Marco va al mercato",
            {"andare", "al", "mercato"},
            id="basic-mercato",
        ),
        pytest.param(
            "La signora Rossi",
            {"la", "signora"},
            id="basic-signora",
        ),
        pytest.param(
            "Paolo mangia la pizza",
            {"la", "mangiare", "pizza"},
            id="basic-pizza",
        ),
        pytest.param(
            "un'amica di Roma",
            {"uno", "amico", "di"},
            id="basic-amica",
        ),
        # -- Elision --
        pytest.param(
            "l'acqua è fredda",
            {"il", "acqua", "essere", "freddo"},
            id="elision-acqua",
        ),
        pytest.param(
            "dov'è il bagno",
            {"dove", "essere", "il", "bagno"},
            id="elision-dove",
        ),
        # -- Conjugated surface → lemma → dictionary word --
        pytest.param(
            "il gatto dorme sul divano",
            {"il", "gatto", "dormire", "sul", "divano"},
            id="chain-gatto-dorme-divano",
        ),
        pytest.param(
            "vorrei un caffè per favore",
            {"volere", "uno", "caffè", "per", "favore"},
            id="chain-vorrei-caffe",
        ),
        pytest.param(
            "la stazione è lontana",
            {"la", "stazione", "essere", "lontano"},
            id="chain-stazione-lontana",
        ),
        pytest.param(
            "ho comprato due biglietti",
            {"avere", "comprare", "due", "biglietto"},
            id="chain-comprato-biglietti",
        ),
        pytest.param(
            "il treno parte alle otto",
            {"il", "treno", "partire", "alle", "otto"},
            id="chain-treno-parte",
        ),
        pytest.param(
            "ciao come stai",
            {"ciao", "come", "stare"},
            id="chain-ciao-come-stai",
        ),
        # -- POS: "abito" exists in EPUB as noun, so no simplemma fallback --
        pytest.param(
            "abito in Italia",
            {"abito", "in"},
            id="pos-abito-noun",
        ),
        pytest.param(
            "mi dispiace molto",
            {"mi", "dispiacere", "molto"},
            id="pos-dispiacere",
        ),
    ],
)
def test_vocab_coverage(prod_word_index, text, expected_words):
    """match_vocab_words against the real production dictionary.

    These tests catch two classes of bugs that unit tests (with a hand-crafted
    word_index) cannot:
      1. Missing vocabulary — function words like "il", "di", "per" absent
         from the dictionary would silently drop from annotations.
      2. Dictionary-dependent POS behaviour — e.g. "abito" resolves to the
         noun entry in the real dictionary instead of falling back to
         simplemma → "abitare".
    """
    from maestro.vocab.discover import match_vocab_words

    matches = match_vocab_words(text, prod_word_index)
    matched_words = {m.word.word for m in matches}
    assert matched_words == expected_words, (
        f"match_vocab_words({text!r})\n"
        f"  expected: {sorted(expected_words)}\n"
        f"  got:      {sorted(matched_words)}"
    )
