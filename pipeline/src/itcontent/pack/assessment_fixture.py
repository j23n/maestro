"""`fixtures/packs/assessment.sqlite`: the mini pack plus placement and final-check rows, for the App's tests.

The course's `placement.yaml` and `final-check.yaml` are skeletons until content task C6, so no pack built from
`content/` can place a learner or run the final check yet. The App's container paths (placement after onboarding,
the final check's sitting, score, recordings and examiner export) are tested on Linux against this fixture instead:
`fixtures/packs/mini.sqlite` with

- placement blocks for Units 1 and 2, five `choice` items each (copies of `u02.l1.ex17`, role `placement`);
- the final review unit `u99` and a final check of five sections (listening ×2 and reading at two points each,
  structures: `choice` copies; writing: the contract's `u01.task.write` form; speaking: a copy of `u02.task.talk`),
  with an indicative pass of **6** per section, so a test can tell the pack's pass mark from the usual 7;
- `meta.content_hash` recomputed.

Rebuilt by `make mini-pack` after the mini pack; `test_assessment_fixture.py` checks the committed file is fresh.
Not course content: the items are copies, never shown to a learner.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from itcontent import paths
from itcontent.pack import db

PASS_PER_SECTION = 6
PLACEMENT_UNITS = ("u01", "u02")
FINAL_UNIT = ("u99", 99, "Ripasso finale", "Final review", "Marco looks back on his first months in Bologna", 60)
# (section, title, [(exercise id, source, score)])
FINAL_SECTIONS: tuple[tuple[str, str, tuple[tuple[str, str, int], ...]], ...] = (
    ("listening", "Listening", (("fin.listening.01", "u02.l1.ex17", 2), ("fin.listening.02", "u02.l1.ex17", 2))),
    ("reading", "Reading", (("fin.reading.01", "u02.l1.ex17", 2),)),
    ("structures", "Structures", (("fin.structures.01", "u02.l1.ex17", 1),)),
    ("writing", "Writing", (("fin.writing.01", "example:u01.task.write", 1),)),
    ("speaking", "Speaking", (("fin.speaking.01", "u02.task.talk", 1),)),
)


def default_paths() -> tuple[Path, Path, Path]:
    packs = paths.FIXTURES / "packs"
    return packs / "mini.sqlite", packs / "payload-examples.json", packs / "assessment.sqlite"


def _source(con: sqlite3.Connection, examples: dict[str, Any], source: str) -> tuple[dict[str, Any], int, list[Any]]:
    """(payload, est_seconds, requires rows) of an exercise in the mini pack, or of a contract example."""
    if source.startswith("example:"):
        wanted = source.removeprefix("example:")
        payload = next(e for e in examples["exercises"] if e["id"] == wanted)
        return dict(payload), 300, []
    row = con.execute("SELECT payload, est_seconds FROM exercises WHERE id = ?", (source,)).fetchone()
    if row is None:
        raise SystemExit(f"the mini pack has no exercise {source}: run `make mini-pack`")
    requires = con.execute(
        "SELECT item_id, skill FROM exercise_requires WHERE exercise_id = ? ORDER BY item_id, skill", (source,)
    ).fetchall()
    return json.loads(row[0]), int(row[1]), requires


def _add_exercise(
    con: sqlite3.Connection,
    examples: dict[str, Any],
    *,
    exercise_id: str,
    source: str,
    unit: str,
    role: str,
    score: int,
) -> None:
    payload, seconds, requires = _source(con, examples, source)
    payload.update({"id": exercise_id, "unitId": unit, "role": role, "stepId": None, "score": score})
    payload.setdefault("targets", [])
    con.execute(
        "INSERT INTO exercises VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL)",
        (
            exercise_id,
            payload["format"],
            unit,
            role,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            score,
            seconds,
        ),
    )
    for target in payload["targets"]:
        con.execute("INSERT INTO exercise_targets VALUES (?, ?, ?)", (exercise_id, target["itemId"], target["skill"]))
    for item_id, skill in requires:
        con.execute("INSERT INTO exercise_requires VALUES (?, ?, ?)", (exercise_id, item_id, skill))
    for tag in payload.get("tags") or []:
        con.execute("INSERT INTO exercise_tags VALUES (?, ?)", (exercise_id, tag))


def build(mini: Path, examples_path: Path, out: Path) -> str:
    """Writes the fixture and returns its pack hash."""
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    source = sqlite3.connect(f"file:{mini}?mode=ro", uri=True)
    con = sqlite3.connect(":memory:")
    try:
        source.backup(con)
    finally:
        source.close()
    blocks = []
    for unit in PLACEMENT_UNITS:
        ids = [f"pl.{unit}.{n}" for n in range(1, 6)]
        for exercise_id in ids:
            _add_exercise(
                con, examples, exercise_id=exercise_id, source="u02.l1.ex17", unit=unit, role="placement", score=1
            )
        blocks.append({"unitId": unit, "exerciseIds": ids})
    con.execute("INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, 'final')", FINAL_UNIT)
    sections = []
    for section, title, exercises in FINAL_SECTIONS:
        for exercise_id, src, score in exercises:
            _add_exercise(con, examples, exercise_id=exercise_id, source=src, unit="u99", role="final", score=score)
        sections.append({"id": section, "titleEn": title, "max": 12, "exerciseIds": [e[0] for e in exercises]})
    assessments = [
        ("placement", {"id": "placement", "advanceThreshold": 4, "blocks": blocks}),
        ("final", {"id": "final", "indicativePassPerSection": PASS_PER_SECTION, "sections": sections}),
    ]
    for key, payload in assessments:
        con.execute(
            "INSERT INTO assessments VALUES (?, ?)",
            (key, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        )
    con.commit()
    problems = con.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise SystemExit(f"assessment fixture: references to missing rows: {problems[:5]}")
    pack_hash = db.canonical_hash(con)
    con.execute("UPDATE meta SET value = ? WHERE key = 'content_hash'", (pack_hash,))
    con.commit()
    db.write(con, out)
    con.close()
    return pack_hash


def main() -> int:
    mini, examples, out = default_paths()
    pack_hash = build(mini, examples, out)
    print(f"{out.relative_to(paths.ROOT)}: {pack_hash[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
