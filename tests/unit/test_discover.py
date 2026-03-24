"""Unit tests for vocab/discover.py — matching, annotation, and text extraction.

Test layers:
- match_vocab_words: the main API boundary ("text + word_index → matches")
- get_target_text: HTML → plain text extraction
- _annotate_in_elements: plain text → annotated HTML
- discover(): integration (HTML scoping, data-no-save, multi-POS annotation)
- simplemma: smoke tests for the third-party fallback library
"""

import pytest
import simplemma
from types import SimpleNamespace

from maestro.vocab.discover import (
    VocabMatch,
    _annotate_in_elements,
    discover,
    get_target_text,
    match_vocab_words,
)
from maestro.vocab import cache as _vocab_cache
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vocab_word(word, pos="s.f.", entry_id=None):
    """Create a mock VocabularyWord for word_index / cache seeding."""
    pos_slug = pos.replace(".", "").replace("/", "")
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization="",
        entry_id=entry_id or f"LM-{word.upper()}",
        senses=[],
        id=f"fake-{word}-{pos_slug}",
        audio_url=None,
    )


def _make_word(
    word="casa", pos="s.f.", syllabization="cà-sa", entry_id="LM-001", senses=None
):
    """Create a mock VocabularyWord for _annotate_in_elements tests."""
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


def _make_soup_and_elements(html, lang="it"):
    """Parse HTML and return (soup, lang_elements)."""
    soup = BeautifulSoup(html, "html.parser")
    return soup, soup.find_all(attrs={"lang": lang})


# Shared word index for match_vocab_words and discover tests.
_TEST_WORD_INDEX = {
    # Nouns
    "mercato": [_make_vocab_word("mercato", pos="s.m.")],
    "gatto": [_make_vocab_word("gatto", pos="s.m.")],
    "divano": [_make_vocab_word("divano", pos="s.m.")],
    "caffè": [_make_vocab_word("caffè", pos="s.m.")],
    "favore": [_make_vocab_word("favore", pos="s.m.")],
    "stazione": [_make_vocab_word("stazione", pos="s.f.")],
    "biglietto": [_make_vocab_word("biglietto", pos="s.m.")],
    "treno": [_make_vocab_word("treno", pos="s.m.")],
    "bagno": [_make_vocab_word("bagno", pos="s.m.")],
    "pizza": [_make_vocab_word("pizza", pos="s.f.")],
    "uomo": [_make_vocab_word("uomo", pos="s.m.")],
    "tempo": [_make_vocab_word("tempo", pos="s.m.")],
    "amore": [_make_vocab_word("amore", pos="s.m.")],
    "signore": [_make_vocab_word("signore", pos="s.m.")],
    "amico": [_make_vocab_word("amico", pos="s.m.")],
    "acqua": [_make_vocab_word("acqua", pos="s.f.")],
    "binario": [_make_vocab_word("binario", pos="s.m.")],
    "cosa": [_make_vocab_word("cosa", pos="s.f.")],
    "ora": [_make_vocab_word("ora", pos="s.f.")],
    "attesa": [_make_vocab_word("attesa", pos="s.f.")],
    "ragazzo": [_make_vocab_word("ragazzo", pos="s.m.")],
    "ragazza": [_make_vocab_word("ragazza", pos="s.f.")],
    "libro": [_make_vocab_word("libro", pos="s.m.")],
    "porta": [_make_vocab_word("porta", pos="s.f.")],
    # Verbs
    "marcare": [_make_vocab_word("marcare", pos="v.tr.")],
    "dormire": [_make_vocab_word("dormire", pos="v.intr.")],
    "volere": [_make_vocab_word("volere", pos="v.tr.")],
    "essere": [_make_vocab_word("essere", pos="v.intr.")],
    "comprare": [_make_vocab_word("comprare", pos="v.tr.")],
    "partire": [_make_vocab_word("partire", pos="v.intr.")],
    "mangiare": [_make_vocab_word("mangiare", pos="v.tr.")],
    "stare": [_make_vocab_word("stare", pos="v.intr.")],
    "dire": [_make_vocab_word("dire", pos="v.tr.")],
    "andare": [_make_vocab_word("andare", pos="v.intr.")],
    "abitare": [_make_vocab_word("abitare", pos="v.intr.")],
    "dispiacere": [_make_vocab_word("dispiacere", pos="v.intr.")],
    "suonare": [_make_vocab_word("suonare", pos="v.tr.")],
    # Adjectives / adverbs
    "bello": [_make_vocab_word("bello", pos="agg.")],
    "lontano": [_make_vocab_word("lontano", pos="agg.")],
    "alto": [_make_vocab_word("alto", pos="agg.")],
    "freddo": [_make_vocab_word("freddo", pos="agg.")],
    "mezzo": [_make_vocab_word("mezzo", pos="agg.")],
    "questo": [_make_vocab_word("questo", pos="agg.")],
    # Other
    "ciao": [_make_vocab_word("ciao", pos="inter.")],
    "come": [_make_vocab_word("come", pos="avv.")],
    "dove": [_make_vocab_word("dove", pos="avv.")],
    # Multi-POS: "piano" as noun (piano/floor) and adjective (quiet/slow)
    "piano": [
        _make_vocab_word("piano", pos="s.m."),
        _make_vocab_word("piano", pos="agg."),
    ],
    # PROPN trap words — in dictionary but should NOT be discovered as proper nouns
    "roma": [_make_vocab_word("roma", pos="s.f.")],
    "paolo": [_make_vocab_word("paolo", pos="s.m.")],
}


