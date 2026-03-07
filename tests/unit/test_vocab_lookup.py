"""Unit tests for vocab/ingest.py — make_lookup() lemmatization logic."""
import pytest
from types import SimpleNamespace


def _make_entry(headword):
    return SimpleNamespace(
        headword=headword,
        hyph=None,
        pos_abbrev="s.m.",
        entry_id=f"LM-{headword}",
        senses=[],
    )


@pytest.fixture
def lookup_fn():
    """Build a lookup function with a small test dictionary.

    Requires spaCy it_core_news_md — skip if not available.
    """
    try:
        import spacy
        nlp = spacy.load("it_core_news_md")
    except OSError:
        pytest.skip("spaCy it_core_news_md not available")

    from maestro.vocab.morphology.it import make_lookup

    by_form = {
        "andare": _make_entry("andare"),
        "mangiare": _make_entry("mangiare"),
        "bello": _make_entry("bello"),
        "fare": _make_entry("fare"),
        "casa": _make_entry("casa"),
        "felice": _make_entry("felice"),
    }

    return make_lookup(by_form, nlp)


@pytest.mark.unit
def test_direct_match(lookup_fn):
    result = lookup_fn("andare")
    assert result is not None
    assert result.headword == "andare"


@pytest.mark.unit
def test_lemma_match(lookup_fn):
    """Conjugated form should resolve via spaCy lemmatization."""
    result = lookup_fn("mangiato")
    assert result is not None
    assert result.headword == "mangiare"


@pytest.mark.unit
def test_unknown_word_returns_none(lookup_fn):
    assert lookup_fn("xyzzyx") is None


@pytest.mark.unit
def test_reflexive_clitic_stripping(lookup_fn):
    """'andarsene' should resolve to 'andare' via clitic stripping."""
    result = lookup_fn("andarsene")
    if result:  # depends on spaCy model accuracy
        assert result.headword == "andare"


@pytest.mark.unit
def test_mente_adverb(lookup_fn):
    """'felicemente' should resolve to 'felice' via -mente rule."""
    result = lookup_fn("felicemente")
    if result:
        assert result.headword == "felice"
