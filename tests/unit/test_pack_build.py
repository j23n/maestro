"""The seed pack must validate against the spec and build a sane bundle."""

import json
import sqlite3
from pathlib import Path

import pytest

from authoring.build_pack import build, load_pack_sources, validate_pack
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_seed_pack_validates_against_spec():
    _manifest, drills, readings, listenings = load_pack_sources(ROOT / "packs" / "it")
    errors = validate_pack(
        [*drills, *readings, *listenings], load_spec(ROOT / "spec" / "it")
    )
    assert errors == []
    assert len(drills) >= 14
    assert len(readings) >= 2
    assert len(listenings) >= 1


def test_build_produces_consistent_bundle(tmp_path):
    out = tmp_path / "it.pack.sqlite"
    assert build(ROOT / "packs" / "it", ROOT / "spec" / "it", out) == 0

    conn = sqlite3.connect(out)
    manifest = dict(conn.execute("SELECT key, value FROM manifest"))
    assert manifest["language"] == "it"

    items = conn.execute("SELECT id, item_type, payload FROM items").fetchall()
    answer_items = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT item_id FROM acceptable_answers WHERE is_canonical = 1"
        )
    }
    parents = 0
    for item_id, item_type, payload in items:
        parsed = json.loads(payload)
        assert parsed["evidence"], item_id
        if item_type in ("reading", "listening"):
            # Parent items carry the passage and their question ids; the
            # questions are the scorable children.
            parents += 1
            for qid in parsed["question_ids"]:
                assert qid in answer_items, qid
        else:
            assert parsed["prompt"], item_id
            assert item_id in answer_items
    assert parents >= 3

    # Spec tables are embedded and populated.
    for table, floor in [
        ("spec_grammar", 351),
        ("spec_functions", 465),
        ("spec_scenarios", 37),
        ("spec_can_dos", 60),
    ]:
        n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        assert n >= floor, table
    conn.close()


def test_draft_items_are_excluded_from_build(tmp_path):
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    draft = pack / "drills" / "zz_draft.yaml"
    draft.write_text(
        """
- id: drill.essere_pre.099
  status: draft
  item_type: drill_cloze
  cefr_level: A0
  prompt: "Noi ___ qui."
  answers: [{ text: siamo, canonical: true }]
  evidence: [{ axis: grammar, id: essere_pre, weight: 1.0 }]
"""
    )
    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out) == 0
    conn = sqlite3.connect(out)
    row = conn.execute(
        "SELECT count(*) FROM items WHERE id = 'drill.essere_pre.099'"
    ).fetchone()
    conn.close()
    assert row[0] == 0
