"""M1.7: grammar detection and morphology unlocks from content/grammar/detection.yaml.

Every point of Units 1–3 has a passing and a failing case (points with `detect: none` are checked to stay silent);
every rule refined in M1.7 for the real Morph-it! tags has its own pair.
"""

from __future__ import annotations

import pytest

from conftest import needs_data
from itcontent import morphit
from itcontent.course import load_course
from itcontent.detection import DetectionRuleError, Detector
from itcontent.morphit import Analysis
from itcontent.resolve import Ctx, Lexicon

pytestmark = needs_data


@pytest.fixture(scope="session")
def course(root):
    return load_course(root)


@pytest.fixture(scope="session")
def lex(course):
    return Lexicon.from_course(course, morphit.load())


def found(lex: Lexicon, text: str, unit: str = "u03") -> set[tuple[str, str]]:
    """(point, covered surfaces) for every detection; unknown tokens are allowed (lenient)."""
    u = lex.unit_index[unit]
    a = lex.annotate(text, Ctx(unit=u, pos=(u, 1, 1), strict=False))
    return {(d.point, " ".join(t.surface for t in a.tokens[d.start : d.end + 1])) for d in a.detections}


def points(lex: Lexicon, text: str, unit: str = "u03") -> set[str]:
    return {p for p, _ in found(lex, text, unit)}


# (point, unit, text that detects it, the expected span, text that must not)
DETECT_CASES = [
    ("g:subject-pronouns", "u01", "Io sono di Bologna.", "Io", "Noi siamo di Bologna. E tu?"),
    ("g:subject-pronouns", "u02", "Lei è americano?", "Lei", "No, sono canadese. E Lei?"),
    ("g:negation-non", "u01", "Non sono americano.", "Non sono", "Non capisco. Non bene."),
    ("g:negation-non", "u07", "Non lo so.", "Non lo so", "Non molto."),
    ("g:conjunctions", "u01", "Sara e Marco.", "e", "E tu? Sara è di Bologna."),
    ("g:conjunctions", "u01", "Sono canadese ma abito a Bologna.", "ma", "Ecco Sara."),
    ("g:simple-prepositions", "u01", "Io sono di Bologna.", "di", "Per favore. Al mercato."),
    ("g:simple-prepositions", "u02", "Una spremuta d'arancia.", "d'", "Un bar."),
    ("g:indefinite-article", "u02", "Ecco un'amica.", "un'", "Uno, due, tre."),
    ("g:indefinite-article", "u02", "Vorrei un cornetto.", "un", "Vorrei il cornetto."),
    ("g:noun-plural", "u02", "Due cornetti.", "cornetti", "Due caffè, sei euro, due bar."),
    ("g:noun-plural", "u02", "Due spremute.", "spremute", "Una spremuta."),
    ("g:numbers-to-100", "u02", "Un euro e sessanta.", "sessanta", "Sei euro e venti. 30 euro."),
    ("g:conditional-courtesy", "u02", "Potrei avere un caffè?", "Potrei", "Vorrei un caffè."),
    ("g:definite-article", "u03", "Il cornetto e la spremuta.", "Il", "La vedo."),
    ("g:definite-article", "u03", "Gli amici di Marco.", "Gli", "Gli piace."),
    ("g:possessives", "u03", "La mia famiglia.", "mia", "Loro sono di Bologna."),
    ("g:possessives", "u03", "È Suo?", "Suo", "Sono io."),
    ("g:molto", "u03", "Molti amici.", "Molti", "Tanti amici."),
    ("g:molto", "u03", "Molto buono!", "Molto", "Buono!"),
    # rules refined in M1.7 for the real Morph-it! tags (later units)
    ("g:present-noi", "u04", "Parliamo italiano.", "Parliamo", "Parlo italiano."),
    ("g:present-voi", "u06", "Parlate italiano?", "Parlate", "Parla italiano?"),
    ("g:present-isc", "u04", "Capisci?", "Capisci", "Capire è difficile."),
    ("g:fare-present", "u04", "Che lavoro fai?", "fai", "Fare."),
    ("g:irregular-movement", "u05", "Vieni?", "Vieni", "Venire."),
    ("g:reflexive-sg", "u05", "Ti alzi presto?", "Ti alzi", "Mi piace."),
    ("g:c-e-ci-sono", "u06", "Ci sono due bar.", "Ci sono", "Ci siamo."),
    ("g:passato-prossimo-avere", "u09", "Ho finito.", "Ho finito", "Ho fame."),
    ("g:passato-prossimo-avere", "u09", "Hai mangiato?", "Hai mangiato", "Hai fame?"),
    ("g:passato-prossimo-essere", "u11", "Sono venuto ieri.", "Sono venuto", "Sono stanco."),
    ("g:questo-quello", "u07", "Quella spremuta.", "Quella", "Quasi."),
    ("g:questo-quello", "u07", "Questi cornetti.", "Questi", "Questura."),
    ("g:tutto-tanto", "u07", "Tutti gli amici.", "Tutti", "Tuttavia."),
    ("g:tutto-tanto", "u07", "Pochi amici.", "Pochi", "Poi."),
    ("g:stressed-pronouns", "u08", "Per Lei.", "Per Lei", "Lei è americano."),
]


