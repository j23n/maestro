"""The content pack builder (M1.9, M1.10; docs/04 § Pack build, § Requirements; docs/05 § Introductions; docs/06).

The pack is built from the frozen seed course (`fixtures/seed-course/`, conftest) and its committed annotation lock
files (no Morph-it! needed), so these tests run everywhere and don't change as the course grows; the mini pack is
built from the same seed course by `content build --mini`. Only determinism is tested on the live course. The golden
lesson's requirement rows are compared with a hand-checked expectation file.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from conftest import copy_seed
from itcontent import approval
from itcontent.cli import app
from itcontent.course import load_course
from itcontent.pack import build as build_mod
from itcontent.pack import db
from itcontent.pack.build import AudioOptions, BuildError, build_pack, select_scope, update_ids_lock
from itcontent.pack.common import Report
from itcontent.pack.locks import LockFile, LockString
from itcontent.pack.payloads import ExerciseInput, exercise_payload, spelling_letters, spelling_of

EXPECTED = Path(__file__).parent / "fixtures" / "expected-requirements-u02-l1.json"
DDL_TABLES = 27


def connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


@pytest.fixture(scope="module")
def dev(seed_root, tmp_path_factory):
    """The seed course's dev pack with no renders at all (hermetic: a developer's own mock or Azure renders don't
    count here)."""
    out = tmp_path_factory.mktemp("dev") / "content.sqlite"
    result = build_pack(seed_root, mode="dev", out=out, echo=lambda _: None, audio=AudioOptions([], None))
    con = connect(out)
    yield result, con
    con.close()


def mini_rows_only(root: Path) -> AudioOptions:
    """The mini pack's committed renders, without encoding: the rows don't depend on ffmpeg."""
    options = AudioOptions.default(root, "mini")
    options.encode = False
    return options


@pytest.fixture(scope="module")
def mini(root, tmp_path_factory):
    """The mini pack as `make mini-pack` builds it (from the seed course, with the committed renders)."""
    out = tmp_path_factory.mktemp("mini") / "mini.sqlite"
    result = build_pack(root, mode="mini", out=out, echo=lambda _: None, audio=mini_rows_only(root))
    con = connect(out)
    yield result, con
    con.close()


def pairs(con, sql: str) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for owner, item, skill in con.execute(sql):
        out.setdefault(owner, set()).add(f"{item}/{skill}")
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------- M1.9: the pack builds


def test_every_table_of_the_ddl_exists_and_the_golden_content_is_there(dev):
    result, con = dev
    assert len(result.counts) == DDL_TABLES
    for table in ("units", "items", "item_skills", "steps", "texts", "text_lines", "tokens", "exercises", "forms"):
        assert result.counts[table] > 0, table
    assert result.counts["lessons"] == 1
    assert result.counts["grammar_notes"] == 1
    kinds = dict(con.execute("SELECT key, value FROM meta"))
    for key in ("schema_version", "pack_version", "content_hash", "course_id", "locale", "release"):
        assert key in kinds, key
    assert kinds["schema_version"] == "2" and kinds["release"] == "0" and kinds["course_id"] == "italiano-a1"
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_pack_hash_is_stable_and_ignores_git_sha_and_built_with(root, tmp_path, monkeypatch):
    """On the live course: its dev pack builds, deterministically."""
    monkeypatch.setattr(build_mod, "git_sha", lambda _root: "1111111")
    a = build_pack(root, mode="dev", out=tmp_path / "a.sqlite", echo=lambda _: None)
    monkeypatch.setattr(build_mod, "git_sha", lambda _root: "2222222")
    monkeypatch.setattr(build_mod, "__version__", "9.9.9")
    b = build_pack(root, mode="dev", out=tmp_path / "b.sqlite", echo=lambda _: None)
    assert a.content_hash == b.content_hash
    assert db.pack_hash(a.path) == db.pack_hash(b.path) == a.content_hash
    with connect(b.path) as con:
        meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["git_sha"] == "2222222" and meta["built_with"] == "itcontent 9.9.9"
    assert meta["content_hash"] == a.content_hash


def test_unit_steps_run_in_the_order_docs06_gives(dev):
    _, con = dev
    steps = [r[0] for r in con.execute("SELECT id FROM steps WHERE unit_id = 'u02' ORDER BY ord")]
    assert steps == [
        "u02.step-opener",
        "u02.l1.step-preview",
        "u02.l1.step-story",
        "u02.l1.step-note",
        "u02.l1.step-practice",
        "u02.l1.step-sounds",
        "u02.l1.step-use",
        "u02.step-conversation-1",
        "u02.step-talk",
        "u02.step-relay",
        "u02.step-check",
        "u02.step-fluency",
    ]
    ords = [r[0] for r in con.execute("SELECT ord FROM steps WHERE unit_id = 'u02' ORDER BY ord")]
    assert ords == list(range(1, len(steps) + 1))
    payload = json.loads(con.execute("SELECT payload FROM steps WHERE id = 'u02.step-fluency'").fetchone()[0])
    assert payload == {"kind": "fluency", "textIds": ["u02.l1.story"], "rate": 1.15}
    drafts = {r[0] for r in con.execute("SELECT draft FROM steps WHERE unit_id = 'u02'")}
    assert drafts == {1}  # dev packs mark unapproved content


def test_payloads_agree_with_their_rows(dev):
    """What Storage's PackReader checks on open and in verify() (docs/02 § Storage)."""
    _, con = dev
    targets = pairs(con, "SELECT exercise_id, item_id, skill FROM exercise_targets")
    exercise_ids = {r[0] for r in con.execute("SELECT id FROM exercises")}
    text_ids = {r[0] for r in con.execute("SELECT id FROM texts")}
    for eid, fmt, unit, step, role, payload, score in con.execute(
        "SELECT id, format, unit_id, step_id, role, payload, score FROM exercises"
    ):
        p = json.loads(payload)
        assert (p["id"], p["format"], p["unitId"], p["stepId"], p["role"], p["score"]) == (
            eid,
            fmt,
            unit,
            step,
            role,
            score,
        )
        assert sorted(f"{t['itemId']}/{t['skill']}" for t in p["targets"]) == targets.get(eid, [])
        for ref in (p["source"] or {}).get("textId"), p.get("audioTextId"), p.get("sourceTextId"):
            assert ref is None or ref in text_ids, (eid, ref)
    for sid, kind, payload in con.execute("SELECT id, kind, payload FROM steps"):
        p = json.loads(payload)
        assert p["kind"] == kind
        named = [*p.get("questionIds", []), *p.get("exerciseIds", []), *p.get("block", []), *p.get("mix", [])]
        named += [e for b in p.get("batches", []) for e in b["exerciseIds"]]
        named += [p["exerciseId"]] if "exerciseId" in p else []
        named += [e for s in p.get("sections", []) for e in s["exerciseIds"]]
        assert set(named) <= exercise_ids, sid
        for tid in [p.get("textId"), *p.get("textIds", [])]:
            assert tid is None or tid in text_ids, sid
    for nid, body in con.execute("SELECT id, body FROM grammar_notes"):
        items = [r[0] for r in con.execute("SELECT item_id FROM note_items WHERE note_id = ? ORDER BY ord", (nid,))]
        assert json.loads(body)["grammar"] == items == ["g:indefinite-article", "g:noun-gender"]


