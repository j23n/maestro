import json
import os

import pytest

from maestro_content import build_db, curriculum, frequency, kaikki, packs
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SAMPLE = os.path.join(HERE, "fixtures", "kaikki-sample.jsonl")
GRAMMAR = os.path.join(ROOT, "content", "grammar")

FREQ = """il 1000
la 900
è 800
e 700
a 650
che 600
andiamo 500
va 400
noi 300
treno 200
nonni 150
nonno 100
estate 90
pesca 80
"""

PLAN = """level: {level}
knownRank: {known}
coreRank: 20
knownShare: 0.5
newWords: 3
words: 3-40
sentenceWords: 12
persons: 1s, 1p, 3s
blocks: prose, dialogue
registers: tu
topicShare: 1
tenseShare: 0.5
recurrence: 1
recurrenceWindow: 5
---
Test plan.
"""


@pytest.fixture()
def conn(tmp_path):
    conn = build_db.create(str(tmp_path / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(SAMPLE))
    build_db.build(conn, entries, form_of, Registry())
    freq = tmp_path / "freq.txt"
    freq.write_text(FREQ, encoding="utf-8")
    frequency.assign_ranks(conn, frequency.load(str(freq)))
    return conn


@pytest.fixture()
def dirs(tmp_path):
    texts = tmp_path / "texts"
    plans = tmp_path / "curriculum"
    plans.mkdir()
    for level, known in (("A1", 4), ("A2", 8), ("B1", 12), ("B2", 16)):
        (plans / f"{level}.md").write_text(PLAN.format(level=level, known=known), encoding="utf-8")
    return {"texts": texts, "plans": plans, "freq": tmp_path / "freq.txt"}


def write(dirs, name, body):
    path = dirs["texts"] / name.rsplit("-", 1)[0] / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return str(path)


def library(conn, dirs):
    return curriculum.load_library(conn, str(dirs["texts"]), str(dirs["plans"]), GRAMMAR, str(dirs["freq"]))


def text(lib, text_id):
    return next(t for t in lib.texts if t.id == text_id)


def checks(lib, text_id):
    return {(f.check, f.error) for f in curriculum.check_text(lib, text(lib, text_id))}


def test_frequency_ranks_lemmas_through_their_forms(conn):
    ranks = dict(conn.execute("SELECT id, freq_rank FROM lemma WHERE freq_rank IS NOT NULL"))
    assert ranks["it:il:art"] == 1
    # andiamo and va both count for andare, so it outranks treno.
    assert ranks["it:andare:v"] < ranks["it:treno:n"]
    # pesca is two homographs; they split its count and both get a rank.
    assert "it:pesca:n" in ranks and "it:pesca:n:2" in ranks


def test_repository_plans_parse():
    plans = curriculum.load_plans(os.path.join(ROOT, "content", "curriculum"))
    assert sorted(plans) == curriculum.LEVELS
    for a, b in zip(curriculum.LEVELS, curriculum.LEVELS[1:]):
        assert plans[a].core_rank <= plans[b].known_rank, "a level's core is known at the next level"


def test_every_form_topic_is_a_grammar_topic():
    ids = {f[:-3] for f in os.listdir(GRAMMAR) if f.endswith(".md")}
    assert set(curriculum.FORM_TOPIC.values()) <= ids


def test_above_level_grammar_is_flagged_unless_a_note_explains_it(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A1\ncollection: test\norder: 1\n\n"
                           "Noi andavamo dai nonni. || We used to go to our grandparents'.\n")
    write(dirs, "test-02", "# Due\nlevel: A1\ncollection: test\norder: 2\n\n"
                           "Noi andavamo dai nonni. || We used to go to our grandparents'.\n"
                           "@unit andavamo | grammar=imperfetto | note=Habit in the past.\n")
    lib = library(conn, dirs)
    assert ("above-level grammar", True) in checks(lib, "test-01")
    assert ("above-level grammar", True) not in checks(lib, "test-02")
    assert text(lib, "test-01").forms["ind.impf"] == 1
    assert text(lib, "test-01").persons["1p"] == 1


def test_compound_tense_counts_once_with_its_unit_form(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A2\ncollection: test\norder: 1\n\n"
                           "Noi siamo andati in treno. || We went by train.\n")
    t = text(library(conn, dirs), "test-01")
    assert t.forms["ind.pp"] == 1 and "ind.pres" not in t.forms


def test_brief_targets(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A2\ncollection: test\norder: 1\nstatus: draft\n"
                           "introduces: imperfetto\nrecycle: passato-prossimo\nreuse: treno:n\n"
                           "newWords: nonno:n, parolanonesiste:n\navoid: presente-indicativo\n\n"
                           "Noi andavamo dai nonni. || We used to go to our grandparents'.\n"
                           "Il nonno va a Bologna. || Grandad goes to Bologna.\n")
    findings = [f.message for f in curriculum.check_text(library(conn, dirs), text(library(conn, dirs), "test-01"))]
    assert any("introduces imperfetto but uses it 1 times" in m for m in findings)
    assert any("must recycle passato-prossimo" in m for m in findings)
    assert any("must reuse treno:n" in m for m in findings)
    assert any("'parolanonesiste:n' is not in the dictionary" in m for m in findings)
    assert any("uses presente-indicativo, which the brief avoids" in m for m in findings)


def test_words_from_earlier_texts_are_known(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A1\ncollection: test\norder: 1\n\n"
                           "Il nonno va in treno. || Grandad goes by train.\n")
    write(dirs, "test-02", "# Due\nlevel: A1\ncollection: test\norder: 2\n\n"
                           "Il nonno mangia in treno. || Grandad eats on the train.\n")
    lib = library(conn, dirs)
    new1 = set(lib.new_words(text(lib, "test-01")))
    new2 = set(lib.new_words(text(lib, "test-02")))
    assert "it:nonno:n" in new1 and "it:treno:n" in new1
    assert "it:nonno:n" not in new2 and "it:mangiare:v" in new2


def test_coverage_counts_recurrence_and_gaps(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A1\ncollection: test\norder: 1\nintroduces: presente-indicativo\n"
                           "register: tu\n\nIl nonno va in treno. || Grandad goes by train.\n")
    write(dirs, "test-02", "# Due\nlevel: A1\ncollection: test\norder: 2\n\n"
                           "Il nonno mangia. || Grandad eats.\n")
    lib = library(conn, dirs)
    cov = curriculum.coverage(lib, conn)["A1"]
    assert cov.recurrence["it:nonno:n"] == 1
    assert cov.recurrence["it:treno:n"] == 0
    assert cov.grammar["presente-indicativo"][0] == ["test-01"]
    assert cov.grammar["articles"][0] == []
    assert cov.persons["3s"] == 2
    page = curriculum.report(lib, curriculum.coverage(lib, conn), sample=True)
    assert "| articles | - |" in page and "Missing: 1s, 1p" in page and "Missing: dialogue" in page


def test_propose_brief_aims_at_gaps(conn, dirs):
    write(dirs, "test-01", "# Uno\nlevel: A1\ncollection: test\norder: 1\nintroduces: presente-indicativo\n\n"
                           "Il nonno va in treno. || Grandad goes by train.\n")
    lib = library(conn, dirs)
    path, content = curriculum.propose_brief(lib, conn, "A1", "test", "Il mercato", window="12-01..01-06")
    assert path == os.path.join("test", "test-02.md")
    meta = dict(line.split(": ", 1) for line in content.splitlines()[1:] if ": " in line)
    assert meta["introduces"] == "articles"  # the first A1 topic no text introduces yet
    assert meta["status"] == "brief" and meta["window"] == "12-01..01-06"
    assert "nonno:n" not in meta.get("newWords", "")  # already met


def test_briefs_are_skipped_and_drafts_marked_in_the_manifest(conn, dirs, tmp_path):
    write(dirs, "test-01", "# Uno\nlevel: A1\ncollection: test\norder: 1\nstatus: draft\nwindow: 12-01..01-06\n\n"
                           "Il nonno va in treno. || Grandad goes by train.\n")
    write(dirs, "test-02", "# Due\nlevel: A1\ncollection: test\norder: 2\nstatus: brief\n")
    warnings, errors = packs.build_all(conn, str(dirs["texts"]), str(tmp_path / "packs"), "1")
    assert not errors
    manifest = json.loads((tmp_path / "packs" / "test" / "manifest.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in manifest["texts"]] == ["test-01"]
    assert manifest["texts"][0]["status"] == "draft"
    assert manifest["texts"][0]["window"] == "12-01..01-06"
    lib = library(conn, dirs)
    assert [t.id for t in lib.texts] == ["test-01"]


def test_window_format():
    assert curriculum.WINDOW_RE.fullmatch("12-01..01-06")
    assert curriculum.WINDOW_RE.fullmatch("easter-60..easter-47")
    assert curriculum.WINDOW_RE.fullmatch("easter+1..easter+1")
    assert not curriculum.WINDOW_RE.fullmatch("December")


def test_draft_keeps_the_brief_and_marks_the_text_a_draft(conn, dirs):
    from maestro_content import draft

    brief = ("# Senza titolo\nlevel: A1\ncollection: test\norder: 1\nstatus: brief\ntopics: \n"
             "introduces: presente-indicativo\nnewWords: nonno:n\n")
    reply = ("Here it is.\n```markdown\n# Il nonno\nlevel: B2\ncollection: other\norder: 9\nstatus: reviewed\n"
             "topics: family\nintroduces: congiuntivo-imperfetto\n\n"
             "Il nonno va in treno. || Grandad goes by train.\n```\n")
    merged = draft.merge(brief, draft.markdown_block(reply))
    title, meta, body = draft.front_matter(merged)
    meta = dict(meta)
    assert title == "Il nonno"
    assert meta["level"] == "A1" and meta["collection"] == "test" and meta["order"] == "1"
    assert meta["status"] == "draft" and meta["introduces"] == "presente-indicativo"
    assert meta["topics"] == "family"
    assert body == "Il nonno va in treno. || Grandad goes by train."

    path = write(dirs, "test-01", brief)
    text = draft.describe_brief(library(conn, dirs), path)
    assert "Level A1" in text and "presente-indicativo" in text and "nonno:n" in text
    assert "passato-remoto" not in text  # later grammar isn't offered
