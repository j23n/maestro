"""M1.4: the normaliser and the answer-pattern expander pass the shared grading fixtures (parity with LearningCore)."""

from __future__ import annotations

import json
import unicodedata

import pytest

from itcontent import paths
from itcontent.normalize import ACCENT_SENSITIVE, normalize, strip_accents, tokens
from itcontent.patterns import PatternError, count, expand, model_answer, parse

NORMALIZER = json.loads((paths.FIXTURES / "grading" / "normalizer.json").read_text(encoding="utf-8"))
PATTERNS = json.loads((paths.FIXTURES / "grading" / "patterns.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", NORMALIZER["cases"], ids=lambda c: c["in"])
def test_normalizer_fixture(case):
    assert normalize(case["in"]) == case["out"]


def test_normalizer_fixture_has_an_nfd_input():
    nfd = [c["in"] for c in NORMALIZER["cases"] if unicodedata.normalize("NFC", c["in"]) != c["in"]]
    assert nfd, "the fixture's NFD case must reach the normaliser as NFD"
    assert normalize(nfd[0]) == unicodedata.normalize("NFC", nfd[0])


@pytest.mark.parametrize("case", NORMALIZER["stripAccents"], ids=lambda c: c["in"])
def test_strip_accents_fixture(case):
    assert strip_accents(case["in"]) == case["out"]


def test_accent_sensitive_list_matches_fixture():
    assert set(NORMALIZER["accentSensitive"]) == ACCENT_SENSITIVE


def test_normalizer_edge_cases():
    assert normalize("10:15, alle 9.30") == "10:15 alle 9.30"
    assert normalize("C’è") == "c'è"
    assert normalize("— Ciao —") == "ciao"
    assert normalize("rosso-verde e -o") == "rosso-verde e o"
    assert tokens("Un' amica, per favore!") == ["un'amica", "per", "favore"]
    assert tokens("") == []


@pytest.mark.parametrize("case", PATTERNS["cases"], ids=lambda c: c["pattern"])
def test_patterns_fixture(case):
    if "error" in case:
        with pytest.raises(PatternError) as exc:
            expand(case["pattern"])
        assert str(exc.value) == case["error"]
        return
    exps = expand(case["pattern"])
    if "expansions" in case:
        assert [e.text for e in exps] == case["expansions"]
    if "count" in case:
        assert len(exps) == case["count"] == count(case["pattern"])
    if "first" in case:
        assert exps[0].text == case["first"]
    if "focus" in case:
        assert [list(e.focus) for e in exps] == case["focus"]
    if "gender" in case:
        assert [e.gender for e in exps] == case["gender"]
    if "slots" in case:
        assert [name for _, name in exps[0].slots] == case["slots"]


def test_expansion_order_and_tokens():
    exps = expand("( {per favore|grazie})")
    assert [e.text for e in exps] == ["per favore", "grazie", ""]
    assert exps[2].tokens == ()
    e = model_answer("Vorrei [un'] amica, per favore.")
    assert e.text == "vorrei un'amica per favore"
    assert e.tokens == ("vorrei", "un'amica", "per", "favore")
    assert e.focus == (1,)
    assert e.raw == "Vorrei un' amica, per favore."
    assert e.raw_focus == ((7, 10),)


def test_gendered_groups_are_linked():
    exps = expand("sono {m:nato|f:nata} e {m:americano|f:americana}")
    assert [(e.text, e.gender) for e in exps] == [
        ("sono nato e americano", "m"),
        ("sono nata e americana", "f"),
    ]
    assert count("sono {m:nato|f:nata} e {m:americano|f:americana}") == 2
    several = expand("{m:americano|m:statunitense|f:americana}")
    assert [(e.text, e.gender) for e in several] == [("americano", "m"), ("statunitense", "m"), ("americana", "f")]
    nested = expand("{io|tu} sono {m:nato|f:nata}( a {m:Roma|f:Roma})")
    assert len(nested) == count("{io|tu} sono {m:nato|f:nata}( a {m:Roma|f:Roma})") == 8


def test_slots_keep_their_case_and_position():
    e = model_answer("Abito {ME.home}, sono {ME.nationality}.")
    assert e.text == "abito {ME.home} sono {ME.nationality}"
    assert e.slots == ((1, "ME.home"), (3, "ME.nationality"))
    assert e.raw == "Abito {ME.home}, sono {ME.nationality}."
    assert e.raw_slots == ((6, 15, "ME.home"), (22, 38, "ME.nationality"))
    assert model_answer("ho {NUMBER} anni").slots == ((1, "NUMBER"),)


def test_escapes():
    assert model_answer(r"a \| b \( c \) \[d\]").text == "a | b c d"
    assert model_answer(r"\{NAME\}").slots == ()


@pytest.mark.parametrize(
    "bad",
    ["{a|b", "(a", "[a", "a)", "a|b", "{FOO}", "{NOME}", "{ME.city}", "{m:a|b}", "x\\", "a}"],
)
def test_malformed_patterns_fail_with_a_position(bad):
    with pytest.raises(PatternError, match=r"character|slot|gendered"):
        parse(bad)


def test_limit_counts_without_expanding():
    with pytest.raises(PatternError, match=r"expansion limit 512 exceeded \(4096\)"):
        expand("{a|b|c|d}{a|b|c|d}{a|b|c|d}{a|b|c|d}{a|b|c|d}{a|b|c|d}")
    assert len(expand("{a|b}{a|b}{a|b}{a|b}{a|b}{a|b}{a|b}{a|b}{a|b}")) == 512
