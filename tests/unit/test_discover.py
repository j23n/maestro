"""Unit tests for vocab/discover.py — matching, annotation, and text extraction.

Test layers:
- match_vocab_words: the main API boundary ("text + word_index → matches")
- get_target_text: HTML → plain text extraction
- _annotate_in_elements: plain text → annotated HTML
- discover(): integration (HTML scoping, data-no-save, multi-POS annotation)
- simplemma: smoke tests for the third-party fallback library
"""

from unittest.mock import patch

import pytest
import simplemma
from types import SimpleNamespace

from maestro.vocab.discover import (
    TokenOccurrence,
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
    "grande": [_make_vocab_word("grande", pos="agg.")],
    "mezzo": [_make_vocab_word("mezzo", pos="agg.")],
    "questo": [_make_vocab_word("questo", pos="agg.")],
    # Articles / determiners
    "il": [_make_vocab_word("il", pos="art.")],
    "uno": [_make_vocab_word("uno", pos="art.")],
    # Prepositions
    "di": [_make_vocab_word("di", pos="prep.")],
    "per": [_make_vocab_word("per", pos="prep.")],
    "in": [_make_vocab_word("in", pos="prep.")],
    # Conjunctions / pronouns
    "che": [_make_vocab_word("che", pos="cong.")],
    # Adjectives (continued)
    "quello": [_make_vocab_word("quello", pos="agg.")],
    # Adverbs (continued)
    "molto": [_make_vocab_word("molto", pos="avv.")],
    # Numerals
    "due": [_make_vocab_word("due", pos="num.")],
    "otto": [_make_vocab_word("otto", pos="num.")],
    # Verbs (continued)
    "avere": [_make_vocab_word("avere", pos="v.tr.")],
    # Other
    "ciao": [_make_vocab_word("ciao", pos="inter.")],
    "come": [_make_vocab_word("come", pos="avv.")],
    "dove": [_make_vocab_word("dove", pos="avv.")],
    # Multi-POS: "piano" as noun (piano/floor) and adjective (quiet/slow)
    "piano": [
        _make_vocab_word("piano", pos="s.m."),
        _make_vocab_word("piano", pos="agg."),
    ],
    # Contractions (preposizioni articolate) — headwords in the EPUB dictionary
    "sul": [_make_vocab_word("sul", pos="prep. articolata")],
    "nella": [_make_vocab_word("nella", pos="prep. articolata")],
    "al": [_make_vocab_word("al", pos="prep. articolata")],
    "del": [_make_vocab_word("del", pos="prep. articolata")],
    "dalle": [_make_vocab_word("dalle", pos="prep. articolata")],
    # PROPN trap words — in dictionary but should NOT be discovered as proper nouns
    "roma": [_make_vocab_word("roma", pos="s.f.")],
    "paolo": [_make_vocab_word("paolo", pos="s.m.")],
}

# Phrase index for phrase-matching tests.
_TEST_PHRASE_INDEX = {
    "per favore": [_make_vocab_word("per favore", pos="loc.")],
    "mi chiamo": [_make_vocab_word("mi chiamo", pos="loc.")],
    "a destra": [_make_vocab_word("a destra", pos="loc.")],
    "quanto costa": [_make_vocab_word("quanto costa", pos="loc.")],
    # Phrases ending in punctuation — \b boundary bug
    "un po'": [_make_vocab_word("un po'", pos="loc.")],
    "come si chiama?": [_make_vocab_word("come si chiama?", pos="loc.")],
    "che ore sono?": [_make_vocab_word("che ore sono?", pos="loc.")],
}


@pytest.fixture()
def seeded_cache():
    """Seed global vocab cache with _TEST_WORD_INDEX for discover() tests."""
    _vocab_cache.seed(words=_TEST_WORD_INDEX, defs={})
    yield
    _vocab_cache.invalidate()


@pytest.fixture()
def seeded_cache_with_phrases():
    """Seed global vocab cache with words AND phrases for discover() tests."""
    _vocab_cache.seed(words=_TEST_WORD_INDEX, defs={}, phrases=_TEST_PHRASE_INDEX)
    yield
    _vocab_cache.invalidate()