@pytest.fixture()
def seeded_cache():
    """Seed global vocab cache with _TEST_WORD_INDEX for discover() tests."""
    _vocab_cache.seed(words=_TEST_WORD_INDEX, defs={})
    yield
    _vocab_cache.invalidate()


# ---------------------------------------------------------------------------
# match_vocab_words — the main API boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, expected_words, unexpected_words",
    [
        # -- Proper nouns: should NOT match even when headword is in word_index --
        pytest.param(
            "Marco va al mercato",
            ["mercato"],
            ["marcare"],
            id="propn-marco",
        ),
        pytest.param(
            "La signora Rossi",
            ["signore"],
            [],
            id="propn-rossi",
        ),
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
        # -- Elision: apostrophe-split tokens --
        pytest.param(
            "cos'è questo",
            ["cosa", "essere", "questo"],
            [],
            id="elision-cosa",
        ),
        pytest.param(
            "Che cos'è? Che cos'è questo? Che cos'è quella cosa?",
            ["cosa", "essere", "questo"],
            [],
            id="elision-cosa-repeated",
        ),
        pytest.param(
            "mezz'ora di attesa",
            ["mezzo", "ora", "attesa"],
            [],
            marks=pytest.mark.xfail(
                reason="#104: spaCy lemma 'mezz'' not resolved, simplemma can't recover"
            ),
            id="elision-mezzo",
        ),
        pytest.param(
            "l'acqua è fredda",
            ["acqua", "essere", "freddo"],
            [],
            id="elision-acqua",
        ),
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
        # -- Short tokens / stop words --
        pytest.param(
            "è bello",
            ["essere", "bello"],
            [],
            id="short-token-essere",
        ),
        # -- Conjugated surface → lemma → dictionary word --
        pytest.param(
            "il gatto dorme sul divano",
            ["gatto", "dormire", "divano"],
            [],
            id="chain-gatto-dorme-divano",
        ),
        pytest.param(
            "vorrei un caffè per favore",
            ["volere", "caffè", "favore"],
            [],
            id="chain-vorrei-caffe",
        ),
        pytest.param(
            "la stazione è lontana",
            ["stazione", "essere", "lontano"],
            [],
            id="chain-stazione-lontana",
        ),
        pytest.param(
            "ho comprato due biglietti",
            ["comprare", "biglietto"],
            [],
            id="chain-comprato-biglietti",
        ),
        pytest.param(
            "il treno parte alle otto",
            ["treno", "partire"],
            [],
            id="chain-treno-parte",
        ),
        pytest.param(
            "ciao come stai",
            ["ciao", "come", "stare"],
            [],
            id="chain-ciao-come-stai",
        ),
        # -- POS disambiguation --
        # spaCy tags "abito" as NOUN, but simplemma fallback resolves to "abitare"
        pytest.param(
            "abito in Italia",
            ["abitare"],
            [],
            id="pos-abito-verb",
        ),
        pytest.param(
            "mi dispiace molto",
            ["dispiacere"],
            [],
            id="pos-dispiacere",
        ),
        # -- Syllabization: hyphenated pronunciation guides are not words --
        pytest.param(
            "si dice bi-na-rio",
            ["dire"],
            ["binario"],
            id="syllabization-not-discovered",
        ),
    ],
)
def test_match_vocab_words_observations(text, expected_words, unexpected_words):
    """match_vocab_words() should find correct dictionary entries from Italian text."""
    matches = match_vocab_words(text, _TEST_WORD_INDEX)
    matched_words = {m.word.word for m in matches}
    for w in expected_words:
        assert w in matched_words, (
            f"Expected {w!r} in match_vocab_words({text!r}), got {matched_words}"
        )
    for w in unexpected_words:
        assert w not in matched_words, (
            f"Unexpected {w!r} in match_vocab_words({text!r}), got {matched_words}"
        )


