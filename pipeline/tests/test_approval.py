"""M1.2: the approval hash, `content approve` / `content reopen`, and lint catching edits to approved files.

Everything runs on a copy of the course (never on the seeds). The refusals are tested through direct calls and
typer's CliRunner, never by running the command in a shell.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
from pathlib import Path

import pytest
from typer.testing import CliRunner

from itcontent import approval, paths
from itcontent.approval import approval_hash, file_hash, set_review, strip_review
from itcontent.cli import app
from itcontent.lint import lint_findings

LESSON = "content/units/02-al-bar/lesson-1.yaml"
TODAY = dt.date(2026, 10, 7)


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def human(**kw):
    """Keyword arguments for a person at a terminal who types the file name to confirm."""
    name = kw.pop("confirm", "lesson-1.yaml")
    return {"env": {}, "stdin": Tty(), "ask": lambda _prompt: name, "echo": kw.pop("echo", lambda _m: None), **kw}


# ---------------------------------------------------------------- the hash (docs/04 § Approval hash)


def test_hash_ignores_the_review_entry_and_line_endings():
    flow = b"id: x\nreview: {status: draft, by: null, date: null, hash: null}\nsteps: []\n"
    block = b'id: x\nreview:\n  status: approved\n  by: "A"\n  date: "2026-10-07"\n  hash: "ab"\nsteps: []\n'
    crlf = flow.replace(b"\n", b"\r\n")
    assert strip_review(flow) == b"id: x\nsteps: []\n"
    assert approval_hash(flow) == approval_hash(block) == approval_hash(crlf)
    assert approval_hash(flow) == hashlib.sha256(b"id: x\nsteps: []\n").hexdigest()
    assert approval_hash(flow) != approval_hash(flow.replace(b"steps: []", b"steps: [ ]"))


def test_hash_keeps_comments_and_blank_lines_that_follow_the_entry():
    text = b"review:\n  status: draft\n\n# a comment between keys\n  by: null\n\n# about steps\nsteps: []\n"
    assert strip_review(text) == b"\n# about steps\nsteps: []\n"
    nested = b"id: x\nnotes:\n  review: keep me\nreview: {status: draft}\n"
    assert strip_review(nested) == b"id: x\nnotes:\n  review: keep me\n"
    assert strip_review(b"id: x\n") == b"id: x\n"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            b"# head\nid: x\nreview: {status: draft, by: null, date: null, hash: null}   # c\nsteps: []\n",
            b'# head\nid: x\nreview: {status: approved, by: "A B", date: "2026-10-07", hash: "h"}\nsteps: []\n',
        ),
        (
            b"id: x\nreview:\n    status: draft\n    by: null\nsteps: []\n",
            b'id: x\nreview:\n    status: approved\n    by: "A B"\n    date: "2026-10-07"\n    hash: "h"\nsteps: []\n',
        ),
        (
            b"id: x\r\nreview: {status: draft}\r\nsteps: []\r\n",
            b'id: x\r\nreview: {status: approved, by: "A B", date: "2026-10-07", hash: "h"}\r\nsteps: []\r\n',
        ),
        (
            b"id: x\nreview: {status: draft}",
            b'id: x\nreview: {status: approved, by: "A B", date: "2026-10-07", hash: "h"}',
        ),
    ],
)
def test_set_review_rewrites_only_the_review_entry(tmp_path, before, after):
    p = tmp_path / "f.yaml"
    p.write_bytes(before)
    set_review(p, {"status": "approved", "by": "A B", "date": "2026-10-07", "hash": "h"})
    assert p.read_bytes() == after


# ---------------------------------------------------------------- approve, edit, lint


def test_approve_then_edit_makes_lint_fail(course_copy):
    path = course_copy / LESSON
    before = path.read_bytes()
    messages: list[str] = []
    rc = approval.approve(
        Path(LESSON), "Maria Rossi", root=course_copy, today=lambda: TODAY, **human(echo=messages.append)
    )
    assert rc == 0, messages
    after = path.read_bytes()
    digest = file_hash(path)
    assert messages == [f"approved {LESSON}: by Maria Rossi, 2026-10-07, hash {digest}"]
    assert approval.read_review(path) == {
        "status": "approved",
        "by": "Maria Rossi",
        "date": "2026-10-07",
        "hash": digest,
    }
    assert strip_review(after) == strip_review(before)  # every other byte is kept
    assert digest == approval_hash(before)
    assert [f for f in lint_findings(course_copy) if f.level == "error"] == []

    path.write_bytes(after.replace(b"Si chiama Aurora.", b"Si chiama Aurora!"))
    errors = [str(f) for f in lint_findings(course_copy) if f.level == "error"]
    assert errors == [
        f"error: {LESSON} › review.hash (line 8): the file changed after approval: review.hash is {digest[:12]}…, "
        f"the file now hashes to {file_hash(path)[:12]}… (docs/04 § Approval hash). Approved content changes only "
        "after the owner runs content reopen"
    ]


def test_reopen_clears_the_approval(course_copy):
    path = course_copy / LESSON
    assert approval.approve(path, "Maria Rossi", root=course_copy, today=lambda: TODAY, **human()) == 0
    assert approval.reopen(path, root=course_copy, **human()) == 0
    assert approval.read_review(path) == {"status": "in-review", "by": None, "date": None, "hash": None}
    assert b"review: {status: in-review, by: null, date: null, hash: null}\n" in path.read_bytes()
    assert [f for f in lint_findings(course_copy) if f.level == "error"] == []


def test_approve_accepts_the_repo_path_as_confirmation(course_copy):
    rc = approval.approve(Path(LESSON), "M", root=course_copy, today=lambda: TODAY, **human(confirm=LESSON))
    assert rc == 0


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        (
            {"env": {"CLAUDECODE": "1"}},
            "refused: CLAUDECODE is set, so this is an agent's shell. Only the owner approves or reopens content "
            "(ADR-15); ask them to run the command in their own terminal.",
        ),
        (
            {"stdin": io.StringIO()},
            "refused: stdin is not a terminal. Approving and reopening content is for a person at a terminal (ADR-15).",
        ),
        ({"confirm": "lesson-2.yaml"}, "not confirmed; nothing changed"),
        (
            {"signoff": Path("reviews/inbox/review-u02.json")},
            f"{LESSON}: the sign-off doesn't allow approval (1 problem(s))",  # no such file (test_review_import)
        ),
    ],
)
def test_approve_refuses(course_copy, kw, message):
    path = course_copy / LESSON
    before = path.read_bytes()
    messages: list[str] = []
    args = human(echo=messages.append, **{k: v for k, v in kw.items() if k == "confirm"})
    args.update({k: v for k, v in kw.items() if k != "confirm"})
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, **args) == 1
    assert messages[-1] == message
    assert path.read_bytes() == before


def test_reopen_refuses_in_an_agent_shell(course_copy):
    messages: list[str] = []
    rc = approval.reopen(Path(LESSON), root=course_copy, **{**human(echo=messages.append), "env": {"CLAUDECODE": ""}})
    assert rc == 1 and messages[0].startswith("refused: CLAUDECODE is set")


def test_approve_refuses_a_file_that_fails_lint(course_copy):
    path = course_copy / LESSON
    path.write_text(path.read_text(encoding="utf-8").replace('prompt_en: "a coffee"', 'prompt_eng: "a coffee"'))
    messages: list[str] = []
    assert approval.approve(Path(LESSON), "M", root=course_copy, **human(echo=messages.append)) == 1
    assert messages[-1] == f"{LESSON} fails lint (2 error(s)); fix them before approving"
    assert any("unknown key 'prompt_eng'" in m for m in messages)
    assert approval.read_review(path)["status"] == "draft"


def test_approve_refuses_files_without_review_and_approved_files(course_copy):
    messages: list[str] = []
    rc = approval.approve(Path("content/grammar/detection.yaml"), "M", root=course_copy, **human(echo=messages.append))
    assert rc == 1 and messages[-1].endswith("has no review: entry, so it isn't approved content (docs/03)")
    assert approval.approve(Path(LESSON), "M", root=course_copy, today=lambda: TODAY, **human()) == 0
    assert approval.approve(Path(LESSON), "N", root=course_copy, **human(echo=messages.append)) == 1
    assert messages[-1] == f"{LESSON} is already approved (by M, 2026-10-07); reopen it first"
    rc = approval.approve(Path("pipeline/pyproject.toml"), "M", root=course_copy, **human(echo=messages.append))
    assert rc == 1


# ---------------------------------------------------------------- the CLI (it refuses an agent's shell)


def test_cli_approve_refuses_with_claudecode(course_copy):
    path = course_copy / LESSON
    before = path.read_bytes()
    result = CliRunner().invoke(app, ["approve", str(path), "--by", "Maria Rossi"], env={"CLAUDECODE": "1"})
    assert result.exit_code != 0
    assert "refused: CLAUDECODE is set" in result.output
    assert path.read_bytes() == before


def test_cli_approve_and_reopen_refuse_without_a_tty(course_copy):
    for args in (["approve", str(course_copy / LESSON), "--by", "M"], ["reopen", str(course_copy / LESSON)]):
        result = CliRunner().invoke(app, args, env={"CLAUDECODE": None})  # CliRunner's stdin is not a terminal
        assert result.exit_code == 1
        assert "refused: stdin is not a terminal" in result.output


def test_cli_approve_signoff_needs_a_review_file(course_copy, monkeypatch):
    monkeypatch.setattr(approval, "agent_refusal", lambda *_a, **_k: None)
    monkeypatch.setattr(paths, "ROOT", course_copy)
    result = CliRunner().invoke(app, ["approve", str(course_copy / LESSON), "--by", "M", "--signoff", "x.json"])
    assert result.exit_code == 1
    assert "x.json: no such review file" in result.output
    assert approval.read_review(course_copy / LESSON)["status"] == "draft"


def test_cli_approve_for_a_person_at_a_terminal(course_copy, monkeypatch):
    monkeypatch.setattr(approval, "agent_refusal", lambda *_a, **_k: None)
    monkeypatch.setattr(approval, "clock", lambda: TODAY)
    monkeypatch.setattr(paths, "ROOT", course_copy)
    path = course_copy / LESSON
    result = CliRunner().invoke(app, ["approve", str(path), "--by", "Maria Rossi"], input="lesson-1.yaml\n")
    assert result.exit_code == 0, result.output
    assert f'Approve as reviewed by "Maria Rossi": {LESSON}? Type the file name (lesson-1.yaml) to confirm' in (
        result.output
    )
    assert approval.read_review(path)["status"] == "approved"
    result = CliRunner().invoke(app, ["reopen", str(path)], input="lesson-1.yaml\n")
    assert result.exit_code == 0, result.output
    assert approval.read_review(path)["status"] == "in-review"
