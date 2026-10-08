"""M8.3: answer adjudication. Rejected answers from the beta (`content beta-import`) appear on the next review page
as "Answers to adjudicate"; `content review-import` turns the teacher's verdicts (and "This should be accepted"
comments from the app) into answer-key changes for the agent to apply, after `content reopen` for approved files.

`fixtures/review-u02-answers.json` adjudicates the three answers the beta fixture (`fixtures/beta/events.jsonl`)
rejected in Unit 2: accept *il cornetto* (u02.l1.ex04), *vorrei cappuccino* as a near-miss in u02.task.conv1/n1,
and *una cornetto* is wrong.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from itcontent import approval, patterns, yamlio
from itcontent.adjudication import (
    ApplyError,
    Proposal,
    add_alternative,
    apply_proposal,
    escape_literal,
    propose,
)
from itcontent.beta import run_beta_import
from itcontent.course import load_course
from itcontent.lint import lint_findings
from itcontent.review_export import export
from itcontent.review_import import import_review, worklist

LESSON = "content/units/02-al-bar/lesson-1.yaml"
TASK = "content/units/02-al-bar/task.yaml"


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def human(confirm: str = "lesson-1.yaml") -> dict[str, Any]:
    return {"env": {}, "stdin": Tty(), "ask": lambda _p: confirm, "echo": lambda _m: None}


@pytest.fixture
def rejected(fixtures_dir: Path, tmp_path: Path) -> Path:
    run_beta_import(fixtures_dir / "beta" / "events.jsonl", tmp_path / "beta")
    return tmp_path / "beta" / "rejected.json"


# ---------------------------------------------------------------- patterns


@pytest.mark.parametrize(
    ("pattern", "answer", "new"),
    [
        ("un [cornetto]", "il cornetto", "{un [cornetto]|il cornetto}"),
        ("{quant'è|quanto è}", "quanto viene", "{quant'è|quanto è|quanto viene}"),
        ("{vorrei|io vorrei} un caffè", "prendo un caffè", "{{vorrei|io vorrei} un caffè|prendo un caffè}"),
        ("{m:americano|f:americana}", "statunitense", "{{m:americano|f:americana}|statunitense}"),
        ("{NAME}", "boh", "{{NAME}|boh}"),
        ("e tu", "a|b (c) [d] \\e", r"{e tu|a\|b \(c\) \[d\] \\e}"),
    ],
)
def test_add_alternative_keeps_the_model_answer(pattern, answer, new):
    assert add_alternative(pattern, answer) == new
    assert patterns.model_answer(new) == patterns.model_answer(pattern)  # the model answer stays
    assert answer.casefold() in {e.raw.casefold() for e in patterns.expand(new)}


def test_escape_literal():
    assert escape_literal("quant'è") == "quant'è"
    assert escape_literal("{x}") == r"\{x\}"


# ---------------------------------------------------------------- the page


def test_rejected_answers_appear_on_the_next_review_page(course_copy, rejected, tmp_path):
    result = export("u02", root=course_copy, rejected=rejected, out=tmp_path / "u02.html")
    section = result.model.sections[0]
    assert section.title == "Answers to adjudicate"
    adj = {(e.target, e.meta["response"]): e for e in section.elements}
    assert set(adj) == {
        ("u02.l1.ex04", "una cornetto"),
        ("u02.l1.ex04", "il cornetto"),
        ("u02.task.conv1/n1", "vorrei cappuccino"),
    }  # pl.01 belongs to the placement test, not to Unit 2
    first = section.elements[0]
    assert (first.target, first.meta["count"]) == ("u02.l1.ex04", 3)  # most frequent first
    assert "rejected 3×" in first.body and "un [cornetto]" in first.body and "Cornetto is masculine." in first.body
    node = adj[("u02.task.conv1/n1", "vorrei cappuccino")]
    assert node.file == TASK and "order-drink" in node.body and "intents" not in node.meta  # one intent: no choice
    html = result.path.read_text(encoding="utf-8")
    assert "Answers to adjudicate" in html and '"adj":{"count":1,"response":"il cornetto"}' in html
    assert "3 answer(s) to adjudicate" in result.summary(course_copy)
    assert export("assessments", root=course_copy, rejected=rejected, out=tmp_path / "a.html").adjudications == 0


def test_adjudicated_answers_do_not_come_back(course_copy, rejected, fixtures_dir, tmp_path):
    import_review(fixtures_dir / "review-u02-answers.json", root=course_copy)
    result = export("u02", root=course_copy, rejected=rejected, out=tmp_path / "u02.html")
    assert result.adjudications == 0 and result.model.sections[0].title != "Answers to adjudicate"


# ---------------------------------------------------------------- import: verdicts become proposals


def test_import_turns_verdicts_into_proposals(course_copy, fixtures_dir):
    result = import_review(fixtures_dir / "review-u02-answers.json", root=course_copy)
    statuses = [e["resolution"]["status"] for e in result.added]
    assert statuses == ["open", "open", "noted"]  # "wrong" keeps the key as it is: nothing to do
    props = {p.target: p for p in result.proposals}
    assert set(props) == {"u02.l1.ex04", "u02.task.conv1/n1"}
    accept = props["u02.l1.ex04"]
    assert (accept.action, accept.file, accept.path[-1]) == ("replace", LESSON, "answer")
    assert (accept.old, accept.new) == ("un [cornetto]", "{un [cornetto]|il cornetto}")
    line = (course_copy / LESSON).read_text(encoding="utf-8").split("\n")[accept.line - 1]
    assert line.strip() == 'answer: "un [cornetto]"'
    near = props["u02.task.conv1/n1"]
    assert (near.action, near.file, near.path[-3:], near.old) == ("add-near", TASK, ["nodes", "n1", "near"], None)
    assert near.new == [
        {"answer": "vorrei cappuccino", "hint": "Don't forget the article: un cappuccino.", "outcome": "almost"}
    ]
    report = (course_copy / "build" / "reports" / "review" / "u02-answers.md").read_text(encoding="utf-8")
    assert "## `u02.l1.ex04`: accept *il cornetto*" in report
    assert '- with: `"{un [cornetto]|il cornetto}"`' in report
    assert "steps[3].block[3].answer" in report
    blob = json.loads((course_copy / "build" / "reports" / "review" / "u02-answers.json").read_text(encoding="utf-8"))
    assert [p["target"] for p in blob] == ["u02.l1.ex04", "u02.task.conv1/n1"]
    assert any("answer key: 2 change(s) to apply" in ln for ln in worklist(result, course_copy))


def test_this_should_be_accepted_from_the_app_is_an_accept(course_copy, fixtures_dir):
    result = import_review(fixtures_dir / "review-u02.json", root=course_copy)
    (p,) = result.proposals
    assert (p.target, p.decision, p.action) == ("u02.l1.ex07", "accept", "replace")
    assert p.new == "{quant'è|quanto è|quanto costa|scusi quant'è|scusi quanto costa|quanto viene}"


def _entry(target: str, response: str, **adj: Any) -> dict[str, Any]:
    return {
        "id": f"t-{target}-{response}",
        "target": target,
        "file": LESSON,
        "verdict": "change",
        "category": "answer-key",
        "response": response,
        "adjudication": {"decision": "accept", **adj},
        "resolution": {"status": "open"},
    }


def test_proposals_per_format(course_copy):
    course = load_course(course_copy)
    cloze = propose(course, _entry("u02.l1.ex01", "uno"))
    assert cloze and (cloze.action, cloze.new) == ("replace", "Vorrei [[{un|uno}]] cappuccino, per favore.")
    two_intents = propose(course, _entry("u02.task.conv1/n2", "niente grazie"))
    assert two_intents and two_intents.action == "manual" and "choose the intent" in two_intents.note
    chosen = propose(course, _entry("u02.task.conv1/n2", "niente grazie", intent="nothing-to-eat"))
    assert chosen and (chosen.action, chosen.new) == ("append", ["no grazie", "niente grazie"])
    assert chosen.path[-4:] == ["n2", "expect", 1, "accept"]
    known = propose(course, _entry("u02.l1.ex07", "Quanto costa"))
    assert known and (known.action, known.note) == ("none", "already an alternative")
    near = propose(course, _entry("u02.l1.ex05", "il caffè", decision="near", hint="Un, not il, for 'a'."))
    assert near and near.action == "add-near" and near.new[-1] == {"answer": "il caffè", "hint": "Un, not il, for 'a'."}
    assert len(near.new) == 2  # appended to the existing near-misses
    dup = propose(course, _entry("u02.l1.ex05", "una caffè", decision="near"))
    assert dup and (dup.action, dup.note) == ("none", "already a near-miss")
    dictation = propose(course, _entry("u02.l1.ex13", "vorrei un cornetto per favore"))
    assert dictation and dictation.action == "manual" and "no answer pattern" in dictation.note
    gone = propose(course, _entry("u02.l1.ex99", "x"))
    assert gone and gone.action == "manual" and gone.note == "the exercise no longer exists"
    assert propose(course, _entry("u02.l1.ex04", "una cornetto", decision="wrong")) is None


# ---------------------------------------------------------------- the acceptance criterion


def test_an_adjudication_adds_the_accepted_answer_after_content_reopen(course_copy, fixtures_dir):
    """The beta unit is approved; the teacher accepts *il cornetto*; the change waits for the owner's reopen."""
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, **human()) == 0
    result = import_review(fixtures_dir / "review-u02-answers.json", root=course_copy)
    proposal = next(p for p in result.proposals if p.target == "u02.l1.ex04")
    assert proposal.approved
    report = (course_copy / "build" / "reports" / "review" / "u02-answers.md").read_text(encoding="utf-8")
    assert "accept *il cornetto* **approved: needs content reopen**" in report
    before = (course_copy / LESSON).read_bytes()
    with pytest.raises(ApplyError, match="is approved: the owner runs content reopen first"):
        apply_proposal(course_copy, proposal)
    assert (course_copy / LESSON).read_bytes() == before

    assert approval.reopen(Path(LESSON), root=course_copy, **human()) == 0  # the owner, at a terminal
    apply_proposal(course_copy, proposal)
    ex04 = yamlio.load(course_copy / LESSON)["steps"][3]["block"][3]
    assert ex04["id"] == "u02.l1.ex04" and ex04["answer"] == "{un [cornetto]|il cornetto}"
    assert patterns.model_answer(ex04["answer"]).text == "un cornetto"  # the model answer stays
    assert [e.text for e in patterns.expand(ex04["answer"])] == ["un cornetto", "il cornetto"]
    assert [str(f) for f in lint_findings(course_copy) if f.level == "error"] == []
    again = import_review(fixtures_dir / "review-u02-answers.json", root=course_copy)  # idempotent re-import
    assert again.added == []
    redo = next(p for p in again.proposals if p.target == "u02.l1.ex04")
    assert (redo.action, redo.note) == ("none", "already an alternative")


def test_apply_refuses_what_it_cannot_do_safely(course_copy):
    p = Proposal("c", "u02.l1.ex04", LESSON, ["steps", 3, "block", 3, "answer"], 1, "append", "accept", "x")
    with pytest.raises(ApplyError, match="only replace proposals apply mechanically"):
        apply_proposal(course_copy, p)
    stale = Proposal("c", "u02.l1.ex04", LESSON, ["steps", 3, "block", 3, "answer"], 129, "replace", "accept", "x")
    stale.old, stale.new = "un [croissant]", "{un [croissant]|x}"
    with pytest.raises(ApplyError):
        apply_proposal(course_copy, stale)
