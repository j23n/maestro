"""Unit tests for vocab/discover.py — annotation, text extraction, and lemmatization."""

import pytest
import simplemma
from types import SimpleNamespace

from maestro.vocab.discover import (
    _annotate_in_elements,
    discover,
    get_target_text,
    lemmatize,
)
from maestro.vocab import cache as _vocab_cache
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
def test_annotate_in_elements_annotates_headings():
    """Text inside h1-h6 IS annotated (headings get tooltips like any other text)."""
    html = '<span lang="it"><h2>Casa bella</h2><p>La casa è grande.</p></span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    h2 = soup.find("h2")
    assert "vocab-word" in str(h2)
    p = soup.find("p")
    assert "vocab-word" in str(p)


@pytest.mark.unit
def test_annotate_in_elements_no_elements():
    """Empty element list means no annotation."""
    word = _make_word(word="casa")
    assert not _annotate_in_elements([], word, None)


@pytest.mark.unit
def test_annotate_in_elements_all_occurrences():
    """All occurrences across all elements get annotated."""
    html = '<span lang="it">La casa è bella.</span> <span lang="it">La casa è grande.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    count = _annotate_in_elements(els, word, None)
    assert count == 2
    assert str(soup).count("vocab-word") == 2


@pytest.mark.unit
def test_annotate_in_elements_case_insensitive():
    """Annotation is case-insensitive."""
    soup, els = _make_soup_and_elements('<span lang="it">CASA bella</span>')
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    assert "vocab-word" in str(soup)


@pytest.mark.unit
def test_annotate_in_elements_word_boundary():
    """'casa' should not match inside 'casamento'."""
    soup, els = _make_soup_and_elements(
        '<span lang="it">Il casamento è vecchio.</span>'
    )
    word = _make_word(word="casa")
    assert not _annotate_in_elements(els, word, None)


@pytest.mark.unit
def test_annotate_in_elements_includes_senses_json():
    """Annotated span includes translation and senses data."""
    soup, els = _make_soup_and_elements('<span lang="it">Il tavolo è rotondo.</span>')
    word = _make_word(word="tavolo")
    wdef = _make_wdef(translation="table")
    _annotate_in_elements(els, word, wdef)
    result = str(soup)
    assert 'data-translation="table"' in result
    assert "data-senses" in result


@pytest.mark.unit
def test_annotate_in_elements_no_wdef_produces_empty_senses():
    """When wdef is None, data-senses should be an empty JSON array."""
    soup, els = _make_soup_and_elements('<span lang="it">Ho letto un libro.</span>')
    word = _make_word(word="libro")
    _annotate_in_elements(els, word, None)
    result = str(soup)
    assert "vocab-word" in result
    assert 'data-senses="[]"' in result or "data-senses='[]'" in result


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
def test_lemmatize_single_char_surface_with_valid_lemma():
    """Single-char surface forms like 'è' are included when lemma is valid (essere)."""
    lemmas = lemmatize("è")
    assert "essere" in lemmas


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


@pytest.mark.unit
def test_lemmatize_excludes_proper_nouns():
    """Proper nouns (PROPN) should not appear in lemmatize results."""
    lemmas = lemmatize("Marco va al mercato")
    assert "marco" not in lemmas
    assert "andare" in lemmas
    assert "mercato" in lemmas


# --- simplemma fallback sanity checks ---


@pytest.mark.unit
@pytest.mark.parametrize(
    "surface, expected",
    [
        ("chiamo", "chiamare"),
        ("parlo", "parlare"),
        ("mangio", "mangiare"),
        ("vado", "andare"),
        ("dormo", "dormire"),
        ("capisco", "capire"),
        ("bevo", "bere"),
        ("esco", "uscire"),
        ("giocavo", "giocare"),
        ("partirò", "partire"),
        ("mangerei", "mangiare"),
    ],
)
def test_simplemma_corrects_common_verb_forms(surface, expected):
    """simplemma should produce the correct infinitive for forms spaCy gets wrong."""
    assert simplemma.lemmatize(surface, lang="it").lower() == expected


# ---------------------------------------------------------------------------
# Observation tests — #104 user testing
#
# Document every known discover() failure so pipeline fixes can be validated.
# xfail = current broken behavior.  Plain @pytest.mark.unit = already correct.
# Easy to extend: just append a new pytest.param tuple.
# ---------------------------------------------------------------------------