def test_every_line_rebuilds_from_its_tokens(dev):
    _, con = dev
    lines = con.execute("SELECT text_id, ord, it FROM text_lines").fetchall()
    assert lines
    for tid, n, it in lines:
        toks = con.execute(
            "SELECT surface, trailing FROM tokens WHERE text_id = ? AND line_ord = ? ORDER BY ord", (tid, n)
        ).fetchall()
        rebuilt = "".join(s + t for s, t in toks)
        assert it.endswith(rebuilt) and rebuilt, (tid, n)
    orphans = con.execute(
        "SELECT COUNT(*) FROM tokens k LEFT JOIN text_lines l ON l.text_id = k.text_id AND l.ord = k.line_ord "
        "WHERE l.ord IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_tokens_carry_items_glosses_and_flags(dev):
    _, con = dev

    def line(n: int) -> list[tuple]:
        return con.execute(
            "SELECT surface, kind, item_id, gloss_en, flags FROM tokens WHERE text_id = 'u02.l1.story' "
            "AND line_ord = ? ORDER BY ord",
            (n,),
        ).fetchall()

    # "Un cappuccino. E da mangiare?": the target article (flag 4), a glossed new chunk (flag 1)
    assert line(4) == [
        ("Un", "word", "g:indefinite-article", None, 4),
        ("cappuccino", "word", "w:cappuccino", None, 0),
        (".", "punct", None, None, 0),
        ("E", "word", "w:e", None, 0),
        ("da", "word", "c:da-mangiare", "to eat", 1),
        ("mangiare", "word", "c:da-mangiare", "to eat", 1),
        ("?", "punct", None, None, 0),
    ]
    assert line(1)[0][:3] == ("Marco", "name", None)
    assert ("bar", "word", None, "café; bar", 0) in line(1)  # allowlisted, glossed from the allowlist
    speakers = dict(con.execute("SELECT ord, speaker_id FROM text_lines WHERE text_id = 'u02.l1.story'"))
    assert speakers[1] == "ch:narrator" and speakers[2] == "ch:giulia"


def test_items_display_forms_and_scheduled_skills(dev):
    _, con = dev
    row = con.execute("SELECT display_def, display_indef, kind FROM items WHERE id = 'w:amico'").fetchone()
    assert row == ("l'amico / l'amica", "un amico / un'amica", "word")
    assert con.execute("SELECT it, kind, lesson_id FROM items WHERE id = 'g:indefinite-article'").fetchone() == (
        "un, uno, una, un'",
        "grammar",
        "u02.l1",
    )
    scheduled = {r[0]: r[1] for r in con.execute("SELECT item_id, skill FROM item_skills WHERE scheduled = 1")}
    assert scheduled["w:cornetto"] == "recall"  # P word
    assert scheduled["c:cosa-prende"] == "read"  # R chunk
    assert scheduled["g:indefinite-article"] == "recall"  # P grammar
    assert scheduled["g:lei-questions"] == "read"  # R grammar
    assert scheduled["g:conditional-courtesy"] == "read"  # chunk grammar
    assert scheduled["s:double-consonants"] == "listen"
    once = con.execute("SELECT item_id FROM item_skills GROUP BY item_id HAVING SUM(scheduled) > 1").fetchall()
    assert once == []
    sounds = json.loads(con.execute("SELECT pairs FROM sounds WHERE item_id = 's:double-consonants'").fetchone()[0])
    assert sounds[0] == [{"it": "pena", "audioId": None}, {"it": "penna", "audioId": None}]


def test_letter_items_carry_their_letter(course_copy, tmp_path):
    """`items.letter` (docs/03 § Items): the spoken-spelling table the app reads (docs/05 § Speech transcripts). The
    seed course has no letter items, so two are added (items aren't annotated, so the lock files stay fresh)."""
    items = course_copy / "content/items/u00.yaml"
    items.write_text(
        items.read_text(encoding="utf-8")
        + "  - {id: 'w:bi', it: bi, pos: noun, gender: f, plural: invariable, gloss: the letter B, letter: B, "
        "status: P, lesson: u00.l2}\n"
        "  - {id: 'c:doppia-vu', kind: chunk, it: doppia vu, gloss: the letter W, match: [doppia vu], letter: W, "
        "status: P, lesson: u00.l2}\n",
        encoding="utf-8",
    )
    out = tmp_path / "letters.sqlite"
    build_pack(course_copy, mode="dev", out=out, echo=lambda _: None, audio=AudioOptions([], None))
    with connect(out) as con:
        letters = con.execute("SELECT letter, it, id FROM items WHERE letter IS NOT NULL ORDER BY letter").fetchall()
        others = con.execute("SELECT COUNT(*) FROM items WHERE letter IS NULL").fetchone()[0]
    assert letters == [("B", "bi", "w:bi"), ("W", "doppia vu", "c:doppia-vu")]
    assert others > 0  # every other item, grammar points included


def test_forms_hold_inflections_of_the_same_item(dev):
    _, con = dev
    forms = {(f, i) for f, i in con.execute("SELECT form, item_id FROM forms")}
    assert {("un", "g:indefinite-article"), ("una", "g:indefinite-article"), ("un'", "g:indefinite-article")} <= forms
    assert {("amico", "w:amico"), ("amica", "w:amico"), ("cornetti", "w:cornetto")} <= forms
    assert all(f == f.lower() for f, _ in forms)


def test_review_files_name_each_prefix_with_its_approval_hash(seed_root, dev):
    _, con = dev
    files = json.loads(con.execute("SELECT value FROM meta WHERE key = 'review_files'").fetchone()[0])
    lesson = "content/units/02-al-bar/lesson-1.yaml"
    assert files["u02.l1"] == {"file": lesson, "hash": approval.file_hash(seed_root / lesson)}
    assert files["u02.task"]["file"] == "content/units/02-al-bar/task.yaml"
    assert files["u02.check"]["file"] == "content/units/02-al-bar/check.yaml"
    assert files["u02"]["file"] == "content/units/02-al-bar/unit.yaml"
    assert files["w:cornetto"]["file"] == "content/items/u02.yaml"
    assert files["g:indefinite-article"]["file"] == "content/grammar/points.yaml"


def test_missing_audio_is_a_warning_in_dev_packs(dev):
    result, con = dev
    missing = next(w for w in result.report.warnings if w.startswith("missing audio:"))
    assert re.match(r"missing audio: (\d+) of \1 need\(s\) \(\d+ exercise, \d+ item, \d+ sound, 2 text;", missing)
    assert not any(w.startswith("audio not-voiceable:") for w in result.report.warnings)
    assert con.execute("SELECT COUNT(*) FROM audio").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM texts WHERE audio_id IS NOT NULL").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM tokens WHERE start_ms IS NOT NULL").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM items WHERE audio_id IS NOT NULL").fetchone()[0] == 0