# ---------------------------------------------------------------------------
# match_vocab_words — the main API boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, expected_words",
    [
        # -- Proper nouns: should NOT match even when headword is in word_index --
        pytest.param(
            "Marco va al mercato",
            {"andare", "al", "mercato"},
            id="propn-marco",
        ),
        pytest.param(
            "La signora Rossi",
            {"il", "signore"},
            id="propn-rossi",
        ),
        pytest.param(
            "Roma è bella",
            {"essere", "bello"},
            id="propn-roma",
        ),
        pytest.param(
            "Paolo mangia la pizza",
            {"il", "mangiare", "pizza"},
            id="propn-paolo",
        ),
        pytest.param(
            "un'amica di Roma",
            {"uno", "amico", "di"},
            id="propn-roma-elision",
        ),
        # -- Elision: apostrophe-split tokens --
        pytest.param(
            "cos'è questo",
            {"cosa", "essere", "questo"},
            id="elision-cosa",
        ),
        pytest.param(
            "Che cos'è? Che cos'è questo? Che cos'è quella cosa?",
            {"che", "cosa", "essere", "questo", "quello"},
            id="elision-cosa-repeated",
        ),
        pytest.param(
            "mezz'ora di attesa",
            {"mezzo", "ora", "di", "attesa"},
            id="elision-mezzo",
        ),
        pytest.param(
            "un grand'uomo",
            {"uno", "grande", "uomo"},
            id="elision-grande",
        ),
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
        pytest.param(
            "com'è il tempo",
            {"come", "essere", "il", "tempo"},
            id="elision-come",
        ),
        pytest.param(
            "l'uomo è alto",
            {"il", "uomo", "essere", "alto"},
            id="elision-uomo",
        ),
        # -- Short tokens / stop words --
        pytest.param(
            "è bello",
            {"essere", "bello"},
            id="short-token-essere",
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
            {"il", "stazione", "essere", "lontano"},
            id="chain-stazione-lontana",
        ),
        pytest.param(
            "ho comprato due biglietti",
            {"avere", "comprare", "due", "biglietto"},
            id="chain-comprato-biglietti",
        ),
        pytest.param(
            "il treno parte alle otto",
            {"il", "treno", "partire", "otto"},
            id="chain-treno-parte",
        ),
        pytest.param(
            "ciao come stai",
            {"ciao", "come", "stare"},
            id="chain-ciao-come-stai",
        ),
        # -- POS disambiguation --
        # spaCy tags "abito" as NOUN, but simplemma fallback resolves to "abitare"
        pytest.param(
            "abito in Italia",
            {"abitare", "in"},
            id="pos-abito-verb",
        ),
        pytest.param(
            "mi dispiace molto",
            {"dispiacere", "molto"},
            id="pos-dispiacere",
        ),
        # -- Syllabization: hyphenated pronunciation guides are not words --
        pytest.param(
            "si dice bi-na-rio",
            {"dire"},
            id="syllabization-not-discovered",
        ),
        # -- Contractions (preposizioni articolate) --
        pytest.param(
            "nella stazione",
            {"nella", "stazione"},
            id="contraction-nella",
        ),
        pytest.param(
            "al mercato dalle otto",
            {"al", "mercato", "dalle", "otto"},
            id="contraction-al-dalle",
        ),
    ],
)
def test_match_vocab_words_observations(text, expected_words):
    """match_vocab_words() should produce exactly the expected set of dictionary matches."""
    matches = match_vocab_words(text, _TEST_WORD_INDEX)
    matched_words = {m.word.word for m in matches}
    assert matched_words == expected_words, (
        f"match_vocab_words({text!r})\n"
        f"  expected: {sorted(expected_words)}\n"
        f"  got:      {sorted(matched_words)}"
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
    # Each match should have exactly one occurrence
    for m in piano_matches:
        assert len(m.occurrences) == 1, (
            f"Expected 1 occurrence per multi-POS match, got {len(m.occurrences)}"
        )
        assert m.occurrences[0].surface == "piano"


@pytest.mark.unit
def test_match_vocab_words_occurrence_index():
    """Each VocabMatch should carry TokenOccurrences with correct token indices."""
    matches = match_vocab_words("il gatto dorme sul divano", _TEST_WORD_INDEX)
    # All single-POS matches — each should have exactly one occurrence
    for m in matches:
        assert len(m.occurrences) >= 1
        assert all(isinstance(occ, TokenOccurrence) for occ in m.occurrences)
    # Token indices should be unique across all occurrences
    all_indices = [occ.index for m in matches for occ in m.occurrences]
    assert len(all_indices) == len(set(all_indices)), "Token indices must be unique"


@pytest.mark.unit
def test_match_vocab_words_dedup_groups_occurrences():
    """Same lemma + same dictionary entry appearing twice → one VocabMatch with two occurrences."""
    matches = match_vocab_words("il gatto e il gatto", _TEST_WORD_INDEX)
    gatto_matches = [m for m in matches if m.word.word == "gatto"]
    assert len(gatto_matches) == 1
    assert len(gatto_matches[0].occurrences) == 2
    assert gatto_matches[0].occurrences[0].index < gatto_matches[0].occurrences[1].index


@pytest.mark.unit
def test_match_vocab_words_per_pos_surface_forms():
    """Multi-POS matches should carry only their own POS's surface forms."""
    # "piano" as both noun and adjective — each match should have surface "piano"
    # but critically, if we had different surface forms per POS, they wouldn't leak.
    matches = match_vocab_words("suono il piano piano", _TEST_WORD_INDEX)
    piano_matches = [m for m in matches if m.lemma == "piano"]
    noun_match = next(m for m in piano_matches if m.word.part_of_speech == "s.m.")
    adj_match = next(m for m in piano_matches if m.word.part_of_speech == "agg.")
    # Each carries only its own occurrence's surface
    assert noun_match.surface_forms == ["piano"]
    assert adj_match.surface_forms == ["piano"]
    # POS on each occurrence matches what spaCy assigned
    assert noun_match.occurrences[0].pos == "NOUN"
    assert adj_match.occurrences[0].pos == "ADJ"


@pytest.mark.unit
def test_match_vocab_words_default_word_index(seeded_cache):
    """match_vocab_words() should use the global cache when word_index is omitted."""
    matches = match_vocab_words("il gatto dorme")
    assert any(m.word.word == "gatto" for m in matches)


# ---------------------------------------------------------------------------
# cache.get_definition — A0 fallback behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cache_get_definition_a0_fallback_to_a1():
    """A0 lookup with no A0 def should return A1 def with translation only."""
    a1_def = _make_wdef(translation="cat")
    _vocab_cache.seed(defs={("word-1", "A1"): a1_def})
    result = _vocab_cache.get_definition("word-1", "A0")
    assert result is not None
    assert result.translation == "cat"
    # Definition text should be stripped
    assert all(s.definition == "" for s in result.senses)
    # Translation preserved
    assert all(s.translation == "cat" for s in result.senses)
    # Examples stripped
    assert all(s.examples == [] for s in result.senses)
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a0_deduplicates_translations():
    """A0 fallback should deduplicate senses with the same translation."""
    a1_def = _make_wdef(
        translation="door",
        senses=[
            SimpleNamespace(
                definition="apertura", translation="door (opening)", examples=[]
            ),
            SimpleNamespace(
                definition="porta di legno", translation="door", examples=[]
            ),
            SimpleNamespace(definition="ingresso", translation="door", examples=[]),
        ],
    )
    _vocab_cache.seed(defs={("word-1", "A1"): a1_def})
    result = _vocab_cache.get_definition("word-1", "A0")
    translations = [s.translation for s in result.senses]
    assert translations == ["door (opening)", "door"]
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a0_with_own_def():
    """A0 lookup with an A0 def should return it directly (no fallback)."""
    a0_def = _make_wdef(
        translation="hello, goodbye",
        senses=[
            SimpleNamespace(definition="", translation="hello, goodbye", examples=[])
        ],
    )
    _vocab_cache.seed(defs={("word-1", "A0"): a0_def})
    result = _vocab_cache.get_definition("word-1", "A0")
    assert result is a0_def  # exact same object, not a copy
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a0_no_a1_returns_none():
    """A0 lookup with no A0 or A1 def should return None."""
    _vocab_cache.seed(defs={})
    result = _vocab_cache.get_definition("word-1", "A0")
    assert result is None
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a1_no_fallback():
    """A1 lookup with no A1 def should return None (no fallback for non-A0)."""
    a2_def = _make_wdef(translation="cat")
    _vocab_cache.seed(defs={("word-1", "A2"): a2_def})
    result = _vocab_cache.get_definition("word-1", "A1")
    assert result is None
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_phrase_index_seeded():
    """seed() with phrases param populates phrase_index()."""
    phrases = {"per favore": [_make_vocab_word("per favore", pos="loc.")]}
    _vocab_cache.seed(phrases=phrases)
    assert _vocab_cache.phrase_index() == phrases
    _vocab_cache.invalidate()


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


@pytest.mark.unit
async def test_discover_contraction_annotated(seeded_cache):
    """Contractions like 'nella' should be annotated as vocab words."""
    result = await discover(
        '<span lang="it">nella stazione</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="nella"' in result
    assert 'data-word="stazione"' in result


@pytest.mark.unit
async def test_discover_elision_essere_annotated(seeded_cache):
    """è should be annotated as essere in elided forms like dov'è."""
    result = await discover(
        '<span lang="it">Dov\'è il bagno</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="dove"' in result
    assert 'data-word="essere"' in result
    assert 'data-word="bagno"' in result


@pytest.mark.unit
async def test_discover_no_discover_skips_element(seeded_cache):
    """Elements with data-no-discover should be excluded from discovery entirely."""
    result = await discover(
        '<span lang="it" data-no-discover>gatto</span> <span lang="it">il gatto dorme</span>',
        student_id=None,
        create_cards=False,
    )
    # The no-discover span should be left untouched — plain text, no vocab-word
    assert 'data-no-discover=""' in result
    no_discover_span = result.split("data-no-discover")[1].split("</span>")[0]
    assert "vocab-word" not in no_discover_span
    # The other span should still be annotated
    assert 'data-word="gatto"' in result
    assert 'data-word="dormire"' in result


# ---------------------------------------------------------------------------
# _annotate_in_elements — phrase annotation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_annotate_phrase_surface_form():
    """Multi-word phrase surface form gets annotated."""
    soup, els = _make_soup_and_elements('<span lang="it">per favore</span>')
    word = _make_word(word="per favore", pos="loc.")
    count = _annotate_in_elements(els, word, None, surface_forms=["per favore"])
    assert count == 1
    assert 'data-word="per favore"' in str(soup)


@pytest.mark.unit
def test_annotate_phrase_inside_longer_text():
    """Phrase is annotated when it appears inside a longer element."""
    soup, els = _make_soup_and_elements(
        '<span lang="it">Sì, per favore, grazie.</span>'
    )
    word = _make_word(word="per favore", pos="loc.")
    count = _annotate_in_elements(els, word, None, surface_forms=["per favore"])
    assert count == 1
    assert 'data-word="per favore"' in str(soup)


# ---------------------------------------------------------------------------
# discover() — phrase matching
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_discover_phrase_matched(seeded_cache_with_phrases):
    """Exact phrase match on a lang element should annotate as a phrase."""
    result = await discover(
        '<span lang="it">per favore</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="per favore"' in result


@pytest.mark.unit
async def test_discover_phrase_takes_priority(seeded_cache_with_phrases):
    """Phrase match takes priority — individual tokens 'per' and 'favore' should not match separately."""
    result = await discover(
        '<span lang="it">per favore</span>',
        student_id=None,
        create_cards=False,
    )
    # "per favore" matched as phrase — element excluded from word matching,
    # so "per" and "favore" should NOT appear as individual word annotations
    assert 'data-word="per favore"' in result
    # Only one vocab-word annotation (the phrase), not two individual words
    assert result.count("vocab-word") == 1


@pytest.mark.unit
async def test_discover_phrase_and_words_coexist(seeded_cache_with_phrases):
    """Phrase and word matches work together across different elements."""
    result = await discover(
        '<span lang="it">per favore</span> <span lang="it">il gatto dorme</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="per favore"' in result
    assert 'data-word="gatto"' in result
    assert 'data-word="dormire"' in result


@pytest.mark.unit
async def test_discover_phrase_case_insensitive(seeded_cache_with_phrases):
    """Phrase matching is case-insensitive."""
    result = await discover(
        '<span lang="it">Per Favore</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="per favore"' in result


@pytest.mark.unit
async def test_discover_phrase_no_match_on_partial(seeded_cache_with_phrases):
    """Element text that doesn't exactly match a phrase is not phrase-matched."""
    result = await discover(
        '<span lang="it">per favore signora</span>',
        student_id=None,
        create_cards=False,
    )
    # "per favore signora" is not an exact phrase match — falls through to word matching
    assert 'data-word="per favore"' not in result
    # Individual words should still be matched via word matching
    assert 'data-word="per"' in result
    assert 'data-word="favore"' in result
    assert 'data-word="signore"' in result


@pytest.mark.unit
async def test_discover_phrase_data_no_save(seeded_cache_with_phrases):
    """Phrase on a data-no-save element is annotated but excluded from card creation."""
    result = await discover(
        '<span lang="it" data-no-save>mi chiamo</span> <span lang="it">il gatto</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="mi chiamo"' in result
    assert 'data-word="gatto"' in result


# ---------------------------------------------------------------------------
# Phrase annotation — punctuation endings and mixed phrase+word sentences
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "phrase",
    [
        pytest.param("un po'", id="apostrophe-ending"),
        pytest.param("come si chiama?", id="question-mark-ending"),
        pytest.param("che ore sono?", id="question-mark-ending-2"),
    ],
)
def test_annotate_phrase_with_trailing_punctuation(phrase):
    """Phrases ending in ' or ? should be annotated by the regex."""
    soup, els = _make_soup_and_elements(f'<span lang="it">{phrase}</span>')
    word = _make_word(word=phrase, pos="loc.")
    count = _annotate_in_elements(els, word, None, surface_forms=[phrase])
    assert count == 1, f"Expected 1 annotation for {phrase!r}, got {count}"
    assert f'data-word="{phrase}"' in str(soup)


@pytest.mark.unit
async def test_discover_phrase_with_punctuation(seeded_cache_with_phrases):
    """Phrases ending in punctuation are discovered and annotated."""
    result = await discover(
        '<span lang="it">un po\'</span>',
        student_id=None,
        create_cards=False,
    )
    assert 'data-word="un po\'"' in result


@pytest.mark.unit
async def test_discover_mixed_phrases_and_words(seeded_cache_with_phrases):
    """Phrases and vocab words coexist in longer multi-element sentences."""
    html = (
        '<p><span lang="it">ciao</span>, '
        '<span lang="it">mi chiamo</span> Giovanni. '
        '<span lang="it">Vorrei un caffè per favore.</span></p>'
    )
    result = await discover(html, student_id=None, create_cards=False)
    # Phrase matches (exact element text)
    assert 'data-word="mi chiamo"' in result
    assert 'data-word="ciao"' in result
    # Word match inside longer element (per-token matching)
    assert 'data-word="caffè"' in result


# ---------------------------------------------------------------------------
# Audio background task — fired in parallel with definition generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_discover_fires_audio_task_for_missing_audio(seeded_cache):
    """discover() should fire a vocab-audio background task for words missing audio."""
    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="it">il gatto dorme</span>',
            student_id=None,
            create_cards=False,
        )

    # All test words have audio_url=None, so audio task should fire
    audio_calls = [
        c
        for c in mock_bg.call_args_list
        if "vocab-audio-" in (c.kwargs.get("name") or "")
    ]
    assert len(audio_calls) == 1


@pytest.mark.unit
async def test_discover_no_audio_task_when_audio_exists():
    """discover() should NOT fire audio task when all words already have audio."""
    gatto_with_audio = SimpleNamespace(
        word="gatto",
        part_of_speech="s.m.",
        syllabization="",
        entry_id="LM-GATTO",
        senses=[],
        id="fake-gatto-sm",
        audio_url="/static/audio/word_gatto.wav",
    )
    _vocab_cache.seed(words={"gatto": [gatto_with_audio]}, defs={})
    try:
        with patch("maestro.vocab.discover.create_background_task") as mock_bg:
            await discover(
                '<span lang="it">il gatto</span>',
                student_id=None,
                create_cards=False,
            )

        audio_calls = [
            c
            for c in mock_bg.call_args_list
            if "vocab-audio-" in (c.kwargs.get("name") or "")
        ]
        assert len(audio_calls) == 0
    finally:
        _vocab_cache.invalidate()


@pytest.mark.unit
async def test_discover_audio_and_def_tasks_fire_independently(seeded_cache):
    """Audio and definition tasks should fire independently based on what's missing."""
    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="it">il gatto dorme</span>',
            student_id=None,
            create_cards=False,
        )

    names = [c.kwargs.get("name", "") for c in mock_bg.call_args_list]
    audio_tasks = [n for n in names if "vocab-audio-" in n]
    # Audio task should fire (words have audio_url=None)
    assert len(audio_tasks) == 1
    # Def task should NOT fire (test words have senses=[], so they're skipped)
    def_tasks = [n for n in names if "vocab-defs-" in n]
    assert len(def_tasks) == 0
