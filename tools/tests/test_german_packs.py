"""German text packs: linking cases, contractions, verb forms, separable verbs and compound tenses."""

import json
import os

import pytest

from maestro_content import build_db, kaikki, packs, packs_de
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample-de.jsonl")


@pytest.fixture(scope="module")
def lex(tmp_path_factory):
    path = tmp_path_factory.mktemp("de") / "content.sqlite"
    conn = build_db.create(str(path), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE), "de")
    build_db.build(conn, entries, form_of, Registry(language="de"))
    return packs.Lexicon(conn)


def link(lex, text):
    clean, hints = packs._strip_hints(text)
    tokens, units, warnings = packs_de.link_sentence(lex, packs.SourceSentence(text=clean, translation="", hints=hints))
    return {t["t"]: t for t in tokens}, units, warnings


def test_noun_phrase_agrees_with_its_preposition_and_adjective(lex):
    tokens, _, _ = link(lex, "Das Kind isst im neuen Haus.")
    assert (tokens["Das"]["case"], tokens["Das"]["gn"]) == ("nom", "ns")
    assert tokens["Kind"]["case"] == "nom"
    im = tokens["im"]
    assert "pos" not in im and [p["t"] for p in im["parts"]] == ["in", "dem"]
    assert (im["parts"][1]["case"], im["parts"][1]["gn"]) == ("dat", "ns")
    assert (tokens["neuen"]["case"], tokens["neuen"]["gn"], tokens["neuen"]["decl"]) == ("dat", "ns", "wk")
    assert (tokens["Haus"]["case"], tokens["Haus"]["gn"]) == ("dat", "ns")
    assert "de:dativ" in im["grammar"] and "de:wechselpraepositionen" in im["grammar"]


def test_two_way_preposition_takes_the_accusative_for_a_direction(lex):
    tokens, _, _ = link(lex, "Wir gehen in die Stadt.")
    assert (tokens["die"]["case"], tokens["Stadt"]["case"], tokens["Stadt"]["gn"]) == ("acc", "acc", "fs")
    assert tokens["die"]["grammar"] == ["de:akkusativ"]
    tokens, _, _ = link(lex, "Gehst du ins Haus?")
    assert tokens["ins"]["parts"][1]["case"] == "acc" and tokens["Haus"]["case"] == "acc"


def test_subject_and_object(lex):
    tokens, _, _ = link(lex, "Der Mann kauft heute ein Brot.")
    assert (tokens["Mann"]["case"], tokens["Mann"]["gn"]) == ("nom", "ms")
    assert (tokens["ein"]["case"], tokens["Brot"]["case"]) == ("acc", "acc"), "the clause already has its subject"
    tokens, _, _ = link(lex, "Die Frau ist zum Bahnhof gegangen.")
    assert tokens["Frau"]["case"] == "nom", "a phrase that opens the sentence is the subject"
    assert tokens["zum"]["parts"][1]["gn"] == "ms" and tokens["Bahnhof"]["case"] == "dat"


def test_a_case_hint_decides(lex):
    tokens, _, warnings = link(lex, "Die Frau{acc} sehe ich.")
    assert tokens["Frau"]["case"] == "acc" and tokens["Die"]["case"] == "acc"
    assert tokens["Frau"]["lemmaID"] == "de:Frau:n"


def test_a_lone_determiner_is_a_pronoun(lex):
    tokens, _, _ = link(lex, "Das ist gut.")
    assert tokens["Das"]["pos"] == "PRON"


def test_verb_form_from_subject_and_clause(lex):
    tokens, _, _ = link(lex, "Wir gehen in die Stadt, weil wir Brot kaufen wollen.")
    assert tokens["gehen"]["form"] == "ind.pres.1p"
    assert tokens["kaufen"]["form"] == "inf.pres", "not the last verb of a subordinate clause"
    assert tokens["wollen"]["form"] == "ind.pres.1p" and tokens["wollen"]["pos"] == "AUX"
    assert tokens["weil"]["pos"] == "SCONJ"
    tokens, _, _ = link(lex, "Gehst du ins Haus?")
    assert tokens["Gehst"]["form"] == "ind.pres.2s" and tokens["du"]["case"] == "nom"