@pytest.mark.unit
def test_match_vocab_words_returns_vocab_match():
    """match_vocab_words() should return a list of VocabMatch dataclasses."""
    matches = match_vocab_words("il gatto dorme", _TEST_WORD_INDEX)
    assert isinstance(matches, list)
    assert all(isinstance(m, VocabMatch) for m in matches)


@pytest.mark.unit
def test_match_vocab_words_surface_forms():
    """Each VocabMatch should carry the inflected surface forms seen in the text."""
    matches = match_vocab_words("i gatti dormono", _TEST_WORD_INDEX)
    gatto_match = next(m for m in matches if m.word.word == "gatto")
    assert "gatti" in gatto_match.surface_forms


@pytest.mark.unit
def test_match_vocab_words_dedup():
    """Same lemma + same dictionary entry appearing twice → only one VocabMatch."""
    matches = match_vocab_words("il gatto e il gatto", _TEST_WORD_INDEX)
    gatto_matches = [m for m in matches if m.word.word == "gatto"]
    assert len(gatto_matches) == 1


@pytest.mark.unit
def test_match_vocab_words_multi_pos():
    """Same lemma with different POS should return multiple VocabMatch entries."""
    matches = match_vocab_words("suono il piano piano", _TEST_WORD_INDEX)
    piano_matches = [m for m in matches if m.lemma == "piano"]
    assert len(piano_matches) == 2, (
        f"Expected 2 piano matches (noun + adj), got {len(piano_matches)}: "
        f"{[(m.word.part_of_speech, m.pos) for m in piano_matches]}"
    )
    pos_set = {m.word.part_of_speech for m in piano_matches}
    assert "s.m." in pos_set
    assert "agg." in pos_set


@pytest.mark.unit
def test_match_vocab_words_default_word_index(seeded_cache):
    """match_vocab_words() should use the global cache when word_index is omitted."""
    matches = match_vocab_words("il gatto dorme")
    assert any(m.word.word == "gatto" for m in matches)


# ---------------------------------------------------------------------------
# simplemma smoke tests — validate third-party library behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "surface, expected",
    [
        ("capisco", "capire"),
        ("vado", "andare"),
        ("bevo", "bere"),
        ("esco", "uscire"),
        ("mangerei", "mangiare"),
    ],
)
def test_simplemma_smoke(surface, expected):
    """simplemma should produce correct infinitives for irregular verb forms."""
    assert simplemma.lemmatize(surface, lang="it").lower() == expected


# ---------------------------------------------------------------------------
# get_target_text — HTML text extraction
# ---------------------------------------------------------------------------


def _get_target_text_from_html(html: str) -> str:
    """Helper: parse HTML, find lang='it' elements, return get_target_text()."""
    soup = BeautifulSoup(html, "html.parser")
    lang_elements = soup.find_all(attrs={"lang": "it"})
    return get_target_text(lang_elements)


@pytest.mark.unit
@pytest.mark.parametrize(
    "html, expected_text",
    [
        # Inline tags should not split words
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
        pytest.param(
            '<span lang="it">una <mark>parola</mark> importante</span>',
            "una parola importante",
            id="inline-mark-no-split",
        ),
        # Syllabization comes through as-is (filtering happens in matching)
        pytest.param(
            '<span lang="it">bi-na-rio</span>',
            "bi-na-rio",
            id="syllabization-passthrough",
        ),
        # Nested lang excluded
        pytest.param(
            '<span lang="it">casa <span lang="en">(house)</span> bella</span>',
            "casa bella",
            id="nested-lang-excluded",
        ),
        pytest.param(
            '<span lang="it">ciao <span lang="en">(hello)</span> come stai</span>',
            "ciao come stai",
            id="nested-lang-inline-excluded",
        ),
        # Block elements insert spaces
        pytest.param(
            '<div lang="it"><p>ciao</p><p>mondo</p></div>',
            "ciao mondo",
            id="block-elements-space",
        ),
        pytest.param(
            '<div lang="it"><h2>Lezione uno</h2><p>Benvenuti alla lezione.</p></div>',
            "Lezione uno Benvenuti alla lezione.",
            id="block-heading-paragraph",
        ),
        # Multiple separate lang elements
        pytest.param(
            '<p>use <span lang="it"><strong>il</strong></span> before masculine nouns and <span lang="it"><strong>la</strong></span> before feminine nouns.</p>',
            "il la",
            id="multi-lang-elements-separated",
        ),
        pytest.param(
            (
                "<p>"
                '- <span lang="it"><em>il ragazzo</em></span> (the boy) — masculine, so we use <span lang="it"><strong>il</strong></span><br>'
                '- <span lang="it"><em>la ragazza</em></span> (the girl) — feminine, so we use <span lang="it"><strong>la</strong></span><br>'
                '- <span lang="it"><em>il libro</em></span> (the book) — masculine, so we use <span lang="it"><strong>il</strong></span><br>'
                '- <span lang="it"><em>la porta</em></span> (the door) — feminine, so we use <span lang="it"><strong>la</strong></span>'
                "</p>"
            ),
            "il ragazzo il la ragazza la il libro il la porta la",
            id="grammar-page-definite-articles",
        ),
    ],
)
def test_get_target_text(html, expected_text):
    """get_target_text() should produce clean text from lang-tagged HTML."""
    assert _get_target_text_from_html(html) == expected_text