# --- Lemmatization observations (lemmatize / lemmatize_with_pos) -----------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, expected, unexpected",
    [
        # -- Proper nouns should not produce lemmas (fixed: PROPN filter) --
        pytest.param(
            "Marco va al mercato",
            ["andare", "mercato"],
            ["marco"],
            id="propn-marco",
        ),
        pytest.param(
            "La signora Rossi",
            ["signore"],
            ["rossi"],
            id="propn-rossi",
        ),
        # -- Elision — apostrophe-split tokens --
        pytest.param(
            "cos'è questo",
            ["cosa", "essere", "questo"],
            [],
            id="elision-cosa",
        ),
        pytest.param(
            "mezz'ora di attesa",
            ["mezzo", "ora", "attesa"],
            [],
            marks=pytest.mark.xfail(
                reason="#104: spaCy lemma for mezz' is not alpha — filtered out, 'mezzo' missing"
            ),
            id="elision-mezzo",
        ),
        pytest.param(
            "l'acqua è fredda",
            ["acqua", "essere", "freddo"],
            [],
            id="elision-acqua",
        ),
        # -- Short tokens should be included --
        pytest.param(
            "è bello",
            ["essere", "bello"],
            [],
            id="short-token-essere",
        ),
        # -- POS disambiguation --
        pytest.param(
            "abito in Italia",
            ["abitare"],
            [],
            marks=pytest.mark.xfail(
                reason="#104: spaCy tags 'abito' as NOUN (dress) not VERB (to live)"
            ),
            id="pos-abito-verb",
        ),
        pytest.param(
            "mi dispiace molto",
            ["dispiacere"],
            [],
            id="pos-dispiacere",
        ),
        # -- More proper nouns (from #104/#106 user testing) --
        pytest.param(
            "Roma è bella",
            ["essere", "bello"],
            ["roma"],
            id="propn-roma",
        ),
        pytest.param(
            "Paolo mangia la pizza",
            ["mangiare", "pizza"],
            ["paolo"],
            id="propn-paolo",
        ),
        pytest.param(
            "un'amica di Roma",
            ["amico"],
            ["roma"],
            id="propn-roma-elision",
        ),
        # -- More elision cases --
        pytest.param(
            "dov'è il bagno",
            ["dove", "essere", "bagno"],
            [],
            id="elision-dove",
        ),
        pytest.param(
            "com'è il tempo",
            ["come", "essere", "tempo"],
            [],
            id="elision-come",
        ),
        pytest.param(
            "l'uomo è alto",
            ["uomo", "essere", "alto"],
            [],
            id="elision-uomo",
        ),
    ],
)
def test_lemmatize_observations(text, expected, unexpected):
    """Observation: lemmatize() should produce expected lemmas and exclude unexpected ones."""
    result = lemmatize(text)
    for word in expected:
        assert word in result, f"Expected {word!r} in lemmatize({text!r}), got {result}"
    for word in unexpected:
        assert word not in result, (
            f"Unexpected {word!r} found in lemmatize({text!r}), got {result}"
        )


# --- Text extraction observations (get_target_text) -----------------------


def _get_target_text_from_html(html: str) -> str:
    """Helper: parse HTML, find lang='it' elements, return get_target_text()."""
    soup = BeautifulSoup(html, "html.parser")
    lang_elements = soup.find_all(attrs={"lang": "it"})
    return get_target_text(lang_elements)