# ---------------------------------------------------------------- M1.10: requirements, introductions, previews


def test_golden_requirements_match_the_hand_checked_expectations(dev):
    """Every requirement and introduction row of Unit 2 Lesson 1 equals the hand-checked expectation file."""
    _, con = dev
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    got_text = pairs(con, "SELECT text_id, item_id, skill FROM text_requires WHERE text_id LIKE 'u02.l1.%'")
    assert got_text == {k: sorted(v) for k, v in expected["text_requires"].items()}
    got_ex = pairs(con, "SELECT exercise_id, item_id, skill FROM exercise_requires WHERE exercise_id LIKE 'u02.l1.%'")
    lesson_exercises = {r[0] for r in con.execute("SELECT id FROM exercises WHERE id LIKE 'u02.l1.%'")}
    assert lesson_exercises == set(expected["exercise_requires"])
    for eid, want in expected["exercise_requires"].items():
        assert got_ex.get(eid, []) == sorted(want), eid
    got_intro = pairs(con, "SELECT step_id, item_id, skill FROM step_introduces WHERE step_id LIKE 'u02.l1.%'")
    for sid, want in expected["step_introduces"].items():
        assert got_intro.get(sid, []) == sorted(want), sid
    assert set(got_intro) <= set(expected["step_introduces"])


