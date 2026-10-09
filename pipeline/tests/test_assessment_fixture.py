"""`fixtures/packs/assessment.sqlite`: the mini pack plus placement and final-check rows for the App's tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from itcontent.pack import assessment_fixture, db


def test_committed_assessment_pack_is_fresh(root: Path, tmp_path: Path) -> None:
    mini, examples, committed = assessment_fixture.default_paths()
    assert committed.is_file(), "run `make mini-pack`"
    fresh = assessment_fixture.build(mini, examples, tmp_path / "assessment.sqlite")
    assert db.pack_hash(committed) == fresh, "fixtures/packs/assessment.sqlite is stale: run `make mini-pack`"


def test_the_fixture_has_runnable_placement_and_final_check(root: Path) -> None:
    _, _, committed = assessment_fixture.default_paths()
    con = sqlite3.connect(f"file:{committed}?mode=ro", uri=True)
    try:
        rows = dict(con.execute("SELECT id, payload FROM assessments").fetchall())
        placement = json.loads(rows["placement"])
        final = json.loads(rows["final"])
        exercises = {r[0]: r[1:] for r in con.execute("SELECT id, format, unit_id, role, step_id FROM exercises")}
        assert [b["unitId"] for b in placement["blocks"]] == ["u01", "u02"]
        for block in placement["blocks"]:
            assert len(block["exerciseIds"]) == 5
            assert all(exercises[e] == ("choice", block["unitId"], "placement", None) for e in block["exerciseIds"])
        assert final["indicativePassPerSection"] == 6
        assert [s["id"] for s in final["sections"]] == ["listening", "reading", "structures", "writing", "speaking"]
        formats = [exercises[e][0] for s in final["sections"] for e in s["exerciseIds"]]
        assert formats == ["choice", "choice", "choice", "choice", "writing", "talk"]
        assert con.execute("SELECT kind FROM units WHERE id = 'u99'").fetchone() == ("final",)
        letters = con.execute("SELECT letter, it FROM items WHERE letter IS NOT NULL ORDER BY letter").fetchall()
        assert letters == [("M", "emme"), ("S", "esse")]
        assert con.execute("SELECT it FROM items WHERE id = 'c:doppia'").fetchone() == ("doppia",)
        stored = con.execute("SELECT value FROM meta WHERE key = 'content_hash'").fetchone()[0]
        assert stored == db.canonical_hash(con)
    finally:
        con.close()
