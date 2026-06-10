"""Unit tests for vocab/discover.py — annotation resolution and HTML annotation.

Test layers:
- matches_from_annotations: verified annotations → dictionary entries
- get_target_text: HTML → plain text extraction
- _annotate_in_elements: plain text → annotated HTML
- discover(): integration (HTML scoping, data-no-discover, multi-POS,
  background definition/audio tasks)
- cache.get_definition: A0 fallback behaviour
"""

from unittest.mock import patch

import pytest
from types import SimpleNamespace

from maestro.models import VocabAnnotation
from maestro.vocab.discover import (
    _annotate_in_elements,
    discover,
    get_target_text,
    matches_from_annotations,
)
from maestro.vocab import cache as _vocab_cache
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vocab_word(word, pos="s.f.", entry_id=None, language="it"):
    """Create a mock VocabularyWord for word_index / cache seeding."""
    pos_slug = pos.replace(".", "").replace("/", "")
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization="",
        ipa=None,
        entry_id=entry_id or f"LM-{word.upper()}",
        senses=[],
        id=f"fake-{word}-{pos_slug}",
        audio_url=None,
        language=language,
    )


def _make_word(
    word="casa",
    pos="s.f.",
    syllabization="cà-sa",
    entry_id="LM-001",
    senses=None,
    ipa=None,
):
    """Create a mock VocabularyWord for _annotate_in_elements tests."""
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization=syllabization,
        ipa=ipa,
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


def _ann(lemma, surfaces, upos=""):
    return VocabAnnotation(surface_forms=list(surfaces), lemma=lemma, upos=upos)


# Word index for annotation-resolution and discover() tests.
_TEST_WORD_INDEX = {
    "gatto": [_make_vocab_word("gatto", pos="s.m.")],
    "dormire": [_make_vocab_word("dormire", pos="v.intr.")],
    "ciao": [_make_vocab_word("ciao", pos="inter.")],
    "stazione": [_make_vocab_word("stazione", pos="s.f.")],
    # Multi-POS: "piano" as noun (piano/floor) and adjective (quiet/slow)
    "piano": [
        _make_vocab_word("piano", pos="s.m."),
        _make_vocab_word("piano", pos="agg."),
    ],
}

_TEST_PHRASE_INDEX = {
    "per favore": [_make_vocab_word("per favore", pos="loc.")],
}


@pytest.fixture()
def seeded_cache():
    """Seed global vocab cache for discover() tests."""
    _vocab_cache.seed(words=_TEST_WORD_INDEX, defs={}, phrases=_TEST_PHRASE_INDEX)
    yield
    _vocab_cache.invalidate()


# ---------------------------------------------------------------------------
# matches_from_annotations — verified annotations → dictionary entries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_matches_resolves_word_index_lemma(seeded_cache):
    matches = matches_from_annotations(
        [_ann("gatto", ["gatti"], "NOUN")], language="it"
    )
    assert len(matches) == 1
    assert matches[0].word.word == "gatto"
    assert matches[0].surface_forms == ["gatti"]


@pytest.mark.unit
def test_matches_resolves_phrase_index_lemma(seeded_cache):
    matches = matches_from_annotations(
        [_ann("per favore", ["per favore"])], language="it"
    )
    assert len(matches) == 1
    assert matches[0].word.word == "per favore"


@pytest.mark.unit
def test_matches_skips_unresolvable_lemma(seeded_cache):
    matches = matches_from_annotations(
        [_ann("capiscare", ["capisco"], "VERB"), _ann("gatto", ["gatto"], "NOUN")],
        language="it",
    )
    assert [m.word.word for m in matches] == ["gatto"]


@pytest.mark.unit
def test_matches_pos_disambiguation(seeded_cache):
    noun = matches_from_annotations([_ann("piano", ["piano"], "NOUN")], language="it")
    adj = matches_from_annotations([_ann("piano", ["piano"], "ADJ")], language="it")
    assert noun[0].word.part_of_speech == "s.m."
    assert adj[0].word.part_of_speech == "agg."


@pytest.mark.unit
def test_matches_dedup_same_entry(seeded_cache):
    matches = matches_from_annotations(
        [_ann("gatto", ["gatto"], "NOUN"), _ann("gatto", ["gatti"], "NOUN")],
        language="it",
    )
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# cache.get_definition — A0 fallback behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cache_get_definition_a0_fallback_to_a1():
    """A0 lookup with no A0 def should return A1 def with translation only."""
    a1_def = _make_wdef(translation="cat")
    _vocab_cache.seed(defs={("word-1", "A1"): a1_def})
    result = _vocab_cache.get_definition("word-1", "A0", language="it")
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
    result = _vocab_cache.get_definition("word-1", "A0", language="it")
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
    result = _vocab_cache.get_definition("word-1", "A0", language="it")
    assert result is a0_def  # exact same object, not a copy
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a0_no_a1_returns_none():
    """A0 lookup with no A0 or A1 def should return None."""
    _vocab_cache.seed(defs={})
    result = _vocab_cache.get_definition("word-1", "A0", language="it")
    assert result is None
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_get_definition_a1_no_fallback():
    """A1 lookup with no A1 def should return None (no fallback for non-A0)."""
    a2_def = _make_wdef(translation="cat")
    _vocab_cache.seed(defs={("word-1", "A2"): a2_def})
    result = _vocab_cache.get_definition("word-1", "A1", language="it")
    assert result is None
    _vocab_cache.invalidate()