def test_generated_preview_exercises(dev):
    _, con = dev
    step = json.loads(con.execute("SELECT payload FROM steps WHERE id = 'u02.l1.step-preview'").fetchone()[0])
    assert step["batches"][1] == {
        "itemIds": ["w:ecco", "w:oggi", "w:buono", "w:amico", "c:cosa-prende"],
        "exerciseIds": [
            "u02.l1.step-preview.b2.match",
            "u02.l1.step-preview.b2.w-ecco",
            "u02.l1.step-preview.b2.w-oggi",
            "u02.l1.step-preview.b2.w-buono",
            "u02.l1.step-preview.b2.w-amico",
            "u02.l1.step-preview.b2.c-cosa-prende",
        ],
    }

    def payload(eid: str) -> dict:
        return json.loads(con.execute("SELECT payload FROM exercises WHERE id = ?", (eid,)).fetchone()[0])

    match = payload("u02.l1.step-preview.b1.match")
    assert [p["right"] for p in match["pairs"]][:2] == ["coffee", "cappuccino"]  # glosses up to the first ;
    assert match["pairs"][0]["left"]["text"] == "il caffè"
    assert [t["itemId"] for t in match["pairs"][0]["left"]["tokens"]] == ["w:caffe", "w:caffe"]
    recall = payload("u02.l1.step-preview.b1.w-cornetto")
    assert recall["format"] == "recall" and recall["promptEn"] == "croissant"
    assert recall["answer"] == {
        "source": "{il|un} [cornetto]",
        "expansions": ["il cornetto", "un cornetto"],
        "spelling": None,
    }
    assert recall["near"][0]["outcome"] == "correctWithNote"
    assert payload("u02.l1.step-preview.b2.w-amico")["answer"]["source"] == "{l'amico|l'amica|un amico|un'amica}"
    assert payload("u02.l1.step-preview.b1.c-quant-e")["answer"]["source"] == "quant'è"
    choice = payload("u02.l1.step-preview.b2.c-cosa-prende")  # an R item: Italian → English
    assert choice["format"] == "choice" and choice["answer"] == 0
    assert choice["options"][0]["text"] == "what will you have? (formal)"
    assert len(choice["options"]) == 3 and choice["promptIt"]["text"] == "cosa prende?"


def test_cloze_payload_splits_around_the_gap(dev):
    _, con = dev
    p = json.loads(con.execute("SELECT payload FROM exercises WHERE id = 'u02.l1.ex03'").fetchone()[0])
    assert p["before"]["text"] == "Giulia è "
    assert p["gap"] == {"source": "un'", "expansions": ["un'"], "spelling": None}
    assert p["after"]["text"] == "amica di Sara." and p["after"]["lead"] == ""
    assert p["source"] is None
    p = json.loads(con.execute("SELECT payload FROM exercises WHERE id = 'u02.l1.ex01'").fetchone()[0])
    assert p["source"] == {"textId": "u02.l1.story", "line": 3}
    assert (p["before"]["text"], p["after"]["text"], p["after"]["lead"]) == ("Vorrei ", " cappuccino, per favore.", " ")


def test_note_examples_highlight_only_the_target_forms(dev):
    _, con = dev
    body = json.loads(con.execute("SELECT body FROM grammar_notes WHERE id = 'u02.l1.note'").fetchone()[0])
    examples = next(b["examples"] for b in body["blocks"] if "examples" in b)
    assert [(e["ref"], e["highlight"]) for e in examples] == [
        ("u02.l1.story#3", [3]),
        ("u02.l1.story#16", [6]),
        ("u02.l1.story#11", [5]),
    ]
    assert examples[0]["text"]["tokens"][3]["surface"] == "un"
    assert body["intro"] == {"mascot": "think", "textEn": body["intro"]["textEn"]}


