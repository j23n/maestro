"""The audio budget projection (M5.4; docs/04 § Pack build › Audio, ADR-17) and its `content report` section, on the
frozen seed course (conftest)."""

from __future__ import annotations

import shutil

import pytest

from conftest import copy_seed
from itcontent import audio_budget as budget
from itcontent.audio_assets import AudioPlan, AudioResolver
from itcontent.course import load_course
from itcontent.pack.build import AudioOptions, select_scope
from itcontent.pack.common import Report
from itcontent.pack.compile import Compiler
from itcontent.pack.locks import Locks
from itcontent.report import build_report, render
from itcontent.tts import run_tts
from itcontent.tts_azure import Voice
from itcontent.tts_needs import Voicing


def plan_for(root, caches=()) -> tuple[object, AudioPlan]:
    course = load_course(root)
    plan = AudioPlan(AudioResolver(list(caches)))
    report = Report()
    Compiler(
        course, Locks(root), select_scope(course, "dev", allow_partial=False, report=report), report, plan
    ).compile()
    return course, plan


def test_projection_without_any_audio(seed_root):
    course, plan = plan_for(seed_root)
    p = budget.project(course, plan)
    units = {u.unit: u for u in p.units}
    assert list(units) == [u.id for u in course.units]  # course order
    assert p.now == 0 and not p.calibrated and p.chars_per_second == budget.CHARS_PER_SECOND
    u02 = units["u02"]
    assert u02.needs == 60 and u02.voiced == 0 and u02.now == 0
    assert 0 < u02.written < u02.projected
    assert u02.missing == ["2 lessons", "36 items"]  # spec: 3 lessons, items 55–65; written: lesson 1, 29 items
    u03 = units["u03"]
    assert u03.needs == 0 and u03.written == 0 and u03.missing == ["3 lessons", "task", "check", "70 items"]
    assert u03.projected > u02.written  # three lessons, a task and a check at the course's averages
    assert units["u99"].missing[0] == "2 lessons" and "check" not in units["u99"].missing  # the final review
    assert p.projected == sum(u.projected for u in p.units) and not p.over_budget
    assert p.projected_fallback == round(p.projected * 40 / 48)
    line = budget.build_line(p)
    assert line.startswith("audio budget (MB now/projected): u00 0.0/") and "of 150 at 48kbps" in line


def test_estimates_follow_characters_rate_and_gaps():
    v = Voicing(
        {"voices": {"items": {"voice": "it-IT-ElsaNeural", "rate": "-10%"}, "narrator": {"voice": "it-IT-A"}}}, {}
    )
    slow = v.single("item:x", "item", "x", "u02", "content/items/u02.yaml", "a" * 26, "items", "x")
    normal = v.single("exercise:y:audioId", "exercise", "y", "u02", "f", "a" * 26, "narrator", "y")
    assert budget.estimate_ms(normal, 13.0) == budget.RENDER_PADDING_MS + 2000
    assert budget.estimate_ms(slow, 13.0) == budget.RENDER_PADDING_MS + round(2000 / 0.9)
    assert budget.part_kind("content/units/02-al-bar/lesson-1.yaml") == "lesson"
    assert budget.part_kind("content/units/02-al-bar/check.yaml") == "check"
    assert budget.part_kind("content/items/u02.yaml") == "items"
    assert budget.part_kind("content/assessments/placement.yaml") == "other"
    assert Voice("x", rate="+8%").rate == "+8%"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_rendered_audio_counts_with_its_encoded_size(tmp_path):
    repo = copy_seed(tmp_path / "repo")
    assert run_tts(repo, provider="mock", only=["w:cornetto"], echo=lambda _: None, lint=False) == 0
    options = AudioOptions.default(repo, "dev")
    course, plan = plan_for(repo, options.caches)
    encoded = {p.name: p for p in (repo / "build" / "audio").glob("*.m4a")}
    assert len(encoded) == 1
    p = budget.project(course, plan, encoded)
    u02 = next(u for u in p.units if u.unit == "u02")
    assert u02.voiced == 1  # the item need (the generated preview plays the same file; it is no need of its own)
    assert u02.now == next(iter(encoded.values())).stat().st_size
    assert not p.calibrated  # mock renders never calibrate the speaking rate

    text = render(build_report(repo, unit="u02"), "u02")
    section = text.split("## Audio budget", 1)[1].split("\n## ", 1)[0]
    assert "| Unit | Needs | Voiced | Minutes | MB now | MB written | MB projected | Still expected |" in section
    assert "| u02 | 60 | 1 |" in section and "| u03 |" not in section
    assert "MB projected of 150 MB" in section


def test_over_budget_says_what_adr17_prescribes(seed_root, monkeypatch):
    course, plan = plan_for(seed_root)
    monkeypatch.setattr(budget, "BUDGET_BYTES", 1024)
    lines = budget.report_lines(budget.project(course, plan))
    assert any(x.startswith("**Over budget:**") and "40kbps" in x for x in lines)
