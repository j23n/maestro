"""The German dictionary pipeline: kaikki German entries, German form and case tags, de: IDs."""

import os

import pytest

from maestro_content import build_db, frequency, grammar, kaikki, tags
from maestro_content.registry import Registry, base_lemma_id

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample-de.jsonl")


def _read():
    return kaikki.read(kaikki.open_jsonl(SAMPLE), "de")


@pytest.fixture()
def db(tmp_path):
    conn = build_db.create(str(tmp_path / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = _read()
    build_db.build(conn, entries, form_of, Registry(language="de"))
    return conn


@pytest.mark.parametrize("source, expected", [
    (["first-person", "singular", "present", "indicative"], ["ind.pres.1s"]),
    (["first-person", "singular", "past", "indicative"], ["ind.prat.1s"]),
    (["third-person", "singular", "preterite"], ["ind.prat.3s"]),
    (["first-person", "third-person", "plural", "present"], ["ind.pres.1p", "ind.pres.3p"]),
    (["third-person", "singular", "present", "subjunctive-i"], ["k1.pres.3s"]),
    (["first-person", "singular", "past", "subjunctive-ii"], ["k2.prat.1s"]),
    (["imperative", "singular"], ["imp.pres.2s"]),
    (["imperative", "plural"], ["imp.pres.2p"]),
    (["infinitive"], ["inf.pres"]),
    (["infinitive", "zu"], ["inf.zu"]),
    (["participle", "present"], ["part.pres"]),
    (["participle", "past"], ["part.pass"]),
    (["participle", "perfect"], ["part.pass"]),
    (["first-person", "singular", "present", "subordinate-clause"], ["ind.pres.1s"]),
    (["first-person", "singular", "perfect", "indicative"], []),
    (["first-person", "singular", "future-i"], []),
    (["auxiliary"], []),
])
def test_verb_tags(source, expected):
    assert tags.kaikki_verb_tags_de(source) == expected
    assert all(tags.is_valid_de(t) for t in expected)


@pytest.mark.parametrize("source, gender, pos, expected", [
    (["genitive", "singular"], "n", "n", ["gen.ns"]),
    (["dative", "plural"], "n", "n", ["dat.pl"]),
    (["nominative", "accusative", "genitive", "plural"], "n", "n", ["nom.pl", "acc.pl", "gen.pl"]),
    (["genitive", "singular"], "?", "n", ["gen.s"]),
    (["diminutive", "neuter"], "n", "n", []),
    (["feminine"], "m", "n", []),
    (["masculine", "nominative", "singular", "strong"], None, "adj", ["str.nom.ms"]),
    (["dative", "plural", "weak"], None, "adj", ["wk.dat.pl"]),
    (["comparative"], None, "adj", ["comp"]),
    (["comparative", "masculine", "nominative", "singular", "strong"], None, "adj", ["comp.str.nom.ms"]),
    (["predicative"], None, "adj", []),
    (["dative", "masculine", "neuter", "singular"], None, "art", ["dat.ms", "dat.ns"]),
    (["accusative"], None, "pron", ["acc"]),
])
def test_case_tags(source, gender, pos, expected):
    assert tags.kaikki_case_tags_de(source, gender, pos) == expected
    assert all(tags.is_valid_de_case(t) for t in expected if not t.endswith(".s"))


def test_tag_validity():
    assert tags.is_valid_de("ind.perf.3s+s") and tags.is_valid_de("k2.wuerde.1s") and tags.is_valid_de("inf.perf")
    assert not tags.is_valid_de("ind.wuerde.1s") and not tags.is_valid_de("ind.pres.1s+e")
    assert not tags.is_valid_de("imp.pres.1s") and not tags.is_valid_de("cond.pres.1s")
    assert tags.is_valid_de_case("gen.ns") and tags.is_valid_de_case("sup")
    assert not tags.is_valid_de_case("gen.ms.x") and not tags.is_valid_de_case("str") and not tags.is_valid_de_case("mp")


def test_entries():
    entries, form_of = _read()
    by = {(e.headword, e.pos): e for e in entries}
    assert all(e.headword not in ("gift", "casa") for e in entries), "other languages are skipped"
    gehen = by[("gehen", "v")]
    assert gehen.auxiliary == "sein" and by[("fahren", "v")].auxiliary == "both"
    assert ("ging", "ind.prat.1s") in gehen.forms and ("ginge", "k2.prat.3s") in gehen.forms
    assert ("geh", "imp.pres.2s") in gehen.forms and ("gegangen", "part.pass") in gehen.forms
    assert not any(" " in f for f, _ in gehen.forms), "compound tenses and separated forms are dropped"
    assert [s.gloss for s in gehen.senses][0] == "to walk, to go"
    anrufen = dict((t, f) for f, t in by[("anrufen", "v")].forms)
    assert anrufen["ind.pres.1s"] == "anrufe" and anrufen["inf.zu"] == "anzurufen"
    haus = by[("Haus", "n")]
    assert haus.gender == "n" and haus.plural == "Häuser"
    assert ("Häusern", "dat.pl") in haus.forms and not any(f == "Häuschen" for f, _ in haus.forms)
    assert by[("Lehrer", "n")].gender == "m" and not any(f == "Lehrerin" for f, _ in by[("Lehrer", "n")].forms)
    assert by[("Gift", "n")].gender == "n"
    assert ("besser", "comp") in by[("gut", "adj")].forms
    assert any(fo.form == "dem" and fo.lemma == "der" and fo.tag == "dat.ns" for fo in form_of)


def test_every_tag_is_valid():
    entries, _ = _read()
    for e in entries:
        for form, tag in e.forms:
            valid = tags.is_valid_de(tag) if e.pos == "v" else tags.is_valid_de_case(tag)
            assert valid, (e.headword, form, tag)


def test_ids_keep_capitals_and_the_prefix():
    assert base_lemma_id("Haus", "n", "de") == "de:Haus:n"
    assert base_lemma_id("essen", "v", "de") == "de:essen:v"
    assert base_lemma_id("Haus", "n") == "it:haus:n", "Italian lowercases as before"
    reg = Registry(language="de")
    assert reg.lemma_id("Essen", "n", "Essen|n|food") == "de:Essen:n"
    assert reg.lemma_id("essen", "v", "essen|v|to eat") == "de:essen:v"


def test_database(db):
    ids = {r[0] for r in db.execute("SELECT id FROM lemma")}
    assert {"de:Haus:n", "de:Essen:n", "de:essen:v", "de:gehen:v", "de:gut:adj", "de:der:art"} <= ids
    assert all(i.startswith("de:") for i in ids)
    assert db.execute("SELECT id FROM sense WHERE lemma_id = 'de:gehen:v' ORDER BY ord").fetchone()[0].startswith("de:gehen:v#")
    rows = set(db.execute("SELECT tag FROM form WHERE form = 'ging' AND lemma_id = 'de:gehen:v'"))
    assert rows == {("ind.prat.1s",), ("ind.prat.3s",)}
    # A singular form-of entry takes its lemma's gender.
    assert db.execute("SELECT tag FROM form WHERE form = 'Hauses' AND lemma_id = 'de:Haus:n'").fetchall() == [("gen.ns",)]
    assert db.execute("SELECT gender, plural FROM lemma WHERE id = 'de:Haus:n'").fetchone() == ("n", "Häuser")
    assert db.execute("SELECT auxiliary FROM lemma WHERE id = 'de:fahren:v'").fetchone()[0] == "both"
    assert ("äße",) in db.execute("SELECT form FROM form WHERE form_fold = 'aße'").fetchall()


def test_lowercase_frequency_list_ranks_nouns(db, tmp_path):
    freq = tmp_path / "de.txt"
    freq.write_text("ich 900\nhaus 600\ngehen 300\nging 200\nessen 100\n", encoding="utf-8")
    frequency.assign_ranks(db, frequency.load(str(freq)), "de")
    ranks = dict(db.execute("SELECT id, freq_rank FROM lemma WHERE freq_rank IS NOT NULL"))
    assert ranks["de:Haus:n"] < ranks["de:gehen:v"]
    assert "de:Essen:n" in ranks and "de:essen:v" in ranks, "essen counts for the noun and the verb"


def test_grammar_ids_get_the_prefix():
    directory = os.path.join(ROOT, "content", "de", "grammar")
    if not os.path.isdir(directory):
        pytest.skip("no German grammar topics on this branch")
    topics = grammar.load_all(directory, "de")
    assert topics and all(t.id.startswith("de:") for t in topics)
    points = grammar.load_base(os.path.join(directory, "base.yaml"), "de")
    assert all(p.id.startswith("de:") for p in points)
    assert all(p.topic.startswith("de:") for p in points if p.topic)
    assert grammar.check_base(points, topics) == []
    italian = grammar.load_all(os.path.join(ROOT, "content", "it", "grammar"))
    assert not any(":" in t.id for t in italian)


def test_head_line_gives_auxiliary_and_plural():
    verb = {"word": "laufen", "pos": "verb", "lang_code": "de", "senses": [{"glosses": ["to run"]}],
            "head_templates": [{"name": "de-verb", "expansion": "laufen (class 7 strong, auxiliary sein or haben)"}]}
    assert kaikki.parse_de(verb)[0].auxiliary == "both"
    noun = {"word": "Baum", "pos": "noun", "lang_code": "de", "senses": [{"glosses": ["tree"]}],
            "head_templates": [{"name": "de-noun", "args": {"1": "m,es,^e"}}],
            "forms": [{"form": "Baumes", "tags": ["genitive"]}, {"form": "Bäume", "tags": ["plural"]}]}
    assert kaikki.parse_de(noun)[0].plural == "Bäume"


def test_form_of_without_a_lemma_gender_is_skipped(tmp_path):
    conn = build_db.create(str(tmp_path / "c.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    lemma = kaikki.Entry(headword="Leute", pos="n", senses=[kaikki.Sense(gloss="people")])
    form = kaikki.FormOf(form="Leuten", lemma="Leute", pos="n", tag="dat.s")
    stats = build_db.build(conn, [lemma], [form], Registry(language="de"))
    assert stats.ungendered_form_of == 1
    assert conn.execute("SELECT count(*) FROM form WHERE form = 'Leuten'").fetchone()[0] == 0


def test_form_of_whose_tags_name_no_form_is_skipped(tmp_path):
    raw = {"lang_code": "de", "word": "dem", "pos": "article",
           "senses": [{"tags": ["form-of", "definite"], "form_of": [{"word": "der"}], "glosses": ["the"]}]}
    _, forms = kaikki.parse_de(raw)
    assert [f.tag for f in forms] == [kaikki.UNTAGGED]
    conn = build_db.create(str(tmp_path / "c.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    lemma = kaikki.Entry(headword="der", pos="art", senses=[kaikki.Sense(gloss="the")])
    stats = build_db.build(conn, [lemma], forms, Registry(language="de"))
    assert stats.untagged_form_of == 1
    assert conn.execute("SELECT count(*) FROM form WHERE form = 'dem'").fetchone()[0] == 0


def test_article_rows_keep_definite_and_feminine_rows_of_two_gender_nouns():
    assert tags.kaikki_case_tags_de(["definite", "dative", "masculine", "singular"], None, "art") == ["dat.ms"]
    assert tags.kaikki_case_tags_de(["definite", "dative", "singular"], "n", "n") == []
    assert tags.kaikki_case_tags_de(["feminine", "dative", "singular"], "mf", "n") == ["dat.fs"]
    assert tags.kaikki_case_tags_de(["feminine", "dative", "singular"], "m", "n") == []


def test_head_line_forms_without_a_case_or_number():
    assert tags.kaikki_case_tags_de(["plural"], "m", "n") == ["nom.pl", "acc.pl", "gen.pl"]
    assert tags.kaikki_case_tags_de(["genitive"], "m", "n") == ["gen.ms"]
    assert tags.kaikki_case_tags_de(["plural"], "?", "n") == ["nom.pl", "acc.pl", "gen.pl"], "plural of Baum"
    noun = {"word": "Baum", "pos": "noun", "lang_code": "de", "senses": [{"glosses": ["tree"]}],
            "head_templates": [{"name": "de-noun", "args": {"1": "m,es,^e"}}],
            "forms": [{"form": "Baumes", "tags": ["genitive"]}, {"form": "Bäume", "tags": ["plural"]}]}
    forms = kaikki.parse_de(noun)[0].forms
    assert ("Bäume", "nom.pl") in forms and ("Baumes", "gen.ms") in forms


def test_a_row_naming_two_declensions_gives_both():
    assert tags.kaikki_case_tags_de(["strong", "mixed", "nominative", "neuter", "singular"], None, "adj") == \
        ["str.nom.ns", "mix.nom.ns"]