def test_layouts_keep_prices_and_ignored_strings_plain(dev):
    _, con = dev
    layout = json.loads(con.execute("SELECT layout FROM texts WHERE id = 'u02.task.menu'").fetchone()[0])
    section = layout["sections"][0]
    assert section["title"] == "Caffetteria"  # in `ignore`
    row = section["rows"][0]
    assert row["price"] == "1,20" and row["note"] is None
    assert row["name"]["tokens"][0]["itemId"] == "w:caffe"
    assert layout["title"]["text"] == "Bar Aurora"


def test_assessments_and_check_payloads(dev):
    _, con = dev
    rows = dict(con.execute("SELECT id, payload FROM assessments"))
    placement = json.loads(rows["placement"])
    assert placement["advanceThreshold"] == 4 and placement["blocks"][0] == {"unitId": "u01", "exerciseIds": []}
    final = json.loads(rows["final"])
    assert final["indicativePassPerSection"] == 7 and [s["max"] for s in final["sections"]] == [12] * 5
    check = json.loads(con.execute("SELECT payload FROM steps WHERE id = 'u02.step-check'").fetchone()[0])
    assert check["checkId"] == "u02.check" and check["pass"] == {"overall": 0.7, "sectionMin": 0.5}
    assert [s["id"] for s in check["sections"]] == ["listening", "reading", "writing", "speaking"]


# ---------------------------------------------------------------- the mini pack


def test_mini_pack_holds_the_golden_sample_only(mini):
    result, con = mini
    assert {r[0] for r in con.execute("SELECT unit_id FROM steps")} == {"u02"}
    assert [r[0] for r in con.execute("SELECT id FROM units ORDER BY ord")] == ["u00", "u01", "u02"]
    assert con.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 0
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert "git_sha" not in meta and "review_files" in meta
    payloads = json.loads(result.payloads_path.read_text(encoding="utf-8"))
    assert set(payloads) == {"exercises", "steps", "notes"}
    assert set(payloads["steps"]) == {r[0] for r in con.execute("SELECT id FROM steps")}
    assert set(payloads["exercises"]) == {r[0] for r in con.execute("SELECT id FROM exercises")}


