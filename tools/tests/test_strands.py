import json
import os

import pytest

from maestro_content import build_db, drills, functions, grammar, kaikki, packs, patterns, strands
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample.jsonl")
INVENTORY = functions.load(os.path.join(ROOT, "content", "it", "functions.yaml"))


@pytest.fixture()
def db(tmp_path):
    conn = build_db.create(str(tmp_path / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE))
    build_db.build(conn, entries, form_of, Registry())
    return conn


def built(db, tmp_path, source, known_ranks=None, inventory=None):
    src_dir = tmp_path / "texts"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "test-01.md").write_text(source, encoding="utf-8")
    topics = grammar.load_all(os.path.join(ROOT, "content", "it", "grammar"))
    warnings, errors = packs.build_all(db, str(src_dir), str(tmp_path / "packs"), "2026.10", topics=topics,
                                       known_ranks=known_ranks or {}, inventory=INVENTORY if inventory is None else inventory)
    assert errors == []
    return json.loads((tmp_path / "packs" / "test-pack" / "texts" / "test-01.json").read_text(encoding="utf-8"))


PROSE = """# Test
level: B1
collection: test-pack
order: 1
introduces: passato-prossimo

Quando eravamo ragazzi, andavamo ogni estate dai nonni. || When we were kids, we went to our grandparents' every summer.
Noi siamo andati a Bologna in treno. || We went to Bologna by train.
Il nonno ha mangiato con noi. || Grandpa ate with us.
Il ragazzo mangia una pesca. || The boy eats a peach.
@gloss pesca = peach
Domani andiamo al mare e corriamo sulla spiaggia. || Tomorrow we go to the sea and run on the beach.
"""

DIALOGUE = """# Plans
level: A2
collection: test-pack
order: 1
speakers: Chiara f, Sara f

> Chiara: Ciao Sara, sei libera venerdì sera? || Hi Sara, are you free on Friday evening?
@fn ask-plans
> Sara: Credo di sì, perché? || I think so, why?
@fn say-unsure
@accept {Credo di sì|Penso di sì}(, perché)?
> Chiara: C'è un concerto jazz al parco, vieni con me? || There's a jazz concert in the park, will you come with me?
@fn invite
> Sara: Volentieri! A che ora comincia? || Gladly! What time does it start?
@fn accept
@accept {Volentieri|Con piacere}! A che ora {comincia|inizia}?
> Chiara: Alle nove. || At nine.
@fn say-time
> Sara: Allora a venerdì! || See you on Friday, then!
@fn confirm
"""


def strand(text, name):
    return [d for d in text["drills"] if d["strand"] == name]


def test_every_drill_has_a_strand_and_a_unique_key(db, tmp_path):
    text = built(db, tmp_path, PROSE)
    ds = text["drills"]
    assert {d["strand"] for d in ds} >= {"grammar", "verbs", "words"}
    assert len({d["key"] for d in ds}) == len(ds)
    assert all(d.get("core") for d in strand(text, "verbs")[:strands.CORE])
    assert drills.validate(text, ds) == []


def test_keys_stay_the_same_from_build_to_build(db, tmp_path):
    first = {d["recipe"] + d["sentence"]: d["key"] for d in built(db, tmp_path, PROSE)["drills"]}
    again = {d["recipe"] + d["sentence"]: d["key"] for d in built(db, tmp_path, PROSE)["drills"]}
    assert first == again
    # A key hashes what the drill asks, not its place in the list.
    d = next(x for x in built(db, tmp_path, PROSE)["drills"] if x["recipe"] == "participle")
    assert d["key"] == drills.drill_hash("test-01", {**d, "id": "d99"}, set())


def test_new_words_skip_what_the_level_knows(db, tmp_path):
    every = built(db, tmp_path, PROSE)["newWords"]
    assert len(every) == strands.NEW_WORDS and {"nonno", "treno"} <= {w["word"] for w in every}
    db.execute("UPDATE lemma SET freq_rank = 1")
    known = built(db, tmp_path, PROSE, known_ranks={"B1": 100})["newWords"]
    assert [w["word"] for w in known] == ["pesca"], "a hand-glossed word is new whatever its rank"
    assert known[0]["gloss"] == "peach"


def test_sense_choice_offers_the_meaning_here(db, tmp_path):
    text = built(db, tmp_path, PROSE)
    choice = next(d for d in strand(text, "words") if d["recipe"] == "sense-choice")
    assert choice["optionLang"] == "en" and choice["answers"][0] in choice["options"]
    assert len(choice["options"]) == 3 and len(set(choice["options"])) == 3
    s = next(x for b in text["blocks"] for x in b["sentences"] if x["id"] == choice["sentence"])
    start, length = choice["focus"]
    assert s["text"][start:start + length] == choice["cue"]


