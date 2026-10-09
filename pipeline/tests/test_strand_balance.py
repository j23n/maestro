"""CL21: check 3's strand balance (docs/04 § Check 3). A band per strand, a language-focus ceiling that depends on the
unit, and listening time in the estimate (a story or listening text is heard as well as read; a listening text twice).

The check tests run on the frozen seed course (conftest), where Unit 2 counts as complete once its spec plans one
lesson: the golden lesson's story (106 words, 3 questions) is the unit's only text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import needs_data
from itcontent import paths, yamlio
from itcontent.checks import CheckResult, run_checks
from itcontent.checks.recycling import LISTENING_PLAYS, UnitStats, bound_for
from itcontent.course import load_course
from itcontent.lint import lint_findings
from test_checks import LESSON, annotate_and_check, edit, messages

CHECKER = "content/checker.yaml"
UNIT_U02 = "content/units/02-al-bar/unit.yaml"
LF_MAX = "language-focus: {min: 0.15, max: {u00: 0.60, u03: 0.50}}"
STORY_WORDS = 106  # u02.l1.story
STORY_QUESTIONS = 3
ORDER = {u: i for i, u in enumerate(["u00", "u01", "u02", "u03", "u04", "u99"])}


def test_a_bound_is_a_share_or_a_map_of_shares_from_each_unit_on():
    assert bound_for(0.35, "u02", ORDER, 0.0) == 0.35
    ceiling = {"u03": 0.50, "u00": 0.60}  # key order doesn't matter: course order does
    assert [bound_for(ceiling, u, ORDER, 0.0) for u in ORDER] == [0.60, 0.60, 0.60, 0.50, 0.50, 0.50]
    assert bound_for({"u42": 0.40}, "u02", ORDER, 0.35) == 0.35  # no unit of the course: the default
    assert bound_for(None, "u02", ORDER, 0.15) == 0.15


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


def test_lint_rejects_the_single_band(course_copy: Path):
    edit(course_copy, CHECKER, "  bands:\n", "  min_share: 0.15\n  max_share: 0.35\n  bands:\n")
    edit(course_copy, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u00: 0.60, unit3: 0.50}}")
    found = [str(f) for f in lint_findings(course_copy) if f.file == CHECKER]
    assert any("strands.min_share" in f and f.startswith("error:") for f in found), found
    assert any("strands.max_share" in f and f.startswith("error:") for f in found), found
    assert any("strands.bands.language-focus.max" in f and f.startswith("error:") for f in found), found


@pytest.fixture
def repo(course_copy: Path) -> Path:
    """The seed course with Unit 2 complete (one lesson planned, one written)."""
    edit(course_copy, UNIT_U02, "lessons: 3", "lessons: 1")
    return course_copy


def u02(result: CheckResult) -> UnitStats:
    assert result.recycling is not None
    return next(u for u in result.recycling.units if u.id == "u02")


@needs_data
def test_a_story_is_read_and_heard_and_a_listening_text_heard_twice(repo):
    edit(repo, CHECKER, "audio_per_word: 0.6", "audio_per_word: 0.5")  # apart from story_per_word (0.6)
    dur = yamlio.load(repo / CHECKER)["durations_seconds"]
    read, heard, questions = dur["story_per_word"], dur["audio_per_word"], STORY_QUESTIONS * dur["comprehension"]
    story = u02(annotate_and_check(repo))
    assert story.seconds["input"] == pytest.approx(STORY_WORDS * (read + heard) + questions)  # 161.6 s

    edit(repo, LESSON, "  - kind: story\n    id: u02.l1.step-story", "  - kind: listening\n    id: u02.l1.step-story")
    listening = u02(annotate_and_check(repo))
    assert LISTENING_PLAYS == 2
    assert listening.seconds["input"] == pytest.approx(STORY_WORDS * (read + 2 * heard) + questions)  # 214.6 s
    replay = STORY_WORDS * read / dur["fluency_rate"]  # fluency replay counts stories only
    assert story.seconds["fluency"] - listening.seconds["fluency"] == pytest.approx(replay)
    assert listening.seconds["language-focus"] == story.seconds["language-focus"]


@needs_data
def test_each_strand_is_held_to_its_band_in_its_unit(repo):
    result = annotate_and_check(repo)
    src = " (checker.yaml strands.bands)"
    assert sorted(m.split("check 3 · strands: ")[1] for m in messages(result, "warning", 3, "strands")) == [
        "u02: fluency is 5% of the estimated 29 minutes (1 min); its band in u02 is 10%–35%" + src,
        "u02: input is 10% of the estimated 29 minutes (3 min); its band in u02 is 15%–35%" + src,
    ]  # language focus is 58%: within Units 0–2's ceiling of 60%
    edit(repo, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u00: 0.60, u02: 0.50}}")
    found = [m.split("check 3 · strands: ")[1] for m in messages(run_checks(repo), "warning", 3, "strands")]
    assert "u02: language-focus is 58% of the estimated 29 minutes (17 min); its band in u02 is 15%–50%" + src in found


@needs_data
def test_a_band_map_starts_at_the_first_unit_and_names_only_course_units(repo):
    edit(repo, CHECKER, LF_MAX, "language-focus: {min: 0.15, max: {u01: 0.60, u42: 0.50}}")
    assert messages(annotate_and_check(repo), "error", 3, "strands") == [
        "error: content/checker.yaml › strands.bands.language-focus.max (line 27): check 3 · strands: the "
        "language-focus max share starts at u01; start it at the course's first unit, u00",
        "error: content/checker.yaml › strands.bands.language-focus.max (line 27): check 3 · strands: u42: not a "
        "unit of course.yaml",
    ]