@pytest.mark.unit
def test_cache_phrase_index_seeded():
    """seed() with phrases param populates phrase_index()."""
    phrases = {"per favore": [_make_vocab_word("per favore", pos="loc.")]}
    _vocab_cache.seed(phrases=phrases)
    assert _vocab_cache.phrase_index("it") == phrases
    _vocab_cache.invalidate()


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


# ---------------------------------------------------------------------------
# discover() — annotations-driven HTML behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_discover_without_annotations_returns_unchanged(seeded_cache):
    """No annotations (None or empty) → content passes through untouched."""
    html = '<span lang="it">il gatto dorme</span>'
    assert await discover(html, student_id=None, language="it") == html
    assert await discover(html, student_id=None, language="it", annotations=[]) == html


@pytest.mark.unit
async def test_discover_no_lang_returns_unchanged(seeded_cache):
    """Content without lang attributes should pass through unchanged."""
    html = '<div class="scoring">Good job!</div>'
    result = await discover(
        html,
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[_ann("gatto", ["gatto"], "NOUN")],
    )
    assert result == html


@pytest.mark.unit
async def test_discover_main_scoping(seeded_cache):
    """When <main> is present, only lang elements inside it are annotated."""
    html = (
        '<nav><span lang="it">ciao</span></nav>'
        '<main><span lang="it">il gatto dorme</span></main>'
    )
    result = await discover(
        html,
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[
            _ann("gatto", ["gatto"], "NOUN"),
            _ann("ciao", ["ciao"], "INTJ"),
        ],
    )
    assert 'data-word="gatto"' in result
    assert 'data-word="ciao"' not in result


@pytest.mark.unit
async def test_discover_fragment_mode(seeded_cache):
    """Without <main>, all lang elements are annotated (HTMX fragment mode)."""
    html = '<span lang="it">il gatto dorme</span>'
    result = await discover(
        html,
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[
            _ann("gatto", ["gatto"], "NOUN"),
            _ann("dormire", ["dorme"], "VERB"),
        ],
    )
    assert 'data-word="gatto"' in result
    assert 'data-word="dormire"' in result


@pytest.mark.unit
async def test_discover_no_discover_skips_element(seeded_cache):
    """Elements with data-no-discover should be excluded entirely."""
    result = await discover(
        '<span lang="it" data-no-discover>gatto</span> <span lang="it">il gatto dorme</span>',
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[_ann("gatto", ["gatto"], "NOUN")],
    )
    assert 'data-no-discover=""' in result
    no_discover_span = result.split("data-no-discover")[1].split("</span>")[0]
    assert "vocab-word" not in no_discover_span
    assert 'data-word="gatto"' in result


@pytest.mark.unit
async def test_discover_multi_pos_annotation(seeded_cache):
    """Same lemma with different UPOS resolves to distinct dictionary entries."""
    result = await discover(
        '<span lang="it">suono il piano piano</span>',
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[
            _ann("piano", ["piano"], "NOUN"),
            _ann("piano", ["piano"], "ADJ"),
        ],
    )
    assert result.count('data-word="piano"') == 2
    assert 'data-pos="s.m."' in result
    assert 'data-pos="agg."' in result


@pytest.mark.unit
async def test_discover_phrase_annotation(seeded_cache):
    """Multi-word lemmas annotate the whole phrase; inner words stay plain."""
    result = await discover(
        '<span lang="it">Sì, per favore, grazie.</span>',
        student_id=None,
        create_cards=False,
        language="it",
        annotations=[_ann("per favore", ["per favore"])],
    )
    assert 'data-word="per favore"' in result
    assert result.count("vocab-word") == 1


# ---------------------------------------------------------------------------
# Background definition/audio tasks
# ---------------------------------------------------------------------------

_GATTO_ANNS = [
    _ann("gatto", ["gatto"], "NOUN"),
    _ann("dormire", ["dorme"], "VERB"),
]


@pytest.mark.unit
async def test_discover_fires_audio_task_for_missing_audio(seeded_cache):
    """discover() should fire a vocab-audio background task for words missing audio."""
    with patch("maestro.vocab.discover.create_background_task") as mock_bg:
        await discover(
            '<span lang="it">il gatto dorme</span>',
            student_id=None,
            create_cards=False,
            language="it",
            annotations=_GATTO_ANNS,
        )

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
        ipa=None,
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
                language="it",
                annotations=[_ann("gatto", ["gatto"], "NOUN")],
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
            language="it",
            annotations=_GATTO_ANNS,
        )

    names = [c.kwargs.get("name", "") for c in mock_bg.call_args_list]
    audio_tasks = [n for n in names if "vocab-audio-" in n]
    # Audio task should fire (words have audio_url=None)
    assert len(audio_tasks) == 1
    # Def task should NOT fire (test words have senses=[], so they're skipped)
    def_tasks = [n for n in names if "vocab-defs-" in n]
    assert len(def_tasks) == 0
