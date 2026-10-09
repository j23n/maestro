"""CL21: check 3's strand balance (docs/04 § Check 3). A band per strand, a language-focus ceiling that depends on the
unit, and listening time in the estimate (a story or listening text is heard as well as read: a story once, a
listening text up to twice; fluency replay is the stories' audio at `fluency_rate`).

The check tests run on the frozen seed course (conftest), where Unit 2 counts as complete once its spec plans one
lesson: the golden lesson's story (106 words, 3 questions) is the unit's only text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import needs_data
from itcontent import paths, report, yamlio
from itcontent.checks import CheckResult, run_check, run_checks
from itcontent.checks.output import band_line, to_json, to_markdown
from itcontent.checks.recycling import LISTENING_PLAYS, UnitStats, bound_for, listening_plays, unit_runs
from itcontent.course import load_course
from itcontent.lint import lint_findings
from test_checks import LESSON, annotate_and_check, edit, messages

CHECKER = "content/checker.yaml"
UNIT_U02 = "content/units/02-al-bar/unit.yaml"
LF_MAX = "language-focus: {min: 0.15, max: {u00: 0.60, u03: 0.50}}"
STORY_WORDS = 106  # u02.l1.story
STORY_QUESTIONS = 3
ORDER = {u: i for i, u in enumerate(["u00", "u01", "u02", "u03", "u04", "u99"])}
STORY_STEP = "  - kind: story\n    id: u02.l1.step-story\n"
SRC = " (checker.yaml strands.bands)"
LIVE_BANDS = {"fluency": [0.1, 0.35], "input": [0.15, 0.35], "language-focus": [0.15, 0.6], "output": [0.15, 0.35]}


def test_a_bound_is_a_share_or_a_map_of_shares_from_each_unit_on():
    assert bound_for(0.35, "u02", ORDER, 0.0) == 0.35
    ceiling = {"u03": 0.50, "u00": 0.60}  # key order doesn't matter: course order does
    assert [bound_for(ceiling, u, ORDER, 0.0) for u in ORDER] == [0.60, 0.60, 0.60, 0.50, 0.50, 0.50]
    assert bound_for({"u42": 0.40}, "u02", ORDER, 0.35) == 0.35  # no unit of the course: the default
    assert bound_for(None, "u02", ORDER, 0.15) == 0.15
    floor = {"u00": 0.15, "u02": 0.08}  # a map works on the min side too
    assert [bound_for(floor, u, ORDER, 0.0) for u in ORDER] == [0.15, 0.15, 0.08, 0.08, 0.08, 0.08]


def test_a_listening_text_is_heard_up_to_twice():
    assert LISTENING_PLAYS == 2
    assert [listening_plays({"plays": n}) for n in (1, 2, 3)] == [1, 2, 2]
    assert listening_plays({}) == listening_plays({"plays": None}) == listening_plays({"plays": "unlimited"}) == 2


def test_unit_runs_and_the_band_line():
    order = list(ORDER)
    assert unit_runs(["u99", "u03", "u04"], order) == "u03–u99"
    assert unit_runs(["u00", "u02", "u03"], order) == "u00, u02–u03"

    def row(uid: str, lf: float, fluency_min: float = 0.10) -> dict:
        bands = {**LIVE_BANDS, "language-focus": [0.15, lf], "fluency": [fluency_min, 0.35]}
        return {"id": uid, "bands": bands}

    units = [row("u00", 0.6), row("u01", 0.6, 0.05), row("u02", 0.6), row("u03", 0.5), row("u99", 0.5)]
    assert band_line(units) == (
        "Bands (checker.yaml `strands.bands`): input 15%–35%; language focus 15%–60% (u00–u02), 15%–50% (u03–u99); "
        "output 15%–35%; fluency 10%–35% (u00), 5%–35% (u01), 10%–35% (u02–u99)."
    )


def test_the_live_bands_are_the_content_leads():
    """CL21: input and output 15–35%, fluency 10–35%, language focus 15–60% in Units 0–2 and 15–50% from Unit 3."""
    bands = yamlio.load(paths.ROOT / CHECKER)["strands"]["bands"]
    order = load_course(paths.ROOT).unit_order()

    def band(strand: str, unit: str) -> tuple[float, float]:
        b = bands[strand]
        return bound_for(b["min"], unit, order, -1.0), bound_for(b["max"], unit, order, -1.0)

    for unit in order:
        assert band("input", unit) == (0.15, 0.35)
        assert band("output", unit) == (0.15, 0.35)
        assert band("fluency", unit) == (0.10, 0.35)
        assert band("language-focus", unit) == (0.15, 0.60 if unit in ("u00", "u01", "u02") else 0.50), unit
    assert order["u99"] > order["u03"]  # the final review takes the later ceiling


def test_lint_rejects_the_single_band_and_a_missing_audio_per_word(course_copy: Path):
    edit(course_copy, CHECKER, "  bands:\n", "  min_share: 0.15\n  max_share: 0.35\n  bands:\n")
    edit(course_copy, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u00: 0.60, unit3: 0.50}}")
    edit(course_copy, CHECKER, "  audio_per_word: 0.6", "  # audio_per_word: 0.6")
    found = [str(f) for f in lint_findings(course_copy) if f.file == CHECKER]
    assert any("strands.min_share" in f and f.startswith("error:") for f in found), found
    assert any("strands.max_share" in f and f.startswith("error:") for f in found), found
    assert any("strands.bands.language-focus.max" in f and f.startswith("error:") for f in found), found
    assert any("durations_seconds" in f and "audio_per_word" in f and f.startswith("error:") for f in found), found


@pytest.fixture
def repo(course_copy: Path) -> Path:
    """The seed course with Unit 2 complete (one lesson planned, one written)."""
    edit(course_copy, UNIT_U02, "lessons: 3", "lessons: 1")
    return course_copy


def u02(result: CheckResult) -> UnitStats:
    assert result.recycling is not None
    return next(u for u in result.recycling.units if u.id == "u02")


@needs_data
@pytest.mark.parametrize(
    ("kind", "plays", "heard"),
    [
        ("story", None, 1),
        ("listening", None, 2),  # unset: twice
        ("listening", "plays: unlimited", 2),
        ("listening", "plays: 1", 1),
        ("listening", "plays: 3", 2),  # at most twice
        ("reading", None, 0),  # not voiced
    ],
)
def test_a_text_is_read_and_heard(repo, kind, plays, heard):
    """The golden story step as a story, a listening step (with its `plays`) or a reading step."""
    edit(repo, CHECKER, "audio_per_word: 0.6", "audio_per_word: 0.5")  # apart from story_per_word (0.6)
    dur = yamlio.load(repo / CHECKER)["durations_seconds"]
    read, audio, questions = dur["story_per_word"], dur["audio_per_word"], STORY_QUESTIONS * dur["comprehension"]
    base = u02(annotate_and_check(repo))  # as written: a story
    if kind != "story":
        edit(repo, LESSON, STORY_STEP, STORY_STEP.replace("story", kind, 1) + (f"    {plays}\n" if plays else ""))
    stats = u02(annotate_and_check(repo)) if kind != "story" else base
    assert stats.seconds["input"] == pytest.approx(STORY_WORDS * (read + heard * audio) + questions)
    replay = STORY_WORDS * audio / dur["fluency_rate"]  # fluency replay: the stories' audio, played faster
    assert base.seconds["fluency"] - stats.seconds["fluency"] == pytest.approx(0 if kind == "story" else replay)
    assert base.seconds["fluency"] > replay  # plus the lesson's repeat-after-me exercises
    assert stats.seconds["language-focus"] == base.seconds["language-focus"]


@needs_data
def test_each_strand_is_held_to_its_band_in_its_unit(repo):
    result = annotate_and_check(repo)
    assert sorted(m.split("check 3 · strands: ")[1] for m in messages(result, "warning", 3, "strands")) == [
        "u02: fluency is 5% of the estimated 29 minutes (1 min); its band in u02 is 10%–35%" + SRC,
        "u02: input is 10% of the estimated 29 minutes (3 min); its band in u02 is 15%–35%" + SRC,
    ]  # language focus is 58%: within Units 0–2's ceiling of 60%
    edit(repo, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u00: 0.60, u02: 0.50}}")
    found = [m.split("check 3 · strands: ")[1] for m in messages(run_checks(repo), "warning", 3, "strands")]
    assert "u02: language-focus is 58% of the estimated 29 minutes (17 min); its band in u02 is 15%–50%" + SRC in found


@needs_data
def test_a_unit_map_on_the_min_side_lowers_a_floor_from_its_unit_on(repo):
    edit(repo, CHECKER, "input: {min: 0.15, max: 0.35}", "input: {min: {u00: 0.15, u02: 0.08}, max: 0.35}")
    edit(repo, CHECKER, "fluency: {min: 0.10, max: 0.35}", "fluency: {min: {u00: 0.10, u02: 0.04}, max: 0.35}")
    result = annotate_and_check(repo)
    assert messages(result, "warning", 3, "strands") == []  # input 10% ≥ 8%, fluency 5% ≥ 4% in u02
    assert messages(result, "error", 3, "strands") == []
    bands = {u.id: u.bands for u in result.recycling.units} if result.recycling else {}
    assert bands["u01"]["input"] == (0.15, 0.35) and bands["u02"]["input"] == (0.08, 0.35)
    assert bands["u99"]["fluency"] == (0.04, 0.35)


@needs_data
def test_a_band_whose_min_is_above_its_max_is_one_config_error(repo):
    edit(repo, CHECKER, "input: {min: 0.15, max: 0.35}", "input: {min: 0.40, max: 0.35}")
    edit(repo, CHECKER, LF_MAX, "language-focus: {min: {u00: 0.15, u03: 0.55}, max: {u00: 0.60, u03: 0.50}}")
    result = annotate_and_check(repo)
    assert messages(result, "error", 3, "strands") == [
        "error: content/checker.yaml › strands.bands.input (line 24): check 3 · strands: the input band's min is "
        "above its max in u00–u99 (40% > 35% in u00)",
        "error: content/checker.yaml › strands.bands.language-focus (line 27): check 3 · strands: the "
        "language-focus band's min is above its max in u03–u99 (55% > 50% in u03)",
    ]
    strands = messages(result, "warning", 3, "strands")
    assert not any("u02: input" in m for m in strands), strands  # the error says it once, no warning per unit


@needs_data
def test_the_bands_are_in_check_json_check_md_and_the_report(repo):
    run_check(repo, echo=lambda _: None)  # writes the reports (the one-lesson Unit 2 has check 4 errors of its own)
    reports = repo / "build" / "reports"
    data = json.loads((reports / "check.json").read_text(encoding="utf-8"))
    (row,) = [u for u in data["recycling"]["units"] if u["id"] == "u02"]
    assert row["bands"] == LIVE_BANDS
    line = (
        "Bands (checker.yaml `strands.bands`): input 15%–35%; language focus 15%–60%; output 15%–35%; fluency 10%–35%."
    )
    assert line in (reports / "check.md").read_text(encoding="utf-8").splitlines()
    assert report.run_report(repo, echo=lambda _: None) == 0
    assert line in (reports / "report.md").read_text(encoding="utf-8").splitlines()


@needs_data
def test_check_md_and_the_report_show_per_unit_runs(repo):
    """Only Unit 2 has steps in the seed course, so a second unit's row is added to the measured result."""
    result = annotate_and_check(repo)
    assert result.recycling is not None
    later = UnitStats("u03", False, bands={**u02(result).bands, "language-focus": (0.15, 0.5)})
    later.seconds["input"] = 60.0
    result.recycling.units.append(later)
    line = (
        "Bands (checker.yaml `strands.bands`): input 15%–35%; language focus 15%–60% (u02), 15%–50% (u03); "
        "output 15%–35%; fluency 10%–35%."
    )
    assert line in to_markdown(result).splitlines()
    assert [u["bands"]["language-focus"] for u in to_json(result)["recycling"]["units"]] == [[0.15, 0.6], [0.15, 0.5]]
    section = report.strands(report.ReportContext(repo, None, result))
    assert line in section.lines


@needs_data
def test_a_band_map_starts_at_the_first_unit_and_names_only_course_units(repo):
    edit(repo, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u01: 0.60, u42: 0.50}}")
    assert messages(annotate_and_check(repo), "error", 3, "strands") == [
        "error: content/checker.yaml › strands.bands.language-focus.max (line 27): check 3 · strands: the "
        "language-focus max share starts at u01; start it at the course's first unit, u00",
        "error: content/checker.yaml › strands.bands.language-focus.max (line 27): check 3 · strands: u42: not a "
        "unit of course.yaml",
    ]