def test_polite_sie_is_third_person_plural(lex):
    tokens, _, _ = link(lex, "Kommen Sie heute?")
    assert tokens["Sie"]["lemmaID"] == "de:Sie:pron"
    assert tokens["Kommen"]["form"] == "ind.pres.3p"
    tokens, _, _ = link(lex, "Ich bin mit Ihnen gefahren.")
    assert tokens["Ihnen"]["lemmaID"] == "de:Sie:pron" and tokens["Ihnen"]["case"] == "dat"


def test_separable_verb_is_one_unit(lex):
    tokens, units, warnings = link(lex, "Ich rufe dich morgen an.")
    assert units == [{"tokens": [1, 4], "surface": "rufe … an", "lemmaID": "de:anrufen:v", "form": "ind.pres.1s",
                      "grammar": ["de:trennbare-verben"], "senseID": tokens["rufe"]["senseID"]}]
    assert tokens["rufe"]["lemmaID"] == "de:anrufen:v" and "lemmaID" not in tokens["an"]
    assert tokens["dich"]["case"] == "acc"
    assert warnings == [], "rufe is only in the dictionary joined to its particle"


def test_imperative_of_a_separable_verb(lex):
    _, units, _ = link(lex, "Ruf mich an!")
    assert units[0]["form"] == "imp.pres.2s" and units[0]["lemmaID"] == "de:anrufen:v"


def test_perfekt(lex):
    tokens, units, _ = link(lex, "Ich habe gestern mit dem Lehrer gegessen.")
    unit = units[0]
    assert (unit["tokens"], unit["surface"], unit["form"], unit["lemmaID"]) == \
        ([1, 6], "habe … gegessen", "ind.perf.1s", "de:essen:v")
    assert unit["grammar"] == ["de:perfekt"]
    assert tokens["habe"]["pos"] == "AUX" and tokens["gegessen"]["form"] == "part.pass"
    assert (tokens["dem"]["case"], tokens["dem"]["gn"], tokens["Lehrer"]["gn"]) == ("dat", "ms", "ms")


def test_perfekt_with_sein_and_a_verb_that_takes_both(lex):
    _, units, _ = link(lex, "Ich bin mit Ihnen gefahren.")
    assert units[0]["form"] == "ind.perf.1s+s"
    _, units, _ = link(lex, "Die Frau ist zum Bahnhof gegangen.")
    assert units[0]["form"] == "ind.perf.3s", "gehen only takes sein"


def test_compound_tense_in_a_subordinate_clause(lex):
    _, units, _ = link(lex, "Ich esse, weil ich nichts gegessen habe.")
    assert [(u["surface"], u["form"]) for u in units] == [("gegessen habe", "ind.perf.1s")]


def test_plusquamperfekt_and_konjunktiv(lex):
    _, units, _ = link(lex, "Er hatte das Brot gekauft.")
    assert units[0]["form"] == "ind.pqp.3s" and "grammar" not in units[0]
    _, units, _ = link(lex, "Ich wäre gern gekommen.")
    assert units[0]["form"] == "k2.pqp.1s" and units[0]["grammar"] == ["de:konjunktiv-2"]


def test_futur_and_wuerde(lex):
    tokens, units, _ = link(lex, "Morgen werde ich nach Hause fahren.")
    assert tokens["fahren"]["form"] == "inf.pres"
    assert (units[0]["surface"], units[0]["form"]) == ("werde … fahren", "ind.fut1.1s")
    _, units, _ = link(lex, "Ich würde gern ein Haus kaufen.")
    assert units[0]["form"] == "k2.wuerde.1s" and units[0]["grammar"] == ["de:konjunktiv-2"]


