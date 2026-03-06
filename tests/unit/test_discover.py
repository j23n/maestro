"""Unit tests for vocab/discover.py — _annotate() pure function."""
import pytest
from types import SimpleNamespace

from maestro.vocab.discover import _annotate


def _make_word(word="casa", pos="s.f.", syllabization="cà-sa", entry_id="LM-001", senses=None):
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization=syllabization,
        entry_id=entry_id,
        senses=senses or [],
        id="fake-id",
    )


def _make_wdef(translation="house", senses=None):
    return SimpleNamespace(
        translation=translation,
        senses=senses or [SimpleNamespace(
            definition="edificio dove si abita",
            translation=translation,
            examples=["La mia casa è grande."],
        )],
    )


@pytest.mark.unit
def test_annotate_wraps_first_occurrence():
    word = _make_word(word="casa")
    wdef = _make_wdef()
    result = _annotate("La casa è grande.", word, wdef)
    assert '<span class="vocab-word"' in result
    assert 'data-word="casa"' in result
    assert result.count("vocab-word") == 1  # only first occurrence


@pytest.mark.unit
def test_annotate_case_insensitive():
    word = _make_word(word="casa")
    result = _annotate("CASA bella", word, None)
    assert "vocab-word" in result


@pytest.mark.unit
def test_annotate_skips_headings():
    word = _make_word(word="tema")
    result = _annotate("# Tema principale\nIl tema è interessante.", word, None)
    lines = result.split("\n")
    assert "vocab-word" not in lines[0]  # heading untouched
    assert "vocab-word" in lines[1]      # body annotated


@pytest.mark.unit
def test_annotate_preserves_existing_html_tags():
    word = _make_word(word="bello")
    result = _annotate('Un <strong>bello</strong> giorno e un bello tramonto.', word, None)
    assert "<strong>" in result
    assert "vocab-word" in result


@pytest.mark.unit
def test_annotate_no_match_returns_unchanged():
    word = _make_word(word="casa")
    text = "Il giardino è grande."
    result = _annotate(text, word, None)
    assert result == text


@pytest.mark.unit
def test_annotate_includes_senses_json():
    word = _make_word(word="tavolo")
    wdef = _make_wdef(translation="table")
    result = _annotate("Il tavolo è rotondo.", word, wdef)
    assert 'data-translation="table"' in result
    assert "data-senses" in result


@pytest.mark.unit
def test_annotate_no_wdef_produces_empty_senses():
    """When wdef is None, data-senses should be an empty JSON array."""
    word = _make_word(word="libro")
    result = _annotate("Ho letto un libro.", word, None)
    assert "vocab-word" in result
    assert "data-senses='[]'" in result


@pytest.mark.unit
def test_annotate_word_boundary():
    """'casa' should not match inside 'casamento'."""
    word = _make_word(word="casa")
    result = _annotate("Il casamento è vecchio.", word, None)
    assert "vocab-word" not in result