# ---------------------------------------------------------------------------
# _annotate_in_elements — HTML annotation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_annotate_target_lang():
    """Text in target-language span gets annotated."""
    soup, els = _make_soup_and_elements('<span lang="it">La casa è grande.</span>')
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    assert "vocab-word" in str(soup)
    assert 'data-word="casa"' in str(soup)


@pytest.mark.unit
def test_annotate_skips_non_target():
    """Text in non-target-language span is not annotated."""
    html = '<span lang="en">The house is big.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="house")
    assert not els
    assert not _annotate_in_elements(els, word, None)
    assert "vocab-word" not in str(soup)


@pytest.mark.unit
def test_annotate_mixed_lang():
    """Only target-lang text gets annotated in mixed content."""
    html = '<span lang="en">Say </span><span lang="it">ciao</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="ciao")
    assert _annotate_in_elements(els, word, None)
    result = str(soup)
    assert "vocab-word" in result
    assert 'data-word="ciao"' in result


@pytest.mark.unit
def test_annotate_nested_lang_skips_inner():
    """English gloss nested inside Italian span is skipped."""
    html = '<span lang="it">Il presente <span lang="en">(present tense)</span> si usa spesso.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="present")
    assert not _annotate_in_elements(els, word, None)
    assert "vocab-word" not in str(soup)


@pytest.mark.unit
def test_annotate_nested_lang_annotates_outer():
    """Italian text in the outer span (not inside nested lang) gets annotated."""
    html = '<span lang="it">Il presente <span lang="en">(present tense)</span> si usa spesso.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="presente")
    assert _annotate_in_elements(els, word, None)
    assert 'data-word="presente"' in str(soup)


@pytest.mark.unit
def test_annotate_headings():
    """Text inside h1-h6 IS annotated (headings get tooltips like any other text)."""
    html = '<span lang="it"><h2>Casa bella</h2><p>La casa è grande.</p></span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    assert "vocab-word" in str(soup.find("h2"))
    assert "vocab-word" in str(soup.find("p"))


@pytest.mark.unit
def test_annotate_no_elements():
    """Empty element list means no annotation."""
    word = _make_word(word="casa")
    assert not _annotate_in_elements([], word, None)


@pytest.mark.unit
def test_annotate_all_occurrences():
    """All occurrences across all elements get annotated."""
    html = '<span lang="it">La casa è bella.</span> <span lang="it">La casa è grande.</span>'
    soup, els = _make_soup_and_elements(html, lang="it")
    word = _make_word(word="casa")
    count = _annotate_in_elements(els, word, None)
    assert count == 2
    assert str(soup).count("vocab-word") == 2


@pytest.mark.unit
def test_annotate_case_insensitive():
    """Annotation is case-insensitive."""
    soup, els = _make_soup_and_elements('<span lang="it">CASA bella</span>')
    word = _make_word(word="casa")
    assert _annotate_in_elements(els, word, None)
    assert "vocab-word" in str(soup)


@pytest.mark.unit
def test_annotate_word_boundary():
    """'casa' should not match inside 'casamento'."""
    soup, els = _make_soup_and_elements(
        '<span lang="it">Il casamento è vecchio.</span>'
    )
    word = _make_word(word="casa")
    assert not _annotate_in_elements(els, word, None)