@pytest.mark.parametrize(("point", "unit", "yes", "span", "no"), DETECT_CASES, ids=lambda x: str(x)[:30])
def test_detection_pass_and_fail(lex, point, unit, yes, span, no):
    assert (point, span) in found(lex, yes, unit)
    assert point not in points(lex, no, unit)


NONE_POINTS = {
    "g:tu-lei": "Lei è americano? Tu sei di Bologna?",
    "g:adjectives-o-a-e": "Sara è italiana. Marco è canadese.",
    "g:noun-gender": "Un cornetto e una spremuta.",
    "g:lei-questions": "Cosa prende? Desidera?",
    "g:piacere-chunk": "Mi piace il caffè. Le piace?",
    "g:irregular-nouns": "Il caffè, la città, il bar.",
    "g:np-agreement": "Una casa piccola, due amici simpatici.",
    "g:predicative-agreement": "Sara è simpatica.",
    "g:quando": "Quando arrivi? Ti chiamo quando arrivo.",
}


@pytest.mark.parametrize(("point", "text"), sorted(NONE_POINTS.items()))
def test_points_traced_by_targets_never_detect(lex, point, text):
    assert not lex.detector.by_id[point].detects
    assert point not in points(lex, text)


# (point, a form whose analyses it unlocks, a form it doesn't)
UNLOCK_CASES = [
    ("g:essere-present-sg", "è", "siamo"),
    ("g:essere-present-sg", "sei", "sono-3p"),
    ("g:avere-present-sg", "hai", "hanno"),
    ("g:essere-avere-3pl", "hanno", "ho"),
    ("g:essere-avere-3pl", "sono", "è"),
    ("g:present-regular-sg", "parla", "parlano"),
    ("g:infinitive", "mangiare", "mangio"),
    ("g:passato-prossimo-avere", "mangiato", "mangiare"),
]


@pytest.mark.parametrize(("point", "yes", "no"), UNLOCK_CASES)
def test_unlocks(lex, point, yes, no):
    m = lex.morph
    assert point in lex.detector.unlocking_points(m.lookup(yes))
    if no == "sono-3p":  # sono: 1s is unlocked by essere-present-sg, 3p is not
        sono = [(a, pts) for a, pts in lex.detector.unlocks(m.lookup("sono"))]
        assert {a.features for a, pts in sono if point in pts} == {"ind+pres+1+s"}
        return
    assert point not in lex.detector.unlocking_points(m.lookup(no))


