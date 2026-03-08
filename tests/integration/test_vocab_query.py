"""Integration tests for get_word_definition (consolidated word-definition lookup)."""

import pytest

from maestro.models import VocabularyWord, VocabularyWordDefinition, CefrSense
from maestro.vocab.query import get_word_definition


@pytest.fixture
async def word(db):
    w = VocabularyWord(word="gatto", part_of_speech="s.m.", cefr_level="A1")
    await w.insert()
    return w


@pytest.fixture
async def word_with_defs(word):
    """Word with A1 and A2 definitions."""
    await VocabularyWordDefinition(
        word=word,
        student_level="A1",
        translation="cat",
        senses=[CefrSense(definition="un animale domestico")],
    ).insert()
    await VocabularyWordDefinition(
        word=word,
        student_level="A2",
        translation="cat",
        senses=[CefrSense(definition="un felino domestico comune")],
    ).insert()
    return word


@pytest.mark.integration
async def test_get_word_definition_at_level(word_with_defs):
    """Returns matching definition for the requested level."""
    wdef = await get_word_definition(word_with_defs, "A1")
    assert wdef is not None
    assert wdef.student_level == "A1"
    assert wdef.translation == "cat"


@pytest.mark.integration
async def test_get_word_definition_different_level(word_with_defs):
    """Returns definition for the specific level requested."""
    wdef = await get_word_definition(word_with_defs, "A2")
    assert wdef is not None
    assert wdef.student_level == "A2"


@pytest.mark.integration
async def test_get_word_definition_a0_fallback(word_with_defs):
    """A0 request falls back to A1 definition."""
    wdef = await get_word_definition(word_with_defs, "A0")
    assert wdef is not None
    assert wdef.student_level == "A1"


@pytest.mark.integration
async def test_get_word_definition_missing_level(word_with_defs):
    """Returns None when no definition exists for the level (and no fallback applies)."""
    wdef = await get_word_definition(word_with_defs, "B2")
    assert wdef is None


@pytest.mark.integration
async def test_get_word_definition_no_definitions(word):
    """Returns None when word has no definitions at all."""
    wdef = await get_word_definition(word, "A1")
    assert wdef is None