@pytest.mark.unit
@pytest.mark.parametrize(
    "html, expected_text",
    [
        # Inline tags should not split words (fixed: inline-aware text extraction)
        pytest.param(
            '<span lang="it"><b>a</b>more</span>',
            "amore",
            id="inline-tag-splitting",
        ),
        pytest.param(
            '<span lang="it">un <em>bel</em> giorno</span>',
            "un bel giorno",
            id="inline-tag-preserves-spaces",
        ),
        # Syllabization should come through as-is (filtering happens later)
        pytest.param(
            '<span lang="it">bi-na-rio</span>',
            "bi-na-rio",
            id="syllabization-passthrough",
        ),
        # Nested lang should be excluded
        pytest.param(
            '<span lang="it">casa <span lang="en">(house)</span> bella</span>',
            "casa bella",
            id="nested-lang-excluded",
        ),
        # Block elements should insert spaces
        pytest.param(
            '<div lang="it"><p>ciao</p><p>mondo</p></div>',
            "ciao mondo",
            id="block-elements-space",
        ),
        # More inline tag cases (from #104/#106)
        pytest.param(
            '<span lang="it"><i>buon</i>giorno</span>',
            "buongiorno",
            id="inline-tag-buongiorno",
        ),
        pytest.param(
            '<span lang="it"><strong>pre</strong>ndere un caffè</span>',
            "prendere un caffè",
            id="inline-tag-prendere",
        ),
        pytest.param(
            '<span lang="it">il <b>bi</b><b>glie</b><b>tto</b></span>',
            "il biglietto",
            id="inline-tag-biglietto-multi",
        ),
        # Block elements: headings + paragraphs
        pytest.param(
            '<div lang="it"><h2>Lezione uno</h2><p>Benvenuti alla lezione.</p></div>',
            "Lezione uno Benvenuti alla lezione.",
            id="block-heading-paragraph",
        ),
        # Inline <mark> should not split
        pytest.param(
            '<span lang="it">una <mark>parola</mark> importante</span>',
            "una parola importante",
            id="inline-mark-no-split",
        ),
        # Nested lang with inline context
        pytest.param(
            '<span lang="it">ciao <span lang="en">(hello)</span> come stai</span>',
            "ciao come stai",
            id="nested-lang-inline-excluded",
        ),
    ],
)
def test_get_target_text_observations(html, expected_text):
    """Observation: get_target_text() should produce clean text from HTML."""
    result = _get_target_text_from_html(html)
    assert result == expected_text


# --- Full pipeline observations (discover) ---------------------------------


def _make_vocab_word(word, pos="s.f.", entry_id=None):
    """Create a mock VocabularyWord for cache seeding."""
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization="",
        entry_id=entry_id or f"LM-{word.upper()}",
        senses=[],
        id=f"fake-{word}",
        audio_url=None,
    )


@pytest.fixture()
def seeded_cache():
    """Seed vocab cache with test words, clean up after."""
    words = {
        # Original test words
        "mercato": [_make_vocab_word("mercato", pos="s.m.")],
        "marcare": [_make_vocab_word("marcare", pos="v.tr.")],
        "amore": [_make_vocab_word("amore", pos="s.m.")],
        "dire": [_make_vocab_word("dire", pos="v.tr.")],
        "binario": [_make_vocab_word("binario", pos="s.m.")],
        "andare": [_make_vocab_word("andare", pos="v.intr.")],
        # Common vocabulary for pipeline tests
        "gatto": [_make_vocab_word("gatto", pos="s.m.")],
        "dormire": [_make_vocab_word("dormire", pos="v.intr.")],
        "divano": [_make_vocab_word("divano", pos="s.m.")],
        "volere": [_make_vocab_word("volere", pos="v.tr.")],
        "caffè": [_make_vocab_word("caffè", pos="s.m.")],
        "favore": [_make_vocab_word("favore", pos="s.m.")],
        "stazione": [_make_vocab_word("stazione", pos="s.f.")],
        "essere": [_make_vocab_word("essere", pos="v.intr.")],
        "lontano": [_make_vocab_word("lontano", pos="agg.")],
        "comprare": [_make_vocab_word("comprare", pos="v.tr.")],
        "biglietto": [_make_vocab_word("biglietto", pos="s.m.")],
        "treno": [_make_vocab_word("treno", pos="s.m.")],
        "partire": [_make_vocab_word("partire", pos="v.intr.")],
        "bello": [_make_vocab_word("bello", pos="agg.")],
        "dove": [_make_vocab_word("dove", pos="avv.")],
        "bagno": [_make_vocab_word("bagno", pos="s.m.")],
        "mangiare": [_make_vocab_word("mangiare", pos="v.tr.")],
        "pizza": [_make_vocab_word("pizza", pos="s.f.")],
        "uomo": [_make_vocab_word("uomo", pos="s.m.")],
        "alto": [_make_vocab_word("alto", pos="agg.")],
        "come": [_make_vocab_word("come", pos="avv.")],
        "stare": [_make_vocab_word("stare", pos="v.intr.")],
        "ciao": [_make_vocab_word("ciao", pos="inter.")],
        # PROPN trap words — in dictionary but should NOT be discovered as proper nouns
        "roma": [_make_vocab_word("roma", pos="s.f.")],
        "paolo": [_make_vocab_word("paolo", pos="s.m.")],
    }
    _vocab_cache.seed(words=words, defs={})
    yield
    _vocab_cache.invalidate()


