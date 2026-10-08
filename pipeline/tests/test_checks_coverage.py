"""M1.11: check 1 (syllabus coverage), check 3 (recycling and balance), `content report`, and `content approve`
refusing a file that fails `content check`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import needs_data
from itcontent import approval, report, yamlio
from itcontent.annotate import run_annotate
from itcontent.checks import CheckResult, run_check, run_checks
from itcontent.checks.output import to_markdown
from test_checks import LESSON, add_story_line, annotate_and_check, edit, make_repo, messages

pytestmark = needs_data

UNIT_U02 = "content/units/02-al-bar/unit.yaml"


@pytest.fixture
def repo(root: Path, tmp_path: Path) -> Path:
    return make_repo(root, tmp_path / "repo")


@pytest.fixture(scope="module")
def seed(root: Path) -> CheckResult:
    return run_checks(root)


def entry(result: CheckResult, eid: str):
    assert result.coverage is not None
    return next(e for e in result.coverage.entries if e.id == eid)


# ---------------------------------------------------------------- check 1


def test_every_syllabus_entry_is_listed_with_its_three_locations(seed, root):
    syllabus = yamlio.load(root / "content/syllabus/a1-syllabus.yaml")["items"]
    assert seed.coverage is not None
    assert [e.id for e in seed.coverage.entries] == [e["id"] for e in syllabus]
    md = to_markdown(seed)
    table = md.split("## Syllabus coverage (check 1)")[1].split("\n## ")[0]
    rows = [r for r in table.splitlines() if r.startswith("| sy:")]
    assert len(rows) == len(syllabus) and all(r.count("|") == 7 for r in rows)
    assert "| sy:gr.articles | Articles, definite and indefinite | u02.l1.step-note (+1) | u02.l1.ex01 (+4) " in md


def test_coverage_roles_and_statuses(seed):
    articles = entry(seed, "sy:gr.articles")
    assert articles.status == "covered"
    assert [articles.first(r).ref for r in ("introduced", "practised", "assessed")] == [
        "u02.l1.step-note",
        "u02.l1.ex01",
        "u02.check.05",
    ]
    assert entry(seed, "sy:ss.open-closed-vowels").status == "info"  # roles: []
    # incomplete units: a gap is pending, never a warning
    assert entry(seed, "sy:gr.noun-gender-number").status == "pending"
    assert entry(seed, "sy:gr.noun-gender-number").missing == ["assessed"]
    # a chunk point is practised through its chunk (vorrei → c:vorrei)
    assert entry(seed, "sy:gr.vorrei").first("practised").ref == "u02.l1.ex08"
    # can-dos listing the entry count; topics trace through items
    assert entry(seed, "sy:fn.get-attention").first("introduced").ref == "u02.step-opener"
    assert entry(seed, "sy:tp.social-feelings-media").first("introduced").ref == "w:amico"
    assert not [f for f in seed.findings if f.check == 1 and f.level != "pending"]
    rows = seed.coverage.trace_rows()  # the pack's syllabus_trace
    assert rows == sorted(set(rows)) and ("sy:cefr.mediation", "assessed", "u02", "u02.check.09") in rows


def test_gaps_warn_in_report_mode_and_fail_in_enforce_mode(repo):
    edit(repo, UNIT_U02, "lessons: 3", "lessons: 1")  # Unit 2 complete: sy:gr.vorrei (units: [u02]) can't wait
    result = annotate_and_check(repo)
    gap = entry(result, "sy:gr.vorrei")
    assert gap.status == "gap" and gap.missing == ["assessed"]
    warned = messages(result, "warning", 1, "coverage")
    assert any("sy:gr.vorrei (vorrei) is not assessed anywhere in the course; coverage is" in m for m in warned)
    edit(repo, "content/checker.yaml", "coverage_mode: report", "coverage_mode: enforce")
    result = run_checks(repo)
    assert any("sy:gr.vorrei (vorrei) is not assessed" in m for m in messages(result, "error", 1, "coverage"))


def test_check_json_lists_coverage(repo):
    out: list[str] = []
    assert run_annotate(repo, echo=out.append) == 0
    out.clear()
    assert run_check(repo, as_json=True, echo=out.append) == 0
    data = json.loads(out[0])
    cov = data["coverage"]
    assert cov["mode"] == "report" and 0 < cov["percent"] < 100
    first = next(e for e in cov["entries"] if e["id"] == "sy:gr.articles")
    assert first["introduced"] == {"ref": "u02.l1.step-note", "unit": "u02", "via": "g:indefinite-article", "count": 2}
    assert data["recycling"]["stories"] == [{"text": "u02.l1.story", "unit": "u02", "words": 106, "range": [100, 200]}]


# ---------------------------------------------------------------- check 3


def test_golden_lesson_retrievals(seed):
    assert seed.recycling is not None
    got = {i.id: i.retrievals for i in seed.recycling.items if i.retrievals is not None}
    assert got == {
        "w:caffe": 5,
        "w:cappuccino": 5,
        "w:cornetto": 6,
        "w:spremuta": 4,
        "w:ecco": 5,
        "w:oggi": 4,
        "w:buono": 4,
        "w:amico": 4,
        "c:vorrei": 6,
        "c:quant-e": 4,
        "c:cosa-prende": 2,
        "c:da-mangiare": 0,
    }
    assert not [f for f in seed.findings if f.check == 3 and f.level != "pending"]


def test_too_few_retrievals(repo):
    edit(repo, LESSON, '["oggi", "today"], ', "")  # drop w:oggi from the match …
    edit(repo, LESSON, "          - {item: w:oggi, skill: read}\n", "")  # … and its target
    edit(
        repo,
        "content/items/u02.yaml",
        "status: P, lesson: u02.l2}\n  - {id: 'w:arancia'",
        "status: P, lesson: u02.l1}\n  - {id: 'w:arancia'",
    )  # w:latte: introduced only by a gloss in the story
    add_story_line(repo, '{speaker: narrator, it: "Un latte?", en: "A milk?", gloss: {latte: milk}}')
    result = annotate_and_check(repo)
    found = [str(f) for f in result.findings if f.rule == "retrievals"]
    assert any(m.startswith("warning:") and "w:oggi has 3 retrieval(s) in u02.l1" in m for m in found)
    assert any(m.startswith("error:") and "w:latte has 0 retrieval(s) in u02.l1" in m for m in found)


def test_complete_units_get_recycling_strand_and_story_length_findings(repo):
    edit(repo, UNIT_U02, "lessons: 3", "lessons: 1")
    edit(repo, UNIT_U02, "words: 100-200", "words: 150-250")
    result = annotate_and_check(repo)
    strands = [m.split("check 3 · strands: ")[1] for m in messages(result, "warning", 3, "strands")]
    assert any(m.startswith("u02: language-focus is 60% of the estimated 28 minutes") for m in strands), strands
    assert any(m.startswith("u02: input is 7%") for m in strands)
    assert not messages(result, "warning", 3, "recycling")  # 48% of its content words come from Units 0–1
    assert any(
        "u02.l1.story has 106 words; u02's stories should have 150–250" in m for m in messages(result, "warning")
    )
    assert not [f for f in result.findings if f.unit == "u02" and f.level == "pending"]


def test_encounters_and_spiral_are_judged_once_the_rest_of_the_course_is_complete(repo):
    edit(repo, UNIT_U02, "lessons: 3", "lessons: 1")
    edit(repo, "content/course.yaml", "12-com-e-andata, 99-ripasso]", "]")
    edit(repo, "content/course.yaml", "03-la-famiglia, 04-che-lavoro-fai, 05-la-mia-giornata,\n", "")
    edit(
        repo,
        "content/course.yaml",
        "06-in-citta, 07-al-mercato, 08-tempo-libero, 09-casa-mia, 10-che-tempo-fa, 11-in-viaggio,\n",
        "",
    )
    result = annotate_and_check(repo)
    enc = {
        m.split("check 3 · encounters: ")[1].split(" ")[0]: m.split(":")[0]
        for m in [*messages(result, "error", 3, "encounters"), *messages(result, "warning", 3, "encounters")]
    }
    assert enc["w:buono"] == "error"  # P, 3 encounters (< 6)
    assert enc["w:amico"] == "warning"  # P, 8 encounters (< 10)
    assert enc["c:da-mangiare"] == "warning"  # R, 2 encounters (< 6)
    assert "w:cornetto" not in enc  # 16
    spiral = messages(result, "warning", 3, "spiral")
    assert any(
        "g:indefinite-article (u02) returns in no later unit; it should come back in the final review" in m
        for m in spiral
    )


# ---------------------------------------------------------------- content report


def test_report_sections_and_open_comments(repo):
    (repo / "reviews").mkdir()
    (repo / "reviews" / "u02.yaml").write_text(
        "scope: u02\ncomments:\n"
        "  - {id: c1, target: u02.l1.story#3, verdict: change, category: naturalness, comment: Più naturale così,"
        " resolution: {status: open, note: null, commit: null}}\n"
        "  - {id: c2, target: u02.l1.ex04, verdict: question, category: answer-key, comment: Fine,"
        " resolution: {status: answered, note: ok, commit: null}}\n",
        encoding="utf-8",
    )
    out: list[str] = []
    assert report.run_report(repo, echo=out.append) == 0  # no lock files: the report still renders, it never fails
    assert run_annotate(repo, echo=lambda _: None) == 0
    out.clear()
    assert report.run_report(repo, unit="u02", echo=out.append) == 0
    text = out[0]
    for title in (
        "Overview",
        "New words per step",
        "Retrievals and encounters",
        "Strand split",
        "Syllabus coverage",
        "Budgets and exemptions",
        "Open review comments",
    ):
        assert f"## {title}" in text
    assert "- `u02.l1.story#3` Change · Unnatural: Più naturale così — reviews/u02.yaml `c1`" in text
    assert "u02.l1.ex04" not in text.split("## Open review comments")[1]
    assert (repo / "build/reports/report.md").read_text(encoding="utf-8") == text + "\n"
    assert report.run_report(repo, unit="u77", echo=out.append) == 2


def test_report_takes_new_section_providers(repo, monkeypatch):
    assert run_annotate(repo, echo=lambda _: None) == 0
    monkeypatch.setattr(report, "SECTIONS", [*report.SECTIONS])
    report.section(lambda rc: report.Section("audio", "Audio budget", [f"{rc.unit}: 0 MB"]))
    text = report.render(report.build_report(repo, unit="u02"), "u02")
    assert text.rstrip().endswith("## Audio budget\n\nu02: 0 MB")


# ---------------------------------------------------------------- approve refuses a file that fails the check


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_approve_refuses_a_file_that_fails_content_check(repo):
    edit(
        repo,
        LESSON,
        '{speaker: ch:giulia, to: ch:marco, register: lei, it: "Buongiorno! Cosa prende?"',
        '{speaker: ch:giulia, to: ch:marco, register: tu, it: "Buongiorno! Cosa prende?"',
    )
    assert run_annotate(repo, echo=lambda _: None) == 0
    out: list[str] = []
    kw = {"env": {}, "stdin": Tty(), "ask": lambda _p: "lesson-1.yaml", "echo": out.append}
    assert approval.approve(Path(LESSON), "Maria Rossi", root=repo, **kw) == 1
    assert out[-1] == f"{LESSON} fails content check (1 error(s)); fix them before approving"
    assert "check 5 · register" in out[0]
    assert "status: draft" in (repo / LESSON).read_text(encoding="utf-8")