def test_a_participle_after_sein_that_takes_haben_is_no_compound(lex):
    _, units, _ = link(lex, "Das Brot ist gekauft.")
    assert units == []


def test_source_ids_get_the_prefix_and_files_do_not(tmp_path):
    folder = tmp_path / "content" / "de" / "texts" / "alltag"
    folder.mkdir(parents=True)
    path = folder / "alltag-01.md"
    path.write_text("# Ein Tag\nlevel: A1\ncollection: alltag\norder: 1\nintroduces: perfekt\n\n"
                    "Ich rufe dich an. || I'll call you.\n@unit rufe an | grammar=trennbare-verben\n", encoding="utf-8")
    src = packs.parse_source(str(path))
    assert src.language == "de" and src.id == "de:alltag-01" and src.file_name == "texts/alltag-01.json"
    assert src.introduces == ["de:perfekt"]
    assert src.blocks[0].sentences[0].units[0]["grammar"] == ["de:trennbare-verben"]
    italian = packs.parse_source(os.path.join(ROOT, "content", "it", "texts", "primi-passi", "primi-passi-01.md"))
    assert italian.language == "it" and ":" not in italian.id


def test_build_all_writes_a_german_pack(lex, tmp_path):
    folder = tmp_path / "texts" / "alltag"
    folder.mkdir(parents=True)
    (folder / "alltag-01.md").write_text(
        "# Im Haus\nlevel: A1\ncollection: alltag\norder: 1\nstatus: draft\n\n"
        "Das Kind isst im neuen Haus. || The child eats in the new house.\n"
        "Ich rufe dich morgen an. || I'll call you tomorrow.\n\n"
        "?? Wo isst das Kind? || Where does the child eat? @s1\n- Im Haus || In the house\n"
        "* Im neuen Haus || In the new house\n", encoding="utf-8")
    out = tmp_path / "packs"
    warnings, errors = packs.build_all(lex.conn, str(tmp_path / "texts"), str(out), "1", language="de")
    assert errors == []
    manifest = json.loads((out / "alltag" / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["texts"][0]
    assert manifest["language"] == "de" and entry["id"] == "de:alltag-01" and entry["file"] == "texts/alltag-01.json"
    assert "de:anrufen:v" in entry["lemmas"] and "de:wechselpraepositionen" in entry["grammar"]["uses"]
    text = json.loads((out / "alltag" / "texts" / "alltag-01.json").read_text(encoding="utf-8"))
    assert text["id"] == "de:alltag-01"
    counts = packs.text_lemmas(text)
    assert counts["de:anrufen:v"] == 1, "the separable verb counts once"
    assert lex.conn.execute("SELECT id FROM catalog_text").fetchone()[0] == "de:alltag-01"


def test_verbs_after_zu_and_coordinators(lex):
    tokens, _, _ = link(lex, "Wir wollen Brot kaufen und essen.")
    assert tokens["wollen"]["form"] == "ind.pres.1p"
    assert tokens["kaufen"]["form"] == "inf.pres" and tokens["essen"]["form"] == "inf.pres", \
        "after und, a verb takes the form of the verb before it"
    tokens, _, _ = link(lex, "Wir kaufen Brot und essen.")
    assert tokens["essen"]["form"] == "ind.pres.1p"
    tokens, _, _ = link(lex, "Ich gehe in die Stadt, um Brot zu kaufen.")
    assert tokens["gehe"]["form"] == "ind.pres.1s"
    assert tokens["kaufen"]["form"] == "inf.pres", "a clause of zu-infinitives has no finite verb"


def test_the_auxiliary_counts_wherever_it_stands(lex):
    for text, aux in (("Ich esse, weil ich Brot gegessen habe.", "de:haben:v"),
                      ("Ich gehe, weil ich essen werde.", "de:werden:v"),
                      ("Ich habe Brot gegessen.", "de:haben:v")):
        clean, hints = packs._strip_hints(text)
        tokens, units, _ = packs_de.link_sentence(lex, packs.SourceSentence(text=clean, translation="", hints=hints))
        counts = packs.text_lemmas({"blocks": [{"sentences": [{"tokens": tokens, "units": units}]}]})
        assert counts[aux] == 1, text
        assert units and counts[units[-1]["lemmaID"]] >= 1


def test_words_spelled_like_determiners(lex):
    tokens, _, _ = link(lex, "Habt ihr Hunger?")
    assert tokens["ihr"]["pos"] == "PRON" and tokens["Habt"]["form"] == "ind.pres.2p"
    tokens, _, _ = link(lex, "Seid ihr gut?")
    assert tokens["ihr"]["pos"] == "PRON"
    tokens, _, _ = link(lex, "Ich kaufe mein Brot.")
    assert tokens["mein"]["pos"] == "DET"


def test_an_object_that_opens_the_sentence(lex):
    tokens, _, _ = link(lex, "Das Brot esse ich.")
    assert tokens["Brot"]["case"] == "acc" and "de:akkusativ" in tokens["Das"]["grammar"]


def test_subordinators_that_are_also_prepositions_and_relative_clauses(lex):
    tokens, _, _ = link(lex, "Bis du kommst, esse ich.")
    assert tokens["Bis"]["pos"] == "SCONJ" and tokens["kommst"]["form"] == "ind.pres.2s"
    tokens, _, _ = link(lex, "Ich esse bis morgen.")
    assert tokens["bis"]["pos"] == "ADP"
    tokens, _, _ = link(lex, "Das ist das Brot, das ich essen will.")
    assert tokens["essen"]["form"] == "inf.pres" and tokens["will"]["form"] == "ind.pres.1s"


def test_coordinated_subjects_and_clauses(lex):
    tokens, _, _ = link(lex, "Die Frau und ich essen Brot.")
    assert tokens["Frau"]["case"] == "nom" and "de:akkusativ" not in tokens["Die"].get("grammar", [])
    tokens, _, _ = link(lex, "Die Frau kauft Brot und ich esse.")
    assert tokens["Frau"]["case"] == "nom" and tokens["esse"]["form"] == "ind.pres.1s"
    tokens, _, _ = link(lex, "Ich kaufe Brot und wir essen.")
    assert tokens["essen"]["form"] == "ind.pres.1p", "und before a subject opens a new main clause"
    tokens, units, _ = link(lex, "Ich habe Brot und ein Haus gekauft.")
    assert any(u["lemmaID"] == "de:kaufen:v" for u in units), "und between two objects keeps one clause"
    assert tokens["Haus"]["case"] == "acc"
    tokens, units, _ = link(lex, "Ich rufe den Mann und die Frau an.")
    assert any(u["lemmaID"] == "de:anrufen:v" for u in units)
    tokens, _, _ = link(lex, "Ich bleibe hier, weil ich Brot kaufe und wir essen wollen.")
    assert tokens["wollen"]["form"] == "ind.pres.1p" and tokens["essen"]["form"] == "inf.pres", \
        "a clause joined by und inside a subordinate clause is verb-final too"
    tokens, _, _ = link(lex, "Ich bleibe hier, weil ich Brot kaufe und wir wollen heute essen.")
    assert tokens["wollen"]["form"] == "ind.pres.1p" and tokens["essen"]["form"] == "inf.pres", \
        "a clause joined by und whose verb isn't last is a main clause"
    tokens, _, _ = link(lex, "Ich kaufe Brot und dann essen wir.")
    assert tokens["essen"]["form"] == "ind.pres.1p", "und before an inverted main clause"


def test_grammar_points_a_token_shows_by_itself(lex):
    tokens, _, _ = link(lex, "Morgen werde ich nach Hause fahren.")
    assert "de:verbstellung" in tokens["werde"]["grammar"], "verb second after something other than the subject"
    tokens, _, _ = link(lex, "Ich werde morgen fahren.")
    assert "grammar" not in tokens["werde"]
    tokens, _, _ = link(lex, "Das Kind isst im neuen Haus.")
    assert "de:adjektivdeklination" in tokens["neuen"]["grammar"]
    tokens, _, _ = link(lex, "Am Montag kauft er ein Brot.")
    assert "de:praepositionen-zeit" in tokens["Am"]["grammar"]
    tokens, _, _ = link(lex, "Der Mann ist nicht gut.")
    assert tokens["nicht"]["grammar"] == ["de:negation"]
    tokens, _, _ = link(lex, "Mein Kind ist besser.")
    assert tokens["Mein"]["grammar"] == ["de:possessivartikel"]
    assert tokens["besser"]["grammar"] == ["de:komparation"]
    for text, verb in (("Er kauft sich ein Brot.", "kauft"), ("Ich rufe sie morgen an.", "rufe"),
                       ("Sie kaufen es heute.", "kaufen"), ("Der Mann kauft es.", "kauft")):
        tokens, _, _ = link(lex, text)
        assert "de:verbstellung" not in tokens[verb].get("grammar", []), f"the subject comes first: {text}"
    tokens, _, _ = link(lex, "Morgen kauf ihr Brot!")
    assert "de:verbstellung" not in tokens["kauf"].get("grammar", []), "an imperative has no subject"
    tokens, _, _ = link(lex, "Dann kaufen Sie Brot!")
    assert "de:verbstellung" not in tokens["kaufen"].get("grammar", []), "a Sie imperative"
    tokens, _, _ = link(lex, "Dann kaufen Sie Brot.")
    assert "de:verbstellung" in tokens["kaufen"]["grammar"]
    tokens, _, _ = link(lex, "Ich esse, aber morgen kaufe ich Brot.")
    assert "de:verbstellung" in tokens["kaufe"]["grammar"], "a leading aber stands outside the clause"
    tokens, _, _ = link(lex, "Wenn du kommst, esse ich Brot.")
    assert "de:verbstellung" in tokens["esse"]["grammar"], "after a subordinate clause"
    tokens, _, _ = link(lex, "Die Frau, die ich kenne, kauft sie.")
    assert "de:verbstellung" not in tokens["kauft"].get("grammar", []), "a relative clause inside the subject"
    tokens, _, _ = link(lex, "Doch kauft er Brot.")
    assert "de:verbstellung" in tokens["kauft"]["grammar"], "doch as an adverb takes the first place"


def test_a_positive_spelled_like_a_comparative():
    kleiner = packs_de.Info(pos="adj", tags=["str.nom.ms", "mix.nom.ms", "comp"])
    assert not packs_de._is_comparison({"t": "kleiner", "decl": "mix", "case": "nom", "gn": "ms"}, kleiner), \
        "ein kleiner Hund"
    assert packs_de._is_comparison({"t": "kleiner"}, kleiner), "der Hund ist kleiner"
    kleinerer = packs_de.Info(pos="adj", tags=["comp.mix.nom.ms"])
    assert packs_de._is_comparison({"t": "kleinerer", "decl": "mix", "case": "nom", "gn": "ms"}, kleinerer)


def test_the_german_texts_build(lex, tmp_path):
    """Every German text builds with the sample dictionary: ranges, units and questions are sound."""
    texts = os.path.join(ROOT, "content", "de", "texts")
    if not os.path.isdir(texts):
        pytest.skip("no German texts on this branch")
    from maestro_content import grammar
    topics = grammar.load_all(os.path.join(ROOT, "content", "de", "grammar"), "de")
    _, errors = packs.build_all(lex.conn, texts, str(tmp_path / "packs"), "1", topics=topics, language="de")
    assert errors == []
    manifests = sorted(p.name for p in (tmp_path / "packs").iterdir())
    assert manifests == ["alltag", "erste-schritte"]
    for name in manifests:
        manifest = json.loads((tmp_path / "packs" / name / "manifest.json").read_text(encoding="utf-8"))
        assert all(t["id"].startswith("de:") and t["status"] == "draft" for t in manifest["texts"])
