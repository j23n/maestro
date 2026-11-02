"""German practice drills: recipes for Perfekt, verb forms, cases, contractions and separable verbs."""

import json
import os

import pytest

from maestro_content import build_db, drills, drills_de, grammar, kaikki, packs, packs_de
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample-de.jsonl")
TOPICS = grammar.load_all(os.path.join(ROOT, "content", "de", "grammar"), "de")
TOPIC_INFO = {t.id: drills.TopicInfo(t.id, t.title, t.level, t.order, t.summary) for t in TOPICS}

TEXT = """# Ein Tag
level: A1
collection: alltag
order: 1
introduces: perfekt

Ich habe gestern mit dem Lehrer gegessen. || Yesterday I ate with the teacher.
Die Frau ist zum Bahnhof gegangen. || The woman went to the station.
Er hat das Haus gekauft. || He bought the house.
Wir sind in die Stadt gefahren. || We drove into town.
Das Kind isst im neuen Haus. || The child eats in the new house.
Ich rufe dich morgen an. || I'll call you tomorrow.
Du kaufst ein Brot, weil du Hunger hast. || You buy bread because you're hungry.
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("de")
    conn = build_db.create(str(tmp / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE), "de")
    build_db.build(conn, entries, form_of, Registry(language="de"))
    folder = tmp / "texts" / "alltag"
    folder.mkdir(parents=True)
    (folder / "alltag-01.md").write_text(TEXT, encoding="utf-8")
    warnings, errors = packs.build_all(conn, str(tmp / "texts"), str(tmp / "packs"), "1", topics=TOPICS,
                                       language="de")
    assert errors == []
    text = json.loads((tmp / "packs" / "alltag" / "texts" / "alltag-01.json").read_text(encoding="utf-8"))
    return conn, text


def sentence(text, n):
    return next(s for b in text["blocks"] for s in b["sentences"] if s["id"] == f"s{n}")


def test_a_perfekt_text_gets_a_perfekt_set(built):
    _, text = built
    set_ = text["drills"]
    assert 3 <= len(set_) <= drills.MAX_DRILLS
    main = [d for d in set_ if not d.get("recycled")]
    assert {d["topic"] for d in main} == {"de:perfekt"}
    assert {"aux", "participle", "participles", "order"} <= {d["recipe"] for d in main}
    assert drills.validate(text, set_) == []


def test_aux_offers_haben_first(built):
    _, text = built
    aux = next(c for c in drills_de.compound_candidates(sentence(text, 2), TOPIC_INFO) if c.recipe == "aux")
    assert aux.drill["options"] == ["hat", "ist"] and aux.drill["answers"] == ["ist"]
    assert aux.drill["near"] == {"hat": "gehen takes sein. Verbs of movement and change usually do."}


def test_no_aux_drill_for_a_verb_that_takes_both(built):
    _, text = built
    assert not [c for c in drills_de.compound_candidates(sentence(text, 4), TOPIC_INFO) if c.recipe == "aux"]


def test_participle_names_the_regular_guess(built):
    _, text = built
    part = next(c for c in drills_de.compound_candidates(sentence(text, 2), TOPIC_INFO) if c.recipe == "participle")
    assert part.drill["answers"] == ["gegangen"] and "gegeht" in part.drill["near"]
    regular = next(c for c in drills_de.compound_candidates(sentence(text, 3), TOPIC_INFO) if c.recipe == "participle")
    assert regular.drill["near"] == {} and regular.drill["hint"] is None


@pytest.mark.parametrize("infinitive, participle", [
    ("machen", "gemacht"), ("kaufen", "gekauft"), ("arbeiten", "gearbeitet"), ("besuchen", "besucht"),
    ("studieren", "studiert"), ("aufmachen", "aufgemacht"), ("gehen", "gegeht"), ("verkaufen", "verkauft"),
])
def test_weak_participle(infinitive, participle):
    assert drills_de.weak_participle(infinitive) == participle


def test_case_drill_after_a_preposition(built):
    _, text = built
    case = next(c for c in drills_de.case_candidates(sentence(text, 1)))
    assert case.topic == "de:dativ" and case.drill["answers"] == ["dem"]
    assert case.drill["options"] == ["der", "den", "dem"]
    assert case.drill["near"]["den"] == "mit takes the dative."


def test_case_drill_for_a_two_way_preposition(built):
    _, text = built
    case = next(c for c in drills_de.case_candidates(sentence(text, 4)))
    assert case.topic == "de:wechselpraepositionen" and case.drill["options"] == ["die", "der"]
    assert "wohin" in case.drill["rule"]


def test_contraction_picks_between_im_and_ins(built):
    _, text = built
    c = drills_de.contraction_candidates(sentence(text, 5))[0]
    assert c.drill["options"] == ["im", "ins"] and c.drill["answers"] == ["im"]
    assert c.drill["near"]["ins"].startswith("im = in dem")


def test_particle_gap(built):
    _, text = built
    c = drills_de.particle_candidates(sentence(text, 6))[0]
    assert c.drill["answers"] == ["an"] and c.drill["cue"] == "anrufen"


def test_present_form_drills_the_person(built):
    conn, text = built
    found = drills_de.form_candidates(sentence(text, 7), set(), drills.Forms(conn))
    choice = next(c for c in found if c.recipe == "form-choice" and c.topic == "de:praesens")
    assert choice.drill["answers"] == ["kaufst"]
    assert all(o in ("kaufe", "kauft", "kaufen", "kaufst") for o in choice.drill["options"])
    verb_last = [c for c in found if c.topic == "de:nebensaetze"]
    assert verb_last and all(c.drill["answers"] == ["hast"] for c in verb_last), "the verb after weil"


def test_order_keeps_a_noun_capital():
    s = {"id": "s1", "translation": "The woman goes home.", "text": "Frauen gehen nach Hause.",
         "tokens": [{"t": "Frauen", "pos": "NOUN"}, {"t": "gehen", "pos": "VERB"}, {"t": "nach", "pos": "ADP"},
                    {"t": "Hause", "pos": "NOUN"}, {"t": ".", "pos": "PUNCT"}]}
    assert drills_de.order_candidate(s, "de:verbstellung").drill["tiles"][0] == "Frauen"


@pytest.mark.parametrize("infinitive, participle, irregular", [
    ("machen", "gemacht", False), ("öffnen", "geöffnet", False), ("antworten", "geantwortet", False),
    ("wiederholen", "wiederholt", False), ("übersetzen", "übersetzt", False), ("atmen", "geatmet", False),
    ("gehen", "gegangen", True), ("bringen", "gebracht", True), ("kennen", "gekannt", True),
])
def test_irregular_participles(infinitive, participle, irregular):
    assert drills_de.is_irregular_participle(infinitive, participle) is irregular


def test_german_keys_keep_umlauts():
    from maestro_content.normalize import german_key
    assert german_key("hatte") != german_key("hätte") and german_key("fahrt") != german_key("fährt")
    assert german_key("haeuser") == german_key("Häuser") and german_key("strasse") == german_key("Straße")
    assert german_key("abenteuerbuecher") == german_key("Abenteuerbücher")


def linked(conn, text):
    tokens, units, _ = packs_de.link_sentence(packs.Lexicon(conn), packs.SourceSentence(text=text, translation=""))
    return {"id": "s1", "text": text, "translation": "", "tokens": tokens, "units": units}


def test_case_drill_without_a_preposition_names_only_the_case(built):
    _, text = built
    case = next(c for c in drills_de.case_candidates(sentence(text, 3)))
    assert case.drill["answers"] == ["das"] and set(case.drill["near"].values()) == {"Here it's in the accusative."}


def test_aux_rule_follows_the_sentence_order(built):
    conn, _ = built
    s = linked(conn, "Ich esse, weil ich Brot gegessen habe.")
    aux = next(c for c in drills_de.compound_candidates(s, TOPIC_INFO) if c.recipe == "aux")
    assert aux.drill["rule"] == "essen takes haben: gegessen … habe."
