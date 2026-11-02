import json
import os

import pytest

from maestro_content import build_db, drills, grammar, kaikki, packs
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample.jsonl")
TOPICS = {t.id: drills.TopicInfo(t.id, t.title, t.level, t.order, t.summary)
          for t in grammar.load_all(os.path.join(ROOT, "content", "it", "grammar"))}


@pytest.fixture()
def db(tmp_path):
    conn = build_db.create(str(tmp_path / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE))
    build_db.build(conn, entries, form_of, Registry())
    return conn


SOURCE = """# Test
level: B1
collection: test-pack
order: 1
introduces: passato-prossimo

Quando eravamo ragazzi, andavamo ogni estate dai nonni. || When we were kids, we went to our grandparents' every summer.
Noi siamo andati a Bologna in treno. || We went to Bologna by train.
Mio padre decise che saremmo andati a Bologna. || My father decided that we would go to Bologna.
@unit saremmo andati | grammar=future-in-the-past | gloss=we would go | note=Future in the past.
Il nonno ha mangiato con noi. || Grandpa ate with us.
"""


def built(db, tmp_path, source=SOURCE):
    src_dir = tmp_path / "texts"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "test-01.md").write_text(source, encoding="utf-8")
    grammar_topics = grammar.load_all(os.path.join(ROOT, "content", "it", "grammar"))
    warnings, errors = packs.build_all(db, str(src_dir), str(tmp_path / "packs"), "2026.10", topics=grammar_topics)
    assert errors == []
    return json.loads((tmp_path / "packs" / "test-pack" / "texts" / "test-01.json").read_text(encoding="utf-8"))


def test_compound_tense_drills_come_from_the_text(db, tmp_path):
    text = built(db, tmp_path)
    ds = text["drills"]
    assert ds and [d["id"] for d in ds] == [f"d{n}" for n in range(1, len(ds) + 1)]
    main = [d for d in ds if not d.get("recycled")]
    assert {d["topic"] for d in main} == {"passato-prossimo"}
    aux = next(d for d in ds if d["recipe"] == "aux")
    assert len(aux["options"]) == 2 and set(aux["answers"]) <= set(aux["options"])
    assert aux["options"] in (["abbiamo", "siamo"], ["ha", "è"])  # avere first, whichever is right
    wrong = next(o for o in aux["options"] if o not in aux["answers"])
    assert "takes" in aux["near"][wrong]
    build = next(d for d in ds if d["recipe"] == "order")
    assert sum(1 for d in ds if d["sentence"] == build["sentence"]) == 1
    assert drills.validate(text, ds) == []


def test_agreement_offers_every_ending(db, tmp_path):
    text = built(db, tmp_path)
    s2 = text["blocks"][0]["sentences"][1]
    agreement = next(c.drill for c in drills.compound_candidates(text, s2, TOPICS) if c.recipe == "agreement")
    assert agreement["options"] == ["andato", "andata", "andati", "andate"]
    assert agreement["answers"] == ["andati"]
    assert agreement["before"].endswith("siamo ") and agreement["after"].startswith(" a Bologna")


def test_recycled_drills_practise_an_earlier_topic(db, tmp_path):
    text = built(db, tmp_path)
    recycled = [d for d in text["drills"] if d.get("recycled")]
    assert 1 <= len(recycled) <= drills.RECYCLED_DRILLS
    order = {t: TOPICS[t].order for t in TOPICS}
    assert all(order[d["topic"]] < order["passato-prossimo"] for d in recycled)


def test_no_drills_without_enough_material(db, tmp_path):
    text = built(db, tmp_path, "# Ciao\nlevel: A1\ncollection: test-pack\norder: 1\n\nCiao. || Hi.\n")
    assert text["drills"] == []