@pytest.mark.unit
def test_annotate_includes_senses_json():
    """Annotated span includes translation and senses data."""
    soup, els = _make_soup_and_elements('<span lang="it">Il tavolo è rotondo.</span>')
    word = _make_word(word="tavolo")
    wdef = _make_wdef(translation="table")
    _annotate_in_elements(els, word, wdef)
    result = str(soup)
    assert 'data-translation="table"' in result
    assert "data-senses" in result


@pytest.mark.unit
def test_annotate_no_wdef_produces_empty_senses():
    """When wdef is None, data-senses should be an empty JSON array."""
    soup, els = _make_soup_and_elements('<span lang="it">Ho letto un libro.</span>')
    word = _make_word(word="libro")
    _annotate_in_elements(els, word, None)
    result = str(soup)
    assert "vocab-word" in result
    assert 'data-senses="[]"' in result or "data-senses='[]'" in result


@pytest.mark.unit
def test_annotate_max_count():
    """max_count limits the number of annotations."""
    html = (
        '<span lang="it">La casa è bella. La casa è grande. La casa è vecchia.</span>'
    )
    soup, els = _make_soup_and_elements(html)
    word = _make_word(word="casa")
    count = _annotate_in_elements(els, word, None, max_count=2)
    assert count == 2
    assert str(soup).count("vocab-word") == 2


# ---------------------------------------------------------------------------
# discover() — integration tests (HTML-specific concerns only)
#
# Matching logic is tested via match_vocab_words above.  These tests cover
# behaviour that only discover() can exercise: HTML scoping, annotation
# across tag boundaries, data-no-save, and multi-POS annotation.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_discover_no_lang_returns_unchanged(seeded_cache):
    """Content without lang attributes should pass through unchanged."""
    html = '<div class="scoring">Good job!</div>'
    assert await discover(html, student_id=None, create_cards=False) == html


@pytest.mark.unit
async def test_discover_main_scoping(seeded_cache):
    """When <main> is present, only lang elements inside it are discovered."""
    html = (
        '<nav><span lang="it">ciao</span></nav>'
        '<main><span lang="it">il gatto dorme</span></main>'
    )
    result = await discover(html, student_id=None, create_cards=False)
    assert 'data-word="gatto"' in result
    assert 'data-word="ciao"' not in result


@pytest.mark.unit
async def test_discover_fragment_mode(seeded_cache):
    """Without <main>, all lang elements are discovered (HTMX fragment mode)."""
    html = '<span lang="it">il gatto dorme</span>'
    result = await discover(html, student_id=None, create_cards=False)
    assert 'data-word="gatto"' in result


@pytest.mark.unit
async def test_discover_inline_tag_amore(seeded_cache):
    """Annotation can't span across inline tag boundaries (known limitation)."""
    result = await discover(
        '<span lang="it"><b>a</b>more mio</span>',
        student_id=None,
        create_cards=False,
    )
    # The word IS matched (text extraction gives "amore"), but annotation
    # can't wrap across <b> boundary, so no data-word appears.
    assert 'data-word="amore"' not in result


@pytest.mark.unit
async def test_discover_nested_lang_excluded(seeded_cache):
    """English gloss nested inside Italian span should not pollute discovery."""
    result = await discover(
        '<span lang="it">il gatto <span lang="en">(the cat)</span> dorme</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="gatto"' in result
    assert 'data-word="dormire"' in result


@pytest.mark.unit
async def test_discover_grammar_page_multi_span(seeded_cache):
    """Multiple separate lang="it" spans should each be annotated independently."""
    html = (
        "<p>"
        '- <span lang="it"><em>il ragazzo</em></span> (the boy)<br>'
        '- <span lang="it"><em>la ragazza</em></span> (the girl)<br>'
        '- <span lang="it"><em>il libro</em></span> (the book)<br>'
        '- <span lang="it"><em>la porta</em></span> (the door)'
        "</p>"
    )
    result = await discover(html, student_id=None, create_cards=False)
    for word in ("ragazzo", "ragazza", "libro", "porta"):
        assert f'data-word="{word}"' in result, f"{word!r} not annotated"


@pytest.mark.unit
async def test_discover_multi_pos_annotation(seeded_cache):
    """Multi-POS words should get different annotations for each occurrence."""
    result = await discover(
        '<span lang="it">suono il piano piano</span>',
        student_id=None,
        create_cards=False,
    )
    assert result.count('data-word="piano"') == 2
    assert 'data-pos="s.m."' in result
    assert 'data-pos="agg."' in result
