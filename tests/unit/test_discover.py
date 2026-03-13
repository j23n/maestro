"""Unit tests for vocab/discover.py — _annotate() and lang-aware helpers."""

import pytest
from types import SimpleNamespace

from maestro.vocab.discover import (
    _annotate,
    _annotate_in_elements,
    lemmatize,
)
from bs4 import BeautifulSoup


def _make_word(
    word="casa", pos="s.f.", syllabization="cà-sa", entry_id="LM-001", senses=None
):
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
        senses=senses
        or [
            SimpleNamespace(
                definition="edificio dove si abita",
                translation=translation,
                examples=["La mia casa è grande."],
            )
        ],
    )


# --- Existing _annotate tests (string-based) ---


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
    assert "vocab-word" in lines[1]  # body annotated


@pytest.mark.unit
def test_annotate_preserves_existing_html_tags():
    word = _make_word(word="bello")
    result = _annotate(
        "Un <strong>bello</strong> giorno e un bello tramonto.", word, None
    )
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


# --- _annotate_in_elements tests (lang-aware BS4) ---


def _make_soup_and_elements(html, lang="it"):
    """Parse HTML and return (soup, lang_elements)."""
    soup = BeautifulSoup(html, "html.parser")
    return soup, soup.find_all(attrs={"lang": lang})


@pytest.mark.unit
def test_annotate_in_elements_target_lang():
    """Text in target-language span gets annotated."""
    soup, els = _make_soup_and_elements('<span lang="it">La casa è grande.</span>')
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    assert "vocab-word" in str(soup)
    assert 'data-word="casa"' in str(soup)


@pytest.mark.unit
def test_annotate_in_elements_skips_non_target():
    """Text in non-target-language span is not annotated."""
    html = '<span lang="en">The house is big.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="house")
    assert not els  # no target elements
    assert not _annotate_in_elements(els, word, None)
    assert "vocab-word" not in str(soup)


@pytest.mark.unit
def test_annotate_in_elements_mixed_lang():
    """Only target-lang text gets annotated in mixed content."""
    html = '<span lang="en">Say </span><span lang="it">ciao</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="ciao")
    assert _annotate_in_elements(els, word, None)
    result = str(soup)
    assert "vocab-word" in result
    assert 'data-word="ciao"' in result


@pytest.mark.unit
def test_annotate_in_elements_nested_lang_skips_inner():
    """English gloss nested inside Italian span is skipped."""
    html = '<span lang="it">Il presente <span lang="en">(present tense)</span> si usa spesso.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    # "present" should NOT be annotated because it's inside lang="en"
    word = _make_word(word="present")
    assert not _annotate_in_elements(els, word, None)
    assert "vocab-word" not in str(soup)


@pytest.mark.unit
def test_annotate_in_elements_nested_lang_annotates_outer():
    """Italian text in the outer span (not inside nested lang) gets annotated."""
    html = '<span lang="it">Il presente <span lang="en">(present tense)</span> si usa spesso.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="presente")
    assert _annotate_in_elements(els, word, None)
    assert 'data-word="presente"' in str(soup)


@pytest.mark.unit
def test_annotate_in_elements_skips_headings():
    """Text inside h1-h6 is not annotated."""
    html = '<span lang="it"><h2>Casa bella</h2><p>La casa è grande.</p></span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    str(soup)
    # Heading should not be annotated, but paragraph should
    h2 = soup.find("h2")
    assert "vocab-word" not in str(h2)
    p = soup.find("p")
    assert "vocab-word" in str(p)


@pytest.mark.unit
def test_annotate_in_elements_no_elements():
    """Empty element list means no annotation."""
    word = _make_word(word="casa")
    assert not _annotate_in_elements([], word, None)


@pytest.mark.unit
def test_annotate_in_elements_only_first_occurrence():
    """Only the first occurrence across all elements gets annotated."""
    html = '<span lang="it">La casa è bella.</span> <span lang="it">La casa è grande.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    _annotate_in_elements(els, word, None)
    assert str(soup).count("vocab-word") == 1


# --- lemmatize tests ---


@pytest.mark.unit
def test_lemmatize_includes_stop_words():
    """Stop words like 'sì', 'no', 'come', 'bene' are legitimate learner vocabulary."""
    lemmas = lemmatize("sì no come bene")
    assert "sì" in lemmas
    assert "no" in lemmas
    assert "come" in lemmas
    assert "bene" in lemmas


@pytest.mark.unit
def test_lemmatize_includes_two_char_words():
    """Two-character alphabetic tokens should be included (e.g. 'no', 'sì')."""
    lemmas = lemmatize("no")
    assert "no" in lemmas


@pytest.mark.unit
def test_lemmatize_excludes_single_char():
    """Single-character tokens (e.g. 'è' as standalone) should be excluded."""
    lemmas = lemmatize("è")
    assert len(lemmas) == 0


@pytest.mark.unit
def test_lemmatize_basic_conjugation():
    """Conjugated verbs should resolve to their lemma."""
    lemmas = lemmatize("mangio la pizza")
    assert "mangiare" in lemmas
    assert "pizza" in lemmas


@pytest.mark.unit
def test_lemmatize_excludes_non_alpha():
    """Punctuation and numbers should be excluded."""
    lemmas = lemmatize("ciao! 123 mondo.")
    assert "ciao" in lemmas
    assert "mondo" in lemmas
    assert "123" not in lemmas
    assert "!" not in lemmas