def test_unlocks_per_analysis_and_legality(lex):
    vorrei = lex.morph.lookup("vorrei")
    assert all(not pts for _, pts in lex.detector.unlocks(vorrei))  # conditional: only inside chunks
    assert not lex.detector.is_legal(vorrei, {"g:essere-present-sg", "g:present-regular-sg"})
    hai = lex.morph.lookup("hai")  # ind+pres+2+s and impr+pres+2+s: legal once any analysis is unlocked
    assert lex.detector.is_legal(hai, {"g:avere-present-sg"})
    assert not lex.detector.is_legal(hai, {"g:essere-present-sg"})
    assert lex.detector.is_legal(lex.morph.lookup("cornetto"), set())  # not a verb
    assert lex.detector.unlocks([Analysis("spremuta", "NOUN-F", "s", synthetic=True)]) == []


def test_every_analysis_must_match_so_invariable_nouns_are_never_plural(lex):
    for text in ["Due caffè.", "Sei euro.", "Tre bar.", "Due città."]:
        assert "g:noun-plural" not in points(lex, text, "u02"), text
    det = Detector([{"id": "g:x", "detect": [{"seq": [{"pos": ["NOUN"], "morph": "p$"}]}]}])
    toks = lex.annotate("caffè", Ctx(unit=2, strict=False)).tokens
    assert det.detect(toks) == []
    det_any = Detector([{"id": "g:x", "detect": [{"seq": [{"pos": ["NOUN"], "morph": "p$", "any": True}]}]}])
    assert [d.point for d in det_any.detect(toks)] == ["g:x"]


def test_excluded_tokens_get_no_detections(lex):
    # chunk tokens (per favore: PRE), a lexical article (u01), names, numbers, foreign words
    assert points(lex, "Per favore.", "u02") == set()
    assert points(lex, "Un cappuccino.", "u01") == set()
    det = Detector([{"id": "g:any", "detect": [{"seq": [{"form": "."}]}]}])
    a = lex.annotate(
        "Marco: 30 croissant, per favore, un cornetto.",
        Ctx(unit=lex.unit_index["u01"], foreign=["croissant"], strict=False),
    )
    hit = {a.tokens[d.start].surface for d in det.detect(a.tokens)}
    assert hit == {"cornetto"}


def test_optional_matchers_present_before_absent(lex):
    det = Detector(
        [
            {
                "id": "g:x",
                "detect": [{"seq": [{"form": "^non$"}, {"pos": ["PRO-PERS"], "optional": True}, {"pos": ["VER"]}]}],
            }
        ]
    )
    a = lex.annotate("Non lo so.", Ctx(unit=7, strict=False))
    assert [(d.start, d.end) for d in det.detect(a.tokens)] == [(0, 2)]
    b = lex.annotate("Non so.", Ctx(unit=7, strict=False))
    assert [(d.start, d.end) for d in det.detect(b.tokens)] == [(0, 1)]


def test_rules_file_parses_and_covers_every_point(course):
    det = Detector(course.detection_rules())
    ids = [str(p["id"]) for p in course.grammar_points()]
    assert sorted(det.by_id) == sorted(ids)
    unit_1_to_3 = {str(p["id"]) for p in course.grammar_points() if p["unit"] in ("u01", "u02", "u03")}
    covered = {c[0] for c in DETECT_CASES} | set(NONE_POINTS) | {c[0] for c in UNLOCK_CASES}
    assert unit_1_to_3 <= covered, unit_1_to_3 - covered


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "g:x", "detect": [{"seq": [{"shape": "x"}]}]},
        {"id": "g:x", "detect": [{"seq": [{"form": "("}]}]},
        {"id": "g:x", "detect": [{"seq": [{"form": "a", "optional": True}]}]},
        {"id": "g:x", "detect": [{"nope": []}]},
        {"id": "g:x", "unlock": [{"lemmas": "*"}]},
    ],
)
def test_bad_rules_are_rejected(bad):
    with pytest.raises(DetectionRuleError):
        Detector([bad])
