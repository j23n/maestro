import json
import os
import sqlite3

import pytest

from maestro_content import build_db, grammar, kaikki, packs
from maestro_content.normalize import utf16_slice
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample.jsonl")


@pytest.fixture()
def db(tmp_path):
    conn = build_db.create(str(tmp_path / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE))
    stats = build_db.build(conn, entries, form_of, Registry())
    assert stats.lemmas > 10 and stats.forms > 50
    return conn


def test_lookup_tables(db):
    rows = db.execute("SELECT l.headword, f.tag FROM form f JOIN lemma l ON l.id = f.lemma_id WHERE f.form = 'andavamo'").fetchall()
    assert ("andare", "ind.impf.1p") in rows
    ids = [r[0] for r in db.execute("SELECT id FROM lemma WHERE headword = 'pesca' ORDER BY id")]
    assert ids == ["it:pesca:n", "it:pesca:n:2"]
    assert db.execute("SELECT auxiliary FROM lemma WHERE id = 'it:correre:v'").fetchone()[0] == "both"
    hit = db.execute("SELECT lemma_id FROM lemma_fts WHERE lemma_fts MATCH 'glosses:grandfather'").fetchone()
    assert hit[0] == "it:nonno:n"
    folded = db.execute("SELECT form FROM form WHERE form_fold = 'ando'").fetchall()
    assert ("andò",) in folded
    canti = db.execute("SELECT tag FROM form WHERE form = 'canti' AND lemma_id = 'it:canto:n'").fetchall()
    assert canti == [("mp",)]


def test_grammar_topics_parse():
    topics = grammar.load_all(os.path.join(ROOT, "content", "grammar"))
    ids = {t.id for t in topics}
    assert {"future-in-the-past", "passato-prossimo", "preposition-contractions"} <= ids
    assert all(t.summary and t.body for t in topics)


SOURCE = """# Test
level: B1
collection: test-pack
order: 1

Quando eravamo ragazzi, andavamo ogni estate dai nonni. || When we were kids, we went to our grandparents' every summer.
Noi siamo andati a Bologna in treno. || We went to Bologna by train.
Mio padre decise che saremmo andati a Bologna. || My father decided that we would go to Bologna.
@unit saremmo andati | grammar=future-in-the-past | gloss=we would go | note=Future in the past.

> Nonno: «Ho mangiato.» || "I have eaten."

?? Dove andavano? || Where did they go? @s1
- Al mare || To the seaside
* Dai nonni || To their grandparents'
?? Il nonno ha mangiato? || Has grandpa eaten? @s4 = yes
"""


def test_pack_build_links_and_validates(db, tmp_path):
    src_dir = tmp_path / "texts"
    src_dir.mkdir()
    (src_dir / "test-01.md").write_text(SOURCE, encoding="utf-8")
    warnings, errors = packs.build_all(db, str(src_dir), str(tmp_path / "packs"), "2026.10")
    assert errors == []
    text = json.loads((tmp_path / "packs" / "test-pack" / "texts" / "test-01.json").read_text(encoding="utf-8"))
    b0 = text["blocks"][0]
    s1, s2, s3 = b0["sentences"]
    assert utf16_slice(b0["text"], *s2["r"]) == s2["text"]
    toks = {t["t"]: t for t in s1["tokens"]}
    assert toks["andavamo"]["form"] == "ind.impf.1p" and toks["andavamo"]["lemmaID"] == "it:andare:v"
    assert toks["eravamo"]["pos"] == "AUX"
    assert [p["t"] for p in toks["dai"]["parts"]] == ["da", "i"] and "pos" not in toks["dai"]
    assert toks["nonni"]["gn"] == "mp"
    unit = s2["units"][0]
    assert unit["form"] == "ind.pp.1p" and unit["agree"] == "mp" and unit["lemmaID"] == "it:andare:v"
    assert unit["grammar"] == ["passato-prossimo"]
    manual = s3["units"][0]
    assert manual["form"] == "cond.pass.1p" and manual["grammar"] == ["future-in-the-past"]
    assert manual["gloss"] == "we would go"
    dialogue = text["blocks"][1]
    assert dialogue["type"] == "dialogue" and dialogue["speaker"] == "Nonno"
    assert text["questions"][0]["answer"] == 1 and text["questions"][1]["answer"] == "yes"
    manifest = json.loads((tmp_path / "packs" / "test-pack" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["texts"][0]["words"] > 20 and "it:andare:v" in manifest["texts"][0]["lemmas"]
    assert db.execute("SELECT count FROM text_lemma WHERE text_id='test-01' AND lemma_id='it:andare:v'").fetchone()[0] >= 3


def test_validation_catches_bad_ranges():
    text = {"id": "x", "blocks": [{"type": "prose", "text": "Ciao mondo.", "sentences": [
        {"id": "s1", "r": [0, 11], "text": "Ciao mondo.", "tokens": [{"t": "Ciao", "r": [1, 4]}]}]}], "questions": []}
    assert any("range" in e for e in packs.validate_text(text))


def test_utf16_ranges_count_surrogates():
    from maestro_content.normalize import utf16_len
    assert utf16_len("però") == 4 and utf16_len("🙂") == 2


def test_unit_surface_with_elision_matches_tokens():
    tokens = [{"t": t} for t, _, _, _ in packs.tokenize("Non l'avevo mai vista prima.")]
    assert packs._find_tokens(tokens, "l'avevo mai vista") == [1, 2, 3, 4]