def test_verbs_strand_rows_and_switches(db, tmp_path):
    text = built(db, tmp_path, PROSE)
    verbs = strand(text, "verbs")
    row = next(d for d in verbs if d["kind"] == "row")
    assert [c["p"] for c in row["cells"]] == ["1s", "2s", "3s", "1p", "2p", "3p"]
    assert sum(c["given"] for c in row["cells"]) == 3
    s = next(x for b in text["blocks"] for x in b["sentences"] if x["id"] == row["sentence"])
    own = s["text"][row["focus"][0]:sum(row["focus"])]
    assert any(c["given"] and drills.fold(c["forms"][0]) == drills.fold(own) for c in row["cells"])
    ident = next(d for d in verbs if d["recipe"] == "form-identify")
    assert len(ident["options"]) == 3 and ident["answers"][0] in ident["options"]
    assert all(v.startswith("Check the") for v in ident["near"].values())
    switch = next(d for d in verbs if d["recipe"] == "person-switch")
    assert switch["answers"] and "before" not in switch


def test_text_verbs_carry_form_tags(db, tmp_path):
    from maestro_content import tags
    text = built(db, tmp_path, PROSE)
    assert text["verbs"]
    assert all(tags.is_valid(v["form"]) for v in text["verbs"])


def test_find_drill_marks_every_compound(db, tmp_path):
    text = built(db, tmp_path, PROSE)
    find = next(d for d in text["drills"] if d["kind"] == "find")
    assert find["strand"] == "grammar" and find["core"] and find["topic"] == "passato-prossimo"
    words = {next(x for b in text["blocks"] for x in b["sentences"] if x["id"] == t["s"])["tokens"][t["t"]]["t"]
             for t in find["targets"]}
    assert {"siamo", "andati", "ha", "mangiato"} <= words
    assert len(find["sentences"]) > len({t["s"] for t in find["targets"]}), "a line without targets is shown too"


def test_say_it_from_function_tags(db, tmp_path):
    text = built(db, tmp_path, DIALOGUE)
    say = strand(text, "say")
    pick = next(d for d in say if d["recipe"] == "function-pick")
    assert pick["answers"] == ["Asking about someone's plans"] and pick["optionLang"] == "en"
    produce = next(d for d in say if d["kind"] == "say")
    expanded = {x for p in produce["accept"] for x in patterns.expand(p)}
    assert produce["answers"][0] in expanded
    assert {f["id"] for f in text["functions"]} >= {"invite", "accept"}
    assert all("accept" not in s for b in text["blocks"] for s in b["sentences"])


def test_roleplay_takes_the_side_with_more_tagged_lines(db, tmp_path):
    text = built(db, tmp_path, DIALOGUE)
    play = next(d for d in text["drills"] if d["kind"] == "roleplay")
    assert play["speaker"] == "Sara" and play["other"] == "Chiara" and play["core"]
    mine = [t for t in play["turns"] if "chips" in t]
    assert len(mine) == 3
    for t in mine:
        assert t["chips"].count(t["answers"][0]) == 1 and len(t["chips"]) == 3
        assert t["answers"][0] in {x for p in t["accept"] for x in patterns.expand(p)}
    accept = next(t for t in mine if t.get("goal") == "accept")
    assert "Con piacere! A che ora inizia?" in patterns.expand(accept["accept"][0])
    # The dialogue is about plans, so the wrong chips are things said in a shop.
    wrong = [c for t in mine for c in t["chips"] if c != t["answers"][0]]
    shop = {p for f in INVENTORY.values() if f.id in strands.TRANSACTION for p in f.phrases}
    assert set(wrong) <= shop


def test_an_unknown_function_fails_the_build(db, tmp_path):
    src = tmp_path / "texts"
    src.mkdir()
    (src / "test-01.md").write_text(DIALOGUE.replace("@fn invite", "@fn invitare"), encoding="utf-8")
    _, errors = packs.build_all(db, str(src), str(tmp_path / "packs"), "1", topics=[], inventory=INVENTORY)
    assert any("unknown function invitare" in e for e in errors)


def test_a_malformed_accept_fails_with_its_place(tmp_path):
    path = tmp_path / "test-01.md"
    line = next(l for l in DIALOGUE.splitlines() if l.startswith("@accept"))
    path.write_text(DIALOGUE.replace(line, "@accept {Volentieri|Con piacere!"), encoding="utf-8")
    with pytest.raises(packs.PackError, match="test-01.md.*@accept"):
        packs.parse_source(str(path))


def test_no_say_it_without_tags(db, tmp_path):
    text = built(db, tmp_path, PROSE)
    assert strand(text, "say") == [] and "functions" not in text


def test_patterns_expand_choices_and_options():
    assert patterns.expand("{Volentieri|Con piacere}!") == ["Volentieri!", "Con piacere!"]
    assert patterns.expand("Credo di sì(, perché)?") == ["Credo di sì?", "Credo di sì, perché?"]
    assert len(patterns.expand("{Ci vediamo|Vediamoci} (prima)")) == 4
    assert patterns.expand("(E) anche una brioche.") == ["anche una brioche.", "E anche una brioche."]
    with pytest.raises(patterns.PatternError):
        patterns.expand("{a|b")


def test_the_inventories_load():
    it = functions.load(os.path.join(ROOT, "content", "it", "functions.yaml"))
    de = functions.load(os.path.join(ROOT, "content", "de", "functions.yaml"), "de")
    assert "invite" in it and all(f.phrases for f in it.values())
    assert "de:introduce" in de and all(k.startswith("de:") for k in de)
    for inventory in (it, de):
        for f in inventory.values():
            for p in f.phrases:
                assert patterns.expand(p) == [p], p