@pytest.mark.unit
@pytest.mark.parametrize(
    "html, should_discover, should_not_discover",
    [
        # Proper nouns — Marco should not trigger "marcare" (fixed: PROPN filter)
        pytest.param(
            '<span lang="it">Marco va al mercato</span>',
            ["mercato"],
            ["marcare"],
            id="propn-marco-pipeline",
        ),
        # HTML tag splitting — text extraction now gives "amore" (not "a more"),
        # but annotation can't span across tag boundaries so no tooltip appears.
        # The word IS correctly discovered/matched; it just doesn't get annotated.
        pytest.param(
            '<span lang="it"><b>a</b>more mio</span>',
            ["amore"],
            [],
            marks=pytest.mark.xfail(
                reason="annotation can't span across inline tag boundaries (acceptable; to improve later)"
            ),
            id="inline-tag-amore",
        ),
        # Syllabization not discovered as base word
        pytest.param(
            '<span lang="it">si dice bi-na-rio</span>',
            ["dire"],
            ["binario"],
            id="syllabization-not-discovered",
        ),
        # Content without lang="it" should not trigger discovery
        pytest.param(
            '<div class="scoring">Good job!</div>',
            [],
            [],
            id="no-lang-no-discovery",
        ),
        # -- Full chain: conjugated surface → lemma → dictionary word --
        pytest.param(
            '<span lang="it">il gatto dorme sul divano</span>',
            ["gatto", "dormire", "divano"],
            [],
            id="chain-gatto-dorme-divano",
        ),
        pytest.param(
            '<span lang="it">vorrei un caffè per favore</span>',
            ["volere", "caffè", "favore"],
            [],
            id="chain-vorrei-caffe",
        ),
        pytest.param(
            '<span lang="it">la stazione è lontana</span>',
            ["stazione", "essere", "lontano"],
            [],
            id="chain-stazione-lontana",
        ),
        pytest.param(
            '<span lang="it">ho comprato due biglietti</span>',
            ["comprare", "biglietto"],
            [],
            id="chain-comprato-biglietti",
        ),
        pytest.param(
            '<span lang="it">il treno parte alle otto</span>',
            ["treno", "partire"],
            [],
            id="chain-treno-parte",
        ),
        # -- PROPN filter: proper nouns should NOT discover even if word is in dict --
        pytest.param(
            '<span lang="it">Roma è bella</span>',
            ["essere", "bello"],
            ["roma"],
            id="propn-roma-pipeline",
        ),
        pytest.param(
            '<span lang="it">Paolo mangia la pizza</span>',
            ["mangiare", "pizza"],
            ["paolo"],
            id="propn-paolo-pipeline",
        ),
        # -- Elision: apostrophe-split tokens resolve through full chain --
        pytest.param(
            '<span lang="it">dov\'è il bagno</span>',
            ["dove", "essere", "bagno"],
            [],
            id="elision-dove-pipeline",
        ),
        pytest.param(
            '<span lang="it">l\'uomo è alto</span>',
            ["uomo", "essere", "alto"],
            [],
            id="elision-uomo-pipeline",
        ),
        # -- Mixed: proper noun + elision + conjugation in one phrase --
        pytest.param(
            '<span lang="it">ciao come stai</span>',
            ["ciao", "come", "stare"],
            [],
            id="chain-ciao-come-stai",
        ),
        # -- Nested lang: English gloss should not pollute Italian discovery --
        pytest.param(
            '<span lang="it">il gatto <span lang="en">(the cat)</span> dorme</span>',
            ["gatto", "dormire"],
            [],
            id="nested-lang-cat-gloss",
        ),
    ],
)
async def test_discover_pipeline_observations(
    html, should_discover, should_not_discover, seeded_cache
):
    """Observation: discover() end-to-end with a seeded word_index."""
    result = await discover(html, student_id=None, create_cards=False)
    for word in should_discover:
        assert f'data-word="{word}"' in result, (
            f"Expected {word!r} to be discovered in {html!r}, output: {result}"
        )
    for word in should_not_discover:
        assert f'data-word="{word}"' not in result, (
            f"Unexpected {word!r} discovered in {html!r}, output: {result}"
        )
