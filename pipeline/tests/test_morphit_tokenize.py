"""M1.5: Morph-it! loader, category matching, elision table and the tokeniser."""

from __future__ import annotations

import pytest

from conftest import needs_data
from itcontent import morphit
from itcontent.morphit import Analysis, parse_lines, pos_matches
from itcontent.tokenize import FOREIGN, NAME, NUMBER, PUNCT, SLOT, WORD, render, sentence_initial, tokenize

NAMES = ["Marco", "Sara", "Rosa", "Bologna"]


# ---------------------------------------------------------------- Morph-it!


@needs_data
def test_loads_real_file_as_nfc_utf8():
    m = morphit.load()
    assert len(m) > 400_000
    assert m.malformed == 2  # the two `seppur` lines with spaces instead of tabs
    assert {str(a) for a in m.get("caffè")} == {"caffè NOUN-M:p", "caffè NOUN-M:s"}
    assert any(a.category == "WH" for a in m.get("perché"))
    assert m.get("seppur")
    assert morphit.load() is m  # cached


@needs_data
def test_lookup_order_and_elisions():
    m = morphit.load()
    assert m.lookup("Lei") == m.get("lei")  # absent capitalised: lowercased lookup
    assert {a.lemma for a in m.lookup("c'")} == {"ci"}  # Morph-it! says ADV with lemma c'
    assert {a.lemma for a in m.lookup("quant’")} == {"quanto"}  # missing in Morph-it!
    assert [str(a) for a in m.lookup("un'")] == ["una ART-F:s"]  # never the pronoun una
    assert {a.lemma for a in m.lookup("d'")} == {"di"}
    assert {a.lemma for a in m.lookup("anch'")} == {"anche"}
    assert {a.category for a in m.lookup("l'")} == {"ART-F", "ART-M", "PRO-PERS-CLI-3-F-S", "PRO-PERS-CLI-3-M-S"}
    assert m.lookup("po'")  # not in the table: Morph-it!'s own entry
    # a capitalised word also takes the lowercase analyses and loses Morph-it!'s proper-noun readings
    assert {str(a) for a in m.get("Al")} == {"Al NPR"}
    assert {str(a) for a in m.lookup("Al")} == {"al ARTPRE-M:s"}
    assert m.lookup("Bologna") == m.get("Bologna")  # no lowercase form: the NPR reading stays


def test_parse_lines_handles_malformed_lines_and_latin1_nfd():
    m = parse_lines(["caffè\tcaffè\tNOUN-M:s\n", "seppur  seppure  CON\n", "\n", "bad line\n"])
    assert m.get("caffè") == (Analysis("caffè", "NOUN-M", "s"),)
    assert m.get("seppur") == (Analysis("seppure", "CON", ""),)
    assert m.malformed == 2


def test_category_prefixes_on_dash_boundaries():
    assert pos_matches("ART-M", "ART")
    assert pos_matches("ART", "ART")
    assert not pos_matches("ARTPRE-M", "ART")
    assert pos_matches("NOUN-M", "NOUN")
    assert pos_matches("PRO-PERS-CLI-3-F-S", "PRO-PERS")
    assert pos_matches("PRO-PERS-CLI-3-F-S", "PRO")
    assert not pos_matches("PRON", "PRO")
    a = Analysis("essere", "VER", "ind+pres+3+s")
    assert a.matches(pos=["VER"], morph=r"ind\+pres\+3") and a.is_verb()
    assert not a.matches(morph=r"^cond")
    assert Analysis("lei", "PRO-PERS-3-F-S").matches(morph="^$")  # no features: the empty string


# ---------------------------------------------------------------- tokeniser


def kinds(text: str, **kw) -> list[tuple[str, str]]:
    _, toks = tokenize(text, **kw)
    return [(t.surface, t.kind) for t in toks]


@pytest.mark.parametrize(
    ("text", "surfaces"),
    [
        ("l'amica", ["l'", "amica"]),
        ("C'è un bar.", ["C'", "è", "un", "bar", "."]),
        ("Scusi, quant'è?", ["Scusi", ",", "quant'", "è", "?"]),
        ("un'amica", ["un'", "amica"]),
        ("Dov’è Sara?", ["Dov’", "è", "Sara", "?"]),
        ("una spremuta d'arancia", ["una", "spremuta", "d'", "arancia"]),
        ("un po' di pane", ["un", "po'", "di", "pane"]),
        ("la mia e-mail", ["la", "mia", "e-mail"]),
        ("'Ciao' dice Marco", ["'", "Ciao", "'", "dice", "Marco"]),
    ],
)
def test_elided_forms_attach_to_the_left_token(text, surfaces):
    lead, toks = tokenize(text)
    assert [t.surface for t in toks] == surfaces
    assert render(lead, toks) == text


def test_names_are_case_sensitive():
    assert kinds("Rosa è rosa.", names=NAMES) == [("Rosa", NAME), ("è", WORD), ("rosa", WORD), (".", PUNCT)]
    assert kinds("Zia Rosa", names=NAMES, not_names=["rosa"]) == [("Zia", WORD), ("Rosa", WORD)]


def test_foreign_words_and_digits():
    assert kinds('Come si dice "croissant"?', foreign=["croissant"])[3:6] == [
        ('"', PUNCT),
        ("croissant", FOREIGN),
        ('"', PUNCT),
    ]
    assert kinds("lo smart working", foreign=["Smart Working"]) == [
        ("lo", WORD),
        ("smart", FOREIGN),
        ("working", FOREIGN),
    ]
    assert kinds("Costa 6,20 €, dalle 9:00–13:00") == [
        ("Costa", WORD),
        ("6,20", NUMBER),
        ("€", PUNCT),
        (",", PUNCT),
        ("dalle", WORD),
        ("9:00", NUMBER),
        ("–", PUNCT),
        ("13:00", NUMBER),
    ]
    assert kinds("1, 2, 3")[0] == ("1", NUMBER)


def test_trailing_text_re_renders_lines_exactly():
    for text in ["  Ciao,  Marco!  ", "**un'**amica", "Ecco: un cappuccino, un cornetto e una spremuta."]:
        lead, toks = tokenize(text, markup="*")
        assert render(lead, toks) == text
    lead, toks = tokenize("**un'**amica", markup="*")
    assert lead == "**" and [(t.surface, t.trailing) for t in toks] == [("un'", "**"), ("amica", "")]
    assert (toks[0].start, toks[0].end) == (2, 5)


def test_protected_spans_are_slot_tokens():
    _, toks = tokenize("mi chiamo {NAME}.", protected=[(10, 16, "NAME")])
    assert [(t.surface, t.kind, t.slot) for t in toks][2:] == [("{NAME}", SLOT, "NAME"), (".", PUNCT, None)]


def test_sentence_initial():
    _, toks = tokenize('No, sono canadese. E Lei? "Bene."')
    initial = [t.surface for k, t in enumerate(toks) if t.kind == WORD and sentence_initial(toks, k)]
    assert initial == ["No", "E", "Bene"]