def test_mini_payloads_conform_to_the_contract(root, mini):
    result, _ = mini
    schema = json.loads((root / "schemas" / "pack-payloads.schema.json").read_text(encoding="utf-8"))
    payloads = json.loads(result.payloads_path.read_text(encoding="utf-8"))
    for key, definition in (("exercises", "exercise"), ("steps", "stepPayload"), ("notes", "noteBody")):
        v = jsonschema.Draft202012Validator({"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]})
        for pid, p in payloads[key].items():
            errors = list(v.iter_errors(p))
            assert not errors, f"{pid}: {errors[0].message}"

    def walk(node):
        if isinstance(node, dict):
            if {"text", "lead", "tokens"} <= node.keys():
                yield node
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    texts = list(walk(payloads))
    assert len(texts) > 50
    for t in texts:
        assert t["lead"] + "".join(k["surface"] + k["trailing"] for k in t["tokens"]) == t["text"]


def test_committed_mini_pack_is_fresh(root, mini):
    """fixtures/packs/mini.sqlite, mini-payloads.json and Audio/ are what `make mini-pack` builds now."""
    result, con = mini
    committed = root / "fixtures" / "packs" / "mini.sqlite"
    assert committed.is_file(), "run `make mini-pack`"
    assert db.pack_hash(committed) == result.content_hash, "fixtures/packs/mini.sqlite is stale: run `make mini-pack`"
    fresh = json.loads(result.payloads_path.read_text(encoding="utf-8"))
    on_disk = json.loads((root / "fixtures" / "packs" / "mini-payloads.json").read_text(encoding="utf-8"))
    assert fresh == on_disk, "fixtures/packs/mini-payloads.json is stale: run `make mini-pack`"
    files = {r[0] for r in con.execute("SELECT file FROM audio")}
    on_disk_audio = {p.name for p in (root / "fixtures" / "packs" / "Audio").glob("*.m4a")}
    assert files == on_disk_audio, "fixtures/packs/Audio/ is stale: run `make mini-pack`"


def test_the_mini_pack_has_two_or_three_audio_files_from_its_committed_renders(mini):
    """docs/04 § Tiny test packs: a text with timings, an item and an exercise string, from the mock renders in
    fixtures/packs/tts-cache/ (other needs stay null)."""
    result, con = mini
    files = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    assert 3 <= files <= 4  # the three needs, plus a conversation line that says what the audio text's first line says
    assert con.execute("SELECT audio_id IS NOT NULL FROM texts WHERE id = 'u02.check.01.audio'").fetchone()[0] == 1
    assert con.execute("SELECT audio_id FROM texts WHERE id = 'u02.l1.story'").fetchone()[0] is None
    timed = con.execute(
        "SELECT COUNT(*) FROM tokens WHERE text_id = 'u02.check.01.audio' AND kind = 'word' AND start_ms IS NOT NULL"
    ).fetchone()[0]
    assert timed == 10
    assert con.execute("SELECT audio_id IS NOT NULL FROM items WHERE id = 'w:cornetto'").fetchone()[0] == 1
    ex13 = json.loads(result.payloads_path.read_text(encoding="utf-8"))["exercises"]["u02.l1.ex13"]
    assert ex13["audioId"] is not None


def test_two_mini_builds_are_byte_identical(root, tmp_path):
    options = mini_rows_only(root)
    a = build_pack(root, mode="mini", out=tmp_path / "a" / "mini.sqlite", echo=lambda _: None, audio=options)
    b = build_pack(root, mode="mini", out=tmp_path / "b" / "mini.sqlite", echo=lambda _: None, audio=options)
    assert a.path.read_bytes() == b.path.read_bytes()
    assert a.payloads_path.read_bytes() == b.payloads_path.read_bytes()


# ---------------------------------------------------------------- failures and release mode


def test_a_stale_lock_file_stops_the_build(tmp_path):
    repo = copy_seed(tmp_path / "repo")
    lesson = repo / "content" / "units" / "02-al-bar" / "lesson-1.yaml"
    lesson.write_text(lesson.read_text(encoding="utf-8").replace("Mmm! Buono!", "Mmm! Buono buono!"), "utf-8")
    with pytest.raises(BuildError, match="stale"):
        build_pack(repo, mode="dev", out=tmp_path / "p.sqlite", lint=False, echo=lambda _: None)


def approve_in_copy(repo: Path, rel: str) -> None:
    """Mark a file of a throwaway copy approved, as `content approve` would (tests only; never on the repo)."""
    path = repo / rel
    digest = approval.file_hash(path)  # the hash leaves out the review entry
    approval.set_review(path, {"status": "approved", "by": "Test", "date": "2026-10-08", "hash": digest})


def test_release_needs_the_signed_off_files_and_complete_approved_units(tmp_path):
    repo = copy_seed(tmp_path / "repo")
    course = load_course(repo)
    with pytest.raises(BuildError, match=r"syllabus.*not approved"):
        select_scope(course, "release", allow_partial=True, report=Report())
    for rel in (
        "content/syllabus/a1-syllabus.yaml",
        "content/grammar/points.yaml",
        "content/story-bible.yaml",
        "content/countries.yaml",
    ):
        approve_in_copy(repo, rel)
    course = load_course(repo)
    with pytest.raises(BuildError, match="u00 can't ship: incomplete"):
        select_scope(course, "release", allow_partial=False, report=Report())
    with pytest.raises(BuildError, match="no unit is complete and approved"):
        select_scope(course, "release", allow_partial=True, report=Report())


def test_release_fails_on_missing_audio(seed_root, tmp_path, monkeypatch):
    def dev_scope_as_release(course, mode, *, allow_partial, report):
        scope = select_scope(course, "dev", allow_partial=allow_partial, report=report)
        scope.mode = "release"
        return scope

    monkeypatch.setattr(build_mod, "select_scope", dev_scope_as_release)
    with pytest.raises(BuildError, match=r"release: .* audio need"):
        build_pack(seed_root, mode="release", out=tmp_path / "r.sqlite", lint=False, echo=lambda _: None)
    assert not (tmp_path / "r.sqlite").exists()


def test_release_records_released_ids_in_ids_lock(tmp_path):
    (tmp_path / "content").mkdir()
    lock = tmp_path / "content" / "ids.lock"
    lock.write_text("# released IDs\nw:ciao 0.1.0\n", encoding="utf-8")
    assert update_ids_lock(tmp_path, ["w:cornetto", "w:ciao", "u02.l1"], "0.2.0") == 2
    assert lock.read_text(encoding="utf-8").splitlines() == [
        "# released IDs",
        "u02.l1 0.2.0",
        "w:ciao 0.1.0",
        "w:cornetto 0.2.0",
    ]


# ---------------------------------------------------------------- the CLI


def test_cli_build_and_pack_hash(tmp_path):
    runner = CliRunner()
    out = tmp_path / "mini.sqlite"
    res = runner.invoke(app, ["build", "--mini", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "pack (mini)" in res.output and "rows: " in res.output
    printed = res.output.split("pack hash ")[1].split()[0]
    res = runner.invoke(app, ["pack-hash", "--pack", str(out)])
    assert res.exit_code == 0 and res.output.strip() == printed
    assert runner.invoke(app, ["build", "--mini", "--release"]).exit_code == 2
    assert runner.invoke(app, ["pack-hash", "--pack", str(tmp_path / "none.sqlite")]).exit_code == 1


# ---------------------------------------------------------------- CL40: what a pattern spells


def lock_entry(path: str, tokens: list[tuple[str, str | None, str | None]], flags: dict[int, list[str]] | None = None):
    """A lock string whose word tokens are (surface, item, chunk)."""
    return LockString.from_json(
        "content/x.yaml",
        {
            "path": path,
            "role": "answer",
            "text": " ".join(t[0] for t in tokens),
            "tokens": [
                {
                    "surface": s,
                    "trailing": " " if n < len(tokens) - 1 else "",
                    "kind": "word",
                    "item": i,
                    "chunk": c,
                    "flags": (flags or {}).get(n, []),
                }
                for n, (s, i, c) in enumerate(tokens)
            ],
        },
    )


LETTERS = {"w:elle": "L", "w:u": "U", "w:ci~letter": "C", "w:a~letter": "A", "c:i-lunga": "J", "c:doppia": None}


def test_a_pattern_spells_what_its_annotation_resolves_to_letters():
    luca = [
        lock_entry(
            "a", [("elle", "w:elle", None), ("u", "w:u", None), ("ci", "w:ci~letter", None), ("a", "w:a~letter", None)]
        )
    ]
    assert spelling_of(luca, LETTERS, "x") == [
        {"name": "a", "letter": "A"},
        {"name": "ci", "letter": "C"},
        {"name": "elle", "letter": "L"},
        {"name": "u", "letter": "U"},
    ]
    # A chunk's tokens are one name; doppia doubles; an article (lexical_article) and other words aren't letters.
    mixed = [
        lock_entry(
            "a", [("Marco", "w:marco", None), ("i", "c:i-lunga", "c:i-lunga"), ("lunga", "c:i-lunga", "c:i-lunga")]
        ),
        lock_entry(
            "a",
            [("la", "w:a~letter", None), ("a", "w:a~letter", None), ("doppia", "c:doppia", "c:doppia")],
            {0: ["lexical_article"]},
        ),
    ]
    assert spelling_of(mixed, LETTERS, "x") == [
        {"name": "a", "letter": "A"},
        {"name": "doppia", "letter": None},
        {"name": "i lunga", "letter": "J"},
    ]
    # No letter: not spelled. The same name as a letter and as a word: an error (the app reads letters by name).
    assert spelling_of([lock_entry("a", [("vado", "w:andare", None), ("a", "w:a", None)])], LETTERS, "x") is None
    with pytest.raises(BuildError, match="'a' is a letter in one place and a word in another"):
        spelling_of([*luca, lock_entry("a", [("a", "w:a", None), ("Roma", None, None)])], LETTERS, "x")


def test_spelled_payloads_carry_their_spelling():
    lock = LockFile(
        "content/x.yaml",
        [
            lock_entry("ex.answer", [("elle", "w:elle", None), ("u", "w:u", None)]),
            lock_entry("ex.say", [("Elle", "w:elle", None), ("u", "w:u", None)]),
        ],
    )
    x = ExerciseInput(
        {"id": "u00.l3.ex01", "format": "recall", "answer": "elle, u", "prompt_en": "Spell Lu", "say": "Elle, u."},
        ("ex",),
        lock,
        "u00",
        "u00.l3.step-practice",
        "practice",
        "learn",
        frozenset(),
        None,
        None,
        lambda _: None,
        LETTERS,
    )
    spelled = [{"name": "elle", "letter": "L"}, {"name": "u", "letter": "U"}]
    assert exercise_payload(x)["answer"] == {"source": "elle, u", "expansions": ["elle u"], "spelling": spelled}
    assert x.pattern("answer")["spelling"] == spelled
    # Without letter items in the pack nothing spells.
    plain = ExerciseInput(**{**x.__dict__, "letters": {}})
    assert exercise_payload(plain)["answer"]["spelling"] is None
    assert spelling_letters({"w:elle": {"letter": "L"}, "w:caffe": {}, "c:doppia": {}}) == {
        "w:elle": "L",
        "c:doppia": None,
    }


# CL40: every payload path that writes a pattern's `spelling` (payloads.repeat, ExerciseInput.pattern for conversation
# `accept`, talk and writing `points`, writing `fields`). Rossi spelled with doppia, as Unit 0 does.
ROSSI = [
    ("erre", "w:erre", None),
    ("o", "w:o~letter", None),
    ("doppia", "c:doppia", "c:doppia"),
    ("esse", "w:esse", None),
    ("i", "w:i~letter", None),
]
ROSSI_LETTERS = {**LETTERS, "w:erre": "R", "w:o~letter": "O", "w:esse": "S", "w:i~letter": "I"}
ROSSI_SPELLING = [
    {"name": "doppia", "letter": None},
    {"name": "erre", "letter": "R"},
    {"name": "esse", "letter": "S"},
    {"name": "i", "letter": "I"},
    {"name": "o", "letter": "O"},
]
SURNAME = [("Rossi", None, None)]


def spelled_input(data: dict, entries: dict[str, list[tuple[str, str | None, str | None]]]) -> ExerciseInput:
    lock = LockFile("content/x.yaml", [lock_entry(path, tokens) for path, tokens in entries.items()])
    return ExerciseInput(
        data, ("ex",), lock, "u00", None, None, "learn", frozenset(), None, None, lambda _: None, ROSSI_LETTERS
    )


def patterns_conform(root, *found: dict) -> None:
    schema = json.loads((root / "schemas" / "pack-payloads.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator({"$ref": "#/$defs/pattern", "$defs": schema["$defs"]})
    for p in found:
        assert not list(v.iter_errors(p)), p


def test_a_spelled_repeat_carries_its_spelling(root):
    """`repeat`: the accept pattern is the `say` text; it spells when the say's tokens resolve to letters."""
    say = " ".join(t[0] for t in ROSSI)
    x = spelled_input({"id": "u00.l3.ex40", "format": "repeat", "say": say}, {"ex.say": ROSSI})
    accept = exercise_payload(x)["accept"]
    assert accept == {"source": say, "expansions": [say], "spelling": ROSSI_SPELLING}
    words = spelled_input({"id": "u00.l3.ex41", "format": "repeat", "say": "Rossi"}, {"ex.say": SURNAME})
    assert exercise_payload(words)["accept"]["spelling"] is None
    unlettered = ExerciseInput(**{**x.__dict__, "letters": {}})
    assert exercise_payload(unlettered)["accept"]["spelling"] is None
    patterns_conform(root, accept)


def test_a_conversation_accept_carries_its_spelling(root):
    """Conversation `accept`: each pattern of an intent has its own spelling, null for one in words."""
    data = {
        "id": "u00.l3.ex31",
        "format": "conversation",
        "with": "ch:extra",
        "start": "n1",
        "nodes": {
            "n1": {
                "say": "Come si scrive",
                "en": "How do you spell it?",
                "expect": [{"intent": "spell", "accept": ["erre, o, doppia esse, i", "Rossi"], "next": "end"}],
            },
            "end": {"say": "Grazie", "en": "Thanks!", "final": True},
        },
    }
    x = spelled_input(
        data,
        {
            "ex.nodes.n1.say": [("Come", None, None), ("si", None, None), ("scrive", None, None)],
            "ex.nodes.n1.expect[0].accept[0]": ROSSI,
            "ex.nodes.n1.expect[0].accept[1]": SURNAME,
            "ex.nodes.end.say": [("Grazie", "w:grazie", None)],
        },
    )
    accept = exercise_payload(x)["nodes"][0]["expect"][0]["accept"]
    assert [a["spelling"] for a in accept] == [ROSSI_SPELLING, None]
    patterns_conform(root, *accept)


def test_talk_and_writing_points_carry_their_spelling(root):
    """Talk and writing `points`: a point's spelled pattern carries its spelling, the others null."""
    points = [
        {"id": "spell", "en": "Spell your surname", "accept": ["erre, o, doppia esse, i"]},
        {"id": "name", "en": "Say your surname", "accept": ["Rossi"]},
    ]
    entries = {"ex.points[0].accept[0]": ROSSI, "ex.points[1].accept[0]": SURNAME, "ex.model": [*SURNAME, *ROSSI]}
    talk = spelled_input(
        {
            "id": "u00.task.talk",
            "format": "talk",
            "prompt_en": "Say and spell your surname",
            "points": points,
            "pass": 2,
            "model": "Rossi erre o doppia esse i",
            "duration_s": {"min": 5, "max": 30},
        },
        entries,
    )
    writing = spelled_input(
        {
            "id": "u00.task.write",
            "format": "writing",
            "kind": "message",
            "prompt_en": "Write and spell your surname",
            "points": points,
            "pass": 2,
            "model": "Rossi erre o doppia esse i",
        },
        entries,
    )
    for x in (talk, writing):
        found = exercise_payload(x)["points"]
        assert [[a["spelling"] for a in p["accept"]] for p in found] == [[ROSSI_SPELLING], [None]]
        patterns_conform(root, *(a for p in found for a in p["accept"]))


def test_writing_fields_carry_their_spelling(root):
    """Writing `fields`: a field's accepted patterns each carry their spelling; a field without `accept` has none."""
    data = {
        "id": "u00.task.form",
        "format": "writing",
        "kind": "form",
        "prompt_en": "Spell your surname on the form",
        "fields": [
            {
                "label_it": "Cognome",
                "label_en": "Surname",
                "type": "text",
                "accept": ["erre, o, doppia esse, i", "Rossi"],
            },
            {"label_it": "Nome", "label_en": "First name", "type": "text"},
        ],
    }
    x = spelled_input(
        data,
        {
            "ex.fields[0].label_it": [("Cognome", None, None)],
            "ex.fields[0].accept[0]": ROSSI,
            "ex.fields[0].accept[1]": SURNAME,
            "ex.fields[1].label_it": [("Nome", None, None)],
        },
    )
    fields = exercise_payload(x)["fields"]
    assert [a["spelling"] for a in fields[0]["accept"]] == [ROSSI_SPELLING, None]
    assert fields[1]["accept"] is None
    patterns_conform(root, *fields[0]["accept"])