def fixture_text():
    with open(os.path.join(ROOT, "content", "fixtures", "racconti-brevi-03.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_hand_marked_unit_becomes_a_gap():
    text = fixture_text()
    ds = drills.generate(text, ["future-in-the-past"], TOPICS)
    unit = next(d for d in ds if d["recipe"] == "unit")
    assert unit["answers"] == ["saremmo andati"] and unit["cue"] == "we would go"
    assert unit["kind"] == "gap" and unit["rule"].startswith("Future in the past")
    assert drills.validate(text, ds) == []


def test_contraction_options_share_the_preposition():
    text = fixture_text()
    s1 = text["blocks"][0]["sentences"][0]
    c = drills.contraction_candidates(s1)[0].drill
    assert c["answers"] == ["dai"] and set(c["options"]) <= {"dai", "dagli", "dalle"}
    assert c["near"]["dagli"] == "nonni takes i."


def test_build_uses_every_tile_once():
    sentence = {"id": "s1", "text": "Noi siamo andati a Bologna.", "translation": "We went to Bologna.",
                "tokens": [{"t": "Noi", "r": [0, 3], "pos": "PRON"}, {"t": "siamo", "r": [4, 5], "pos": "AUX",
                           "lemmaID": "it:essere:v", "form": "ind.pres.1p"},
                           {"t": "andati", "r": [10, 6], "pos": "VERB", "lemmaID": "it:andare:v", "form": "part.pass"},
                           {"t": "a", "r": [17, 1], "pos": "ADP"}, {"t": "Bologna", "r": [19, 7], "pos": "PROPN"},
                           {"t": ".", "r": [26, 1], "pos": "PUNCT"}],
                "units": [{"tokens": [1, 2], "surface": "siamo andati", "lemmaID": "it:andare:v",
                           "form": "ind.pp.1p", "agree": "mp", "grammar": ["passato-prossimo"]}]}
    build = drills.order_candidate(sentence, "passato-prossimo").drill
    assert build["tiles"] == ["noi", "siamo", "andati", "a", "Bologna"]
    assert build["answers"] == ["noi siamo andati a Bologna"] and build["distractors"] == ["abbiamo"]


class FakeForms:
    def __init__(self, rows):
        self.rows = rows

    def of(self, lemma_id):
        return self.rows


def test_form_choice_names_the_wrong_tense():
    sentence = {"id": "s1", "text": "Va bene.", "tokens": [
        {"t": "Va", "r": [0, 2], "pos": "VERB", "lemmaID": "it:andare:v", "form": "ind.pres.3s"},
        {"t": "bene", "r": [3, 4], "pos": "ADV"}, {"t": ".", "r": [7, 1], "pos": "PUNCT"}]}
    forms = FakeForms([("va", "ind.pres.3s"), ("vada", "imp.pres.3s"), ("vada", "sub.pres.3s"),
                       ("andò", "ind.prem.3s"), ("vai", "ind.pres.2s"), ("andava", "ind.impf.3s")])
    cands = drills.form_candidates(sentence, set(), forms)
    choice = next(c.drill for c in cands if c.recipe == "form-choice")
    assert "Va" in choice["options"] and len(choice["options"]) == 3
    gap = next(c.drill for c in cands if c.recipe == "form").copy()
    assert gap["near"]["vada"] == "That's the congiuntivo presente. We need the presente."
    assert gap["near"]["vai"] == "Check the person: we need lui, lei."
    assert gap["cue"] == "andare, lui, lei"


def test_validate_catches_a_broken_gap():
    text = fixture_text()
    bad = [{"id": "d1", "kind": "gap", "sentence": "s1", "before": "x", "after": "y", "r": [0, 6],
            "answers": ["Quando"]}]
    assert any("rebuild" in e for e in drills.validate(text, bad))


def test_grammar_base_points_at_real_topics():
    topics = grammar.load_all(os.path.join(ROOT, "content", "it", "grammar"))
    points = grammar.load_base(os.path.join(ROOT, "content", "it", "grammar", "base.yaml"))
    assert len(points) == 351
    assert grammar.check_base(points, topics) == []
    covered = {p.topic for p in points if p.topic}
    assert {"passato-prossimo", "articles", "si-impersonale"} <= covered
    assert next(p for p in points if p.id == "art_un_una").label == "Articoli indeterminativi singolari un una un'"


def test_the_answer_is_not_always_in_the_same_place(db, tmp_path):
    text = built(db, tmp_path)
    fixture = fixture_text()
    choices = [d for d in text["drills"] + drills.generate(fixture, ["future-in-the-past"], TOPICS)
               if d["kind"] == "choice"]
    places = {d["options"].index(d["answers"][0]) for d in choices}
    assert len(choices) >= 3 and len(places) >= 2
    s1 = fixture["blocks"][0]["sentences"][0]
    sentence = {"id": "s9", "text": "Va bene.", "tokens": [
        {"t": "Va", "r": [0, 2], "pos": "VERB", "lemmaID": "it:andare:v", "form": "ind.pres.3s"},
        {"t": "bene", "r": [3, 4], "pos": "ADV"}, {"t": ".", "r": [7, 1], "pos": "PUNCT"}]}
    forms = FakeForms([("va", "ind.pres.3s"), ("andò", "ind.prem.3s"), ("andava", "ind.impf.3s")])
    choice = next(c.drill for c in drills.form_candidates(sentence, set(), forms) if c.recipe == "form-choice")
    contraction = drills.contraction_candidates(s1)[0].drill
    for d, sid in ((choice, "s9"), (contraction, s1["id"])):
        assert d["options"] == sorted(d["options"], key=lambda o: drills._seed(sid, drills.fold(o)))


BUSY = """# Busy
level: A2
collection: test-pack
order: 1
introduces: passato-prossimo

Sabato sono andata al mercato con la mamma. || On Saturday I went to the market with Mum.
Abbiamo preso il pane dal fornaio. || We got bread from the baker.
Poi sono passata dal formaggiaio. || Then I stopped at the cheesemonger's.
Il nonno ha mangiato con noi. || Grandpa ate with us.
La zia è arrivata alle dieci. || My aunt arrived at ten.
Noi siamo andati a Bologna in treno. || We went to Bologna by train.
Ho fatto la spesa nel negozio. || I did the shopping in the shop.
Hanno visto il mare dalla finestra. || They saw the sea from the window.
Abbiamo dato un libro ai bambini. || We gave the children a book.
"""


def test_a_busy_text_still_gets_at_most_eight_drills(db, tmp_path):
    text = built(db, tmp_path, BUSY)
    ds = text["drills"]
    assert drills.MIN_DRILLS <= len(ds) <= drills.MAX_DRILLS
    assert drills.validate(text, ds) == []
    assert drills.validate(text, ds * 2)[0].endswith(f"more than {drills.MAX_DRILLS}")


def test_the_cap_holds_when_every_recipe_has_material(monkeypatch):
    # The sample dictionary knows too few verbs to fill every recipe, so the pool is faked:
    # two own drills per sentence, a match, a build and three earlier topics to recycle.
    sentences = [{"id": f"s{n}", "text": "x", "translation": "x", "tokens": []} for n in range(1, 11)]
    text = {"id": "busy-01", "level": "A2", "blocks": [{"sentences": sentences}]}

    def fake(recipe, topic, sid, kind="gap"):
        return drills.Candidate(recipe, topic, sid, {"kind": kind})

    pool = [fake(r, "passato-prossimo", s["id"]) for s in sentences for r in ("aux", "participle")]
    pool += [fake("article", t, s["id"]) for t in ("articles", "presente-indicativo", "preposition-contractions")
             for s in sentences]
    monkeypatch.setattr(drills, "candidates", lambda *_: pool)
    monkeypatch.setattr(drills, "participles_match", lambda t, topic: fake("participles", topic, "s1", "match"))
    monkeypatch.setattr(drills, "order_candidate", lambda s, topic: fake("order", topic, s["id"], "build"))
    ds = drills.generate(text, ["passato-prossimo"], TOPICS)
    assert len(ds) == drills.MAX_DRILLS
    assert sum(1 for d in ds if d.get("recycled")) == drills.RECYCLED_DRILLS
    assert {"participles", "order"} <= {d["recipe"] for d in ds}


def test_match_pairs_never_repeat_a_participle():
    for d in fixture_text()["drills"]:
        if d["kind"] == "match":
            assert len({b for _, b in d["pairs"]}) == len(d["pairs"])
