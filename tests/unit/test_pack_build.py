"""The seed pack must validate against the spec and build a sane bundle."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from authoring.build_pack import (
    _normalize,
    build,
    coverage_report,
    load_pack_sources,
    validate_media,
    validate_pack,
    validate_tombstones,
)
from authoring.pack_schemas import DrillItem, TaskItem
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_seed_pack_validates_against_spec():
    sources = load_pack_sources(ROOT / "packs" / "it")
    spec = load_spec(ROOT / "spec" / "it")
    errors = validate_pack(sources.all_items(), spec)
    errors += validate_media(sources.all_items(), ROOT / "packs" / "it")
    errors += validate_tombstones(sources)
    assert errors == []
    assert len(sources.drills) >= 14
    assert len(sources.readings) >= 2
    assert len(sources.listenings) >= 1
    assert len(sources.vocab_cards) >= 4
    assert len(sources.speaking_prompts) >= 2
    assert len(sources.writing_prompts) >= 1
    assert len(sources.grammar_refs) >= 1


def test_build_produces_consistent_bundle(tmp_path):
    out = tmp_path / "it.pack.sqlite"
    assert build(ROOT / "packs" / "it", ROOT / "spec" / "it", out) == 0

    conn = sqlite3.connect(out)
    manifest = dict(conn.execute("SELECT key, value FROM manifest"))
    assert manifest["language"] == "it"
    assert manifest["schema_version"] == "1"

    items = conn.execute("SELECT id, item_type, payload FROM items").fetchall()
    answer_items = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT item_id FROM acceptable_answers WHERE is_canonical = 1"
        )
    }
    parents = 0
    by_type: dict[str, int] = {}
    for item_id, item_type, payload in items:
        parsed = json.loads(payload)
        by_type[item_type] = by_type.get(item_type, 0) + 1
        assert parsed["evidence"], item_id
        if item_type in ("reading", "listening"):
            # Parent items carry the passage and their question ids; the
            # questions are the scorable children.
            parents += 1
            for qid in parsed["question_ids"]:
                assert qid in answer_items, qid
        elif item_type in ("writing_prompt", "grammar_ref"):
            pass  # open/reference items are not answer-scored
        else:
            assert item_id in answer_items, item_id
    assert parents >= 3
    # Every item family made it into the bundle.
    for t in (
        "drill_cloze",
        "reading",
        "listening",
        "vocab_card",
        "speaking_prompt",
        "writing_prompt",
        "grammar_ref",
    ):
        assert by_type.get(t), t

    # A speaking prompt's target is scorable via acceptable_answers.
    target = conn.execute(
        "SELECT answer FROM acceptable_answers"
        " WHERE item_id = 'speaking.a0_ordinare.001' AND is_canonical = 1"
    ).fetchone()
    assert target[0] == "Vorrei un caffè, per favore."

    # Spec tables are embedded and populated.
    for table, floor in [
        ("spec_grammar", 351),
        ("spec_functions", 465),
        ("spec_scenarios", 37),
        ("spec_can_dos", 60),
        ("spec_vocab", 300),
    ]:
        n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        assert n >= floor, table
    # Media carries the pack's generated art; tombstones are empty for
    # the seed pack.
    assert conn.execute("SELECT count(*) FROM media").fetchone()[0] > 0
    assert conn.execute("SELECT count(*) FROM tombstones").fetchone()[0] == 0
    conn.close()

    # The build wrote a coverage report next to the bundle.
    report = json.loads(out.with_suffix(".coverage.json").read_text())
    assert report["totals"]["grammar_points_covered"] >= 8
    assert report["grammar_points"]["essere_pre"]["counts"]["drill"] >= 1


def test_draft_items_are_excluded_from_build(tmp_path):
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


def test_include_draft_compiles_draft_items(tmp_path):
    """`--include-draft` is the dev-pack escape hatch for content that has
    been authored but not yet reviewed. `release` never passes it."""
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
    assert build(pack, ROOT / "spec" / "it", out, include_draft=True) == 0
    conn = sqlite3.connect(out)
    row = conn.execute(
        "SELECT count(*) FROM items WHERE id = 'drill.essere_pre.099'"
    ).fetchone()
    conn.close()
    assert row[0] == 1, "draft item should be compiled when include_draft is set"


def test_scenario_ids_reach_the_bundle_and_are_checked(tmp_path):
    """The composer prefers items tagged with the session's scenario, so
    the tag has to survive the build — including onto the question items
    split out of a passage, which are scheduled inside their parent."""
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out, include_draft=True) == 0

    conn = sqlite3.connect(out)
    rows = dict(conn.execute("SELECT id, payload FROM items"))
    conn.close()
    assert json.loads(rows["reading.in_aereo.001"])["scenario_ids"] == [
        "a0-01-in-aereo"
    ]
    assert json.loads(rows["reading.in_aereo.001.q1"])["scenario_ids"] == [
        "a0-01-in-aereo"
    ], "question children must inherit the passage's scenario"
    # Shared material stays untagged — usable in any lesson.
    assert json.loads(rows["reading.la_giornata.001"])["scenario_ids"] == []

    spec = load_spec(ROOT / "spec" / "it")
    sources = load_pack_sources(pack)
    item = sources.readings[0].model_copy(update={"scenario_ids": ["a0-99-nowhere"]})
    assert any(
        "unknown scenario id a0-99-nowhere" in e for e in validate_pack([item], spec)
    )


def test_demand_reaches_the_bundle_at_the_right_rung(tmp_path):
    """`demand` is the spiral's rung, and it has to survive the build for
    the composer to select on it. The question children are the ones that
    matter: they are comprehension, not production, whatever their parent
    is — that mislabelling is what let a passage question count as a
    productive use of a speech act."""
    out = tmp_path / "bundle.sqlite"
    assert (
        build(ROOT / "packs" / "it", ROOT / "spec" / "it", out, include_draft=True) == 0
    )

    conn = sqlite3.connect(out)
    rows = {
        r[0]: (r[1], json.loads(r[2]).get("demand"))
        for r in conn.execute("SELECT id, item_type, payload FROM items")
    }
    conn.close()

    by_type: dict[str, set] = {}
    for item_type, demand in rows.values():
        by_type.setdefault(item_type, set()).add(demand)

    assert by_type["reading"] == {"meet"}
    assert by_type["reading_question"] == {"meet"}
    assert by_type["listening_question"] == {"meet"}
    assert by_type["drill_cloze"] == {"use"}
    assert by_type["writing_prompt"] == {"perform"}
    # A reference page is presentation, not an attempt: it emits
    # `introduced` and never carries evidence about the learner.
    assert by_type["grammar_ref"] == {None}


def test_demand_rungs_that_contradict_the_item_are_rejected():
    """The rung has to describe what the learner actually does, or the
    mastery weight it drives is a lie."""
    base = dict(
        id="drill.saluti.900",
        cefr_level="A0",
        prompt="«___, signora!»",
        answers=[{"text": "buongiorno", "canonical": True}],
        evidence=[{"axis": "grammar", "id": "saluti"}],
    )
    with pytest.raises(ValidationError, match="recognition"):
        DrillItem(**base, item_type="drill_cloze", demand="meet")
    # The same rung is fine when the learner only has to pick.
    DrillItem(
        **base,
        item_type="drill_multiple_choice",
        demand="meet",
        choices=["buongiorno", "buonasera"],
    )


def test_capstone_is_the_only_item_that_can_achieve_a_cando():
    """A can-do moves to `achieved` on cando-axis evidence and nothing
    else, so a capstone without it is inert — and until this item family
    existed, no authored item carried that axis at all."""
    base = dict(
        id="task.al_bar.d1",
        cefr_level="A0",
        mode="speaking",
        prompt="Ordina un caffè e chiedi quanto costa.",
        target_text="Vorrei un caffè, per favore. Quant'è?",
        rubric=["orders a coffee", "asks the price"],
    )
    with pytest.raises(ValidationError, match="cando-axis"):
        TaskItem(**base, demand="use", evidence=[{"axis": "grammar", "id": "vorrei"}])

    task = TaskItem(
        **base, demand="use", evidence=[{"axis": "cando", "id": "a0.order_something"}]
    )
    assert task.item_type == "task"

    # Speaking is scored by alignment against the target, so it needs one.
    with pytest.raises(ValidationError, match="target_text"):
        TaskItem(
            **{**base, "target_text": None},
            demand="perform",
            evidence=[{"axis": "cando", "id": "a0.order_something"}],
        )


def test_perform_capstone_withholds_its_target(tmp_path):
    """The closing capstone is the pass with no scaffolding — showing the
    target would make it a reading-aloud exercise. Scoring still has it."""
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    (pack / "tasks").mkdir(exist_ok=True)
    (pack / "tasks" / "probe.yaml").write_text(
        json.dumps(
            [
                {
                    "id": "task.probe.d1",
                    "item_type": "task",
                    "cefr_level": "A0",
                    "demand": "perform",
                    "mode": "speaking",
                    "prompt": "Ordina per tutti e due.",
                    "target_text": "Vorrei due caffè, per favore.",
                    "rubric": ["orders for two"],
                    "scenario_ids": ["a0-03-al-bar"],
                    "evidence": [{"axis": "cando", "id": "a0.order_something"}],
                }
            ]
        )
    )
    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out, include_draft=True) == 0

    conn = sqlite3.connect(out)
    payload = json.loads(
        conn.execute("SELECT payload FROM items WHERE id = 'task.probe.d1'").fetchone()[
            0
        ]
    )
    answers = [
        r[0]
        for r in conn.execute(
            "SELECT answer FROM acceptable_answers WHERE item_id = 'task.probe.d1'"
        )
    ]
    conn.close()
    assert payload["target_text"] is None, "a perform capstone shows nothing to copy"
    assert payload["demand"] == "perform"
    assert "Vorrei due caffè, per favore." in answers, "but it is still scorable"


def test_media_files_are_embedded_and_missing_ones_rejected(tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    (pack / "audio").mkdir()
    (pack / "audio" / "listening.al_bar.wav").write_bytes(b"RIFFfakewav")
    listening = pack / "listenings" / "a1_basics.yaml"
    listening.write_text(
        listening.read_text().replace(
            "audio: null", "audio: audio/listening.al_bar.wav"
        )
    )

    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out) == 0
    conn = sqlite3.connect(out)
    kind, sha, blob = conn.execute(
        "SELECT kind, sha256, bytes FROM media WHERE path = 'audio/listening.al_bar.wav'"
    ).fetchone()
    conn.close()
    assert kind == "audio"
    assert blob == b"RIFFfakewav"
    assert len(sha) == 64

    # A dangling reference must fail the build.
    listening.write_text(
        listening.read_text().replace(
            "audio/listening.al_bar.wav", "audio/nonexistent.wav"
        )
    )
    assert build(pack, ROOT / "spec" / "it", tmp_path / "bad.sqlite") == 1


def test_tombstoned_ids_must_be_absent(tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    (pack / "tombstones.yaml").write_text(
        "- { item_id: drill.essere_pre.001, removed_in: 0.2.0 }\n"
    )
    # drill.essere_pre.001 is still a live item -> build must refuse.
    assert build(pack, ROOT / "spec" / "it", tmp_path / "bundle.sqlite") == 1

    (pack / "tombstones.yaml").write_text(
        "- { item_id: drill.gone.001, removed_in: 0.2.0, reason: reworked }\n"
    )
    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out) == 0
    conn = sqlite3.connect(out)
    rows = conn.execute("SELECT item_id, removed_in, reason FROM tombstones").fetchall()
    conn.close()
    assert rows == [("drill.gone.001", "0.2.0", "reworked")]


def test_normalize_matches_conformance_vectors():
    """The Python build-time normalizer is pinned to the same golden
    vectors as core/src/normalize.rs — the cross-language contract."""
    data = json.loads((ROOT / "conformance" / "normalize_vectors.json").read_text())
    assert len(data["vectors"]) >= 15
    for v in data["vectors"]:
        assert _normalize(v["input"]) == v["normalized"], v["input"]


def test_coverage_report_shape():
    sources = load_pack_sources(ROOT / "packs" / "it")
    spec = load_spec(ROOT / "spec" / "it")
    report = coverage_report(sources.all_items(), spec)
    assert report["levels"]["A0"]["vocab_card"] >= 4
    assert report["grammar_points"]["vorrei"]["counts"]["speaking_prompt"] >= 1
