"""M6.7: `content beta-import` on a recorded JSONL export (fixtures/beta/events.jsonl, the server's export format)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from itcontent.beta import analyse, read_events, run_beta_import
from itcontent.cli import app


def test_reads_dedupes_and_orders(fixtures_dir):
    pairs = read_events(fixtures_dir / "beta" / "events.jsonl")
    assert len(pairs) == 18  # the duplicated line counts once
    ats = [e["at"] for _, e in pairs]
    assert ats == sorted(ats)


def test_item_statistics_use_first_attempts_only(fixtures_dir):
    r = analyse(read_events(fixtures_dir / "beta" / "events.jsonl"))
    cornetto = r.items["w:cornetto|recall"]
    # 4 first attempts (3 + one more from learner 1), all wrong; second attempts and placement are excluded
    assert (cornetto.first_attempts, cornetto.first_errors) == (4, 4)
    assert cornetto.median_latency_ms == 6500
    assert r.items["c:quant-e|recall"].error_rate == 0
    assert r.items["c:vorrei|speak"].skips == 1 and r.items["c:vorrei|speak"].first_attempts == 0
    assert "w:cornetto|recall" in r.items and not any(k.startswith("pl.") for k in r.exercises)
    assert r.gloss_taps["c:da-mangiare"] == 3
    assert r.gloss_taps["u02.l1.story#1:3"] == 1
    assert r.learners == 3


def test_rejected_answers_grouped_by_exercise_and_turn(fixtures_dir):
    r = analyse(read_events(fixtures_dir / "beta" / "events.jsonl"))
    assert r.rejected["u02.l1.ex04"] == {"una cornetto": 3, "il cornetto": 1}
    assert r.rejected["u02.task.conv1/n1"] == {"vorrei cappuccino": 1}
    assert "pl.01" in r.rejected  # placement answers are still worth adjudicating


def test_reports_are_written_deterministically(fixtures_dir, tmp_path):
    run_beta_import(fixtures_dir / "beta" / "events.jsonl", tmp_path / "a")
    run_beta_import(fixtures_dir / "beta" / "events.jsonl", tmp_path / "b")
    for name in ("items.json", "items.md", "rejected.json", "rejected.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    rejected = json.loads((tmp_path / "a" / "rejected.json").read_text())
    assert rejected["u02.l1.ex04"][0] == {"response": "una cornetto", "count": 3}
    md = (tmp_path / "a" / "items.md").read_text()
    assert md.index("`w:cornetto`") < md.index("`c:quant-e`")  # outliers first


def test_cli(fixtures_dir, tmp_path):
    result = CliRunner().invoke(
        app, ["beta-import", str(fixtures_dir / "beta" / "events.jsonl"), "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "18 events from 3 learners" in result.output
    assert (tmp_path / "rejected.md").exists()
