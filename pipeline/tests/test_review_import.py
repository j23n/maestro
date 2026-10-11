"""M1.13: `content review-import`, the ledger `reviews/<scope>.yaml`, `review-export --since`, open comments in
`content report`, and `content approve --signoff` (docs/04 § Content review loop › Back into the project).

`fixtures/review-u02.json` is a page review of Unit 2 by the content lead: comments on real IDs of
`content/units/02-al-bar/` (a story line, an exercise, a conversation node, an item, the note, a check exercise)
and one on the unit spec. Its `files` hashes are those of the seed files when it was written; tests that need the
current hashes compute them. Everything runs on a copy of the course.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from itcontent import approval, paths, schemas, yamlio
from itcontent.annotate import run_annotate
from itcontent.cli import app
from itcontent.course import load_course
from itcontent.ledger import _yaml, report_lines, signoff_problems
from itcontent.lint import lint_findings
from itcontent.review import version_hash
from itcontent.review_elements import Context, build_page
from itcontent.review_export import export
from itcontent.review_import import ReviewImportError, import_review, run, worklist

LESSON = "content/units/02-al-bar/lesson-1.yaml"
TASK = "content/units/02-al-bar/task.yaml"
LEDGER = "reviews/u02.yaml"


def load(fixtures_dir: Path, name: str = "review-u02.json") -> dict[str, Any]:
    return json.loads((fixtures_dir / name).read_text(encoding="utf-8"))


def write(tmp: Path, data: dict[str, Any], name: str = "review-u02-2026-10-20.json") -> Path:
    path = tmp / "downloads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def current(root: Path, data: dict[str, Any]) -> dict[str, Any]:
    """The review as if made on the current files (hashes and element fingerprints)."""
    model = build_page(Context.build(load_course(root)), data["scope"])
    return {**data, "files": dict(model.files), "elements": {e.target: e.fp for e in model.elements() if e.fp}}


def errors(root: Path) -> list[str]:
    return [str(f) for f in lint_findings(root) if f.level == "error"]


def ledger(root: Path) -> list[dict[str, Any]]:
    return yamlio.load(root / LEDGER)["comments"]


def resolve(root: Path, comment_id: str, status: str, note: str | None = None, commit: str | None = None) -> None:
    """What an agent does in the ledger (docs/04 § Back into the project, step 2)."""
    y = _yaml()
    doc = y.load((root / LEDGER).read_text(encoding="utf-8"))
    entry = next(c for c in doc["comments"] if c["id"] == comment_id)
    entry["resolution"]["status"], entry["resolution"]["note"], entry["resolution"]["commit"] = status, note, commit
    buf = io.StringIO()
    y.dump(doc, buf)
    (root / LEDGER).write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------- import


def test_import_creates_the_ledger(course_copy, fixtures_dir):
    source = fixtures_dir / "review-u02.json"
    data = load(fixtures_dir)
    result = import_review(source, root=course_copy)
    assert result.inbox == "reviews/inbox/review-u02.json"
    assert (course_copy / result.inbox).read_bytes() == source.read_bytes()  # filed unchanged
    entries = ledger(course_copy)
    assert [e["id"] for e in entries] == [c["id"] for c in data["comments"]]
    for entry, c in zip(entries, data["comments"], strict=True):
        assert {k: entry[k] for k in c} == c  # every field as filed
        assert entry["review"] == "reviews/inbox/review-u02.json" and entry["reviewer"] == "Maria Rossi"
        seen = data["files"].get(c["file"])
        assert entry["hash"] == seen
        assert entry["stale"] == (seen is not None and seen != version_hash(course_copy, c["file"]))
    statuses = {e["target"]: e["resolution"]["status"] for e in entries}
    assert statuses == {
        "u02.l1.story#3": "open",
        "u02.l1.ex07": "open",
        "u02.task.conv1/n2": "open",
        "w:cornetto": "noted",  # an OK verdict with nothing to act on
        "u02.l1.note": "open",
        "u02.check.05": "open",  # OK, but with a comment: someone answers it
        "cd:order-food-drink": "open",
    }
    assert all(e["resolution"]["note"] is None and e["resolution"]["commit"] is None for e in entries)
    assert errors(course_copy) == []  # the ledger and the inbox copy pass lint
    lines = worklist(result, course_copy)
    assert lines[0] == (
        "filed reviews/inbox/review-u02.json; 7 comment(s) added to reviews/u02.yaml (6 to do, 1 marked OK)"
    )
    assert any("content/units/02-al-bar/unit.yaml is outside scope u02" in ln for ln in lines)
    assert any(ln.startswith("  - u02.l1.story#3 [Change · Unnatural]") for ln in lines)
    assert any("[answer: quanto viene]" in ln for ln in lines)


def test_the_apps_review_files_import(course_copy, fixtures_dir):
    """M6.10: `review-app-*.json` are what the app's review mode exports (written by `ReviewModeTests` in
    App/ItalianoTests, which checks its output against them): "This should be accepted" and a comment on
    u02.l1.ex07, a suggestion on a story line, and an OK on the unit's opener. They import as they are, one scope
    per file, and the accept request becomes an answer-key proposal."""
    results = {}
    for name in ("review-app-u02.json", "review-app-specs.json"):
        source = fixtures_dir / name
        data = json.loads(source.read_text(encoding="utf-8"))
        assert schemas.validate("review-file", data) == []
        assert data["channel"] == "app" and data["signoff"] is None
        result = import_review(source, root=course_copy)
        assert result.warnings == []  # every comment is in its file's scope
        assert [e["id"] for e in result.added] == [c["id"] for c in data["comments"]]
        assert all(e["reviewer"] == "Maria Rossi" for e in result.added)
        results[data["scope"]] = result
    u02 = [(e["target"], e["category"], e["resolution"]["status"]) for e in ledger(course_copy)]
    assert u02 == [
        ("u02.l1.ex07", "answer-key", "open"),
        ("u02.l1.ex07", "level", "open"),
        ("u02.l1.story#3", "naturalness", "open"),
    ]
    specs = yamlio.load(course_copy / "reviews" / "specs.yaml")["comments"]
    assert [(c["target"], c["file"], c["resolution"]["status"]) for c in specs] == [
        ("u02.step-opener", "content/units/02-al-bar/unit.yaml", "noted")
    ]
    accept = next(p for p in results["u02"].proposals if p.target == "u02.l1.ex07")
    assert (accept.decision, accept.action, accept.answer) == ("accept", "replace", "quanto fa")
    assert accept.new.startswith("{quant'è|") and accept.new.endswith("|quanto fa}")
    assert errors(course_copy) == []  # the ledgers and the inbox copies pass lint


def test_reimport_is_a_no_op(course_copy, fixtures_dir):
    import_review(fixtures_dir / "review-u02.json", root=course_copy)
    before = (course_copy / LEDGER).read_text(encoding="utf-8")
    again = import_review(fixtures_dir / "review-u02.json", root=course_copy)
    assert again.added == [] and len(again.skipped) == 7
    assert (course_copy / LEDGER).read_text(encoding="utf-8") == before
    assert sorted(p.name for p in (course_copy / "reviews" / "inbox").iterdir()) == ["review-u02.json"]


def test_a_second_review_appends_and_keeps_its_own_name(course_copy, fixtures_dir, tmp_path):
    import_review(fixtures_dir / "review-u02.json", root=course_copy)
    data = load(fixtures_dir)
    data["comments"] = [{**data["comments"][0], "id": "second-1", "comment": "Still stiff."}]
    result = import_review(write(tmp_path, data, "review-u02.json"), root=course_copy)  # same name, other bytes
    assert result.inbox == "reviews/inbox/review-u02-2.json"
    assert [e["id"] for e in ledger(course_copy)][-1] == "second-1"
    assert ledger(course_copy)[-1]["review"] == "reviews/inbox/review-u02-2.json"


def test_stale_comments_are_flagged(course_copy, fixtures_dir, tmp_path):
    data = current(course_copy, load(fixtures_dir))
    path = course_copy / LESSON
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Buongiorno. Vorrei un cappuccino", "Buongiorno! Vorrei un cappuccino"
        ),
        encoding="utf-8",
    )
    result = import_review(write(tmp_path, data), root=course_copy)
    stale = {e["target"]: e["stale"] for e in ledger(course_copy)}
    assert stale["u02.l1.story#3"] and stale["u02.l1.ex07"] and stale["u02.l1.note"]  # made on the older lesson
    assert not stale["u02.task.conv1/n2"] and not stale["w:cornetto"]
    assert not stale["cd:order-food-drink"]  # the page didn't show unit.yaml: no hash, so never stale
    lines = worklist(result, course_copy)
    story = next(ln for ln in lines if "u02.l1.story#3" in ln)
    assert "stale: the file changed since; so did this element" in story
    ex07 = next(ln for ln in lines if "u02.l1.ex07" in ln)
    assert "stale: the file changed since)" in ex07  # the exercise itself didn't change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["comments"][1].update(target="u02.l1.ex99"),
            "comments[1] (5e1d0c2a-7b3f-4c1e-9a6d-000000000002): unknown target 'u02.l1.ex99'",
        ),
        (
            lambda d: d["comments"][0].update(target="u02.l1.story#99"),
            "text u02.l1.story has 22 lines; there is no line 99",
        ),
        (lambda d: d["comments"][2].update(target="u02.task.conv1/n9"), "conversation u02.task.conv1 has no node 'n9'"),
        (
            lambda d: d["comments"][6].update(target="u02.can_do[9]"),
            "unknown target 'u02.can_do[9]' in content/units/02-al-bar/unit.yaml",
        ),
        (
            lambda d: d["comments"][0].update(file="content/units/02-al-bar/lesson-9.yaml"),
            "lesson-9.yaml doesn't exist",
        ),
    ],
)
def test_unknown_targets_import_nothing(course_copy, fixtures_dir, tmp_path, change, message):
    data = load(fixtures_dir)
    change(data)
    with pytest.raises(ReviewImportError) as exc:
        import_review(write(tmp_path, data), root=course_copy)
    assert message in str(exc.value) and "nothing was imported" in str(exc.value)
    assert not (course_copy / "reviews" / "inbox").exists() and not (course_copy / LEDGER).exists()


def test_malformed_files_import_nothing(course_copy, fixtures_dir, tmp_path):
    bad = tmp_path / "review.json"
    bad.write_text("{not json", encoding="utf-8")
    messages: list[str] = []
    assert run(bad, root=course_copy, echo=messages.append) == 1
    assert messages[0].startswith("error: ") and "not a review file" in messages[0]
    data = load(fixtures_dir)
    data["comments"][0]["verdict"] = "maybe"
    data["scope"] = "unit2"
    with pytest.raises(ReviewImportError) as exc:
        import_review(write(tmp_path, data), root=course_copy)
    assert "comments.0.verdict: 'maybe' is not a valid verdict (allowed: ok, change, question)" in str(exc.value)
    assert "scope: 'unit2' is not a review scope (specs, assessments or uNN)" in str(exc.value)
    data = load(fixtures_dir)
    data["scope"] = "u42"
    with pytest.raises(ReviewImportError, match="scope u42 is not a unit"):
        import_review(write(tmp_path, data), root=course_copy)
    assert not (course_copy / "reviews").exists()


def test_cli_review_import(course_copy, fixtures_dir, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", course_copy)
    result = CliRunner().invoke(app, ["review-import", str(fixtures_dir / "review-u02.json")])
    assert result.exit_code == 0, result.output
    assert "7 comment(s) added to reviews/u02.yaml" in result.output
    result = CliRunner().invoke(app, ["review-import", str(fixtures_dir / "nope.json")])
    assert result.exit_code == 1 and "no such file" in result.output


# ---------------------------------------------------------------- --since


def test_since_shows_resolutions_and_change_marks(course_copy, fixtures_dir, tmp_path):
    import_review(write(tmp_path, current(course_copy, load(fixtures_dir))), root=course_copy)
    resolve(course_copy, "5e1d0c2a-7b3f-4c1e-9a6d-000000000001", "fixed", "Now «Buongiorno! Un cappuccino».", "1a2b3c4")
    resolve(course_copy, "5e1d0c2a-7b3f-4c1e-9a6d-000000000005", "declined", "Keep the <b>friendly</b> tone.")
    assert errors(course_copy) == []
    path = course_copy / LESSON
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"Buongiorno. Vorrei un cappuccino, per favore."', '"Buongiorno! Un cappuccino, per favore."'
        ),
        encoding="utf-8",
    )
    result = export("u02", root=course_copy, since=True, out=tmp_path / "since.html")
    html = result.path.read_text(encoding="utf-8")
    assert result.since is not None
    assert result.since.marks == {"u02.l1.story#3": "changed"}  # only what changed since the teacher saw it
    assert 'class="el depth-2 kind-line changed"' in html and '<span class="mark">changed</span>' in html
    assert "Keep the &lt;b&gt;friendly&lt;/b&gt; tone." in html  # the ledger's text is escaped, never raw HTML
    assert "Now «Buongiorno! Un cappuccino». <code>1a2b3c4</code>" in html
    assert '<span class="tag">Fixed</span>' in html and '<span class="tag">Declined</span>' in html
    assert 'data-reopens="5e1d0c2a-7b3f-4c1e-9a6d-000000000001">Reopen</button>' in html
    assert "Marked OK (Maria Rossi, 2026-10-20)" in html  # w:cornetto, noted
    data = json.loads(html.split('id="review-data">', 1)[1].split("</script>", 1)[0])
    assert data["since"] is True
    still_open = {d["target"] for d in data["open"]}  # these block the teacher's sign-off
    assert still_open == {"u02.l1.ex07", "u02.task.conv1/n2", "u02.check.05"}
    assert "changed since my last review" in html
    assert "since: 1 changed, 0 new, 6 earlier comment(s)" in result.summary(course_copy)  # cd: is on the specs page
    assert "elements that are gone" not in html


def test_since_marks_new_elements(course_copy, fixtures_dir, tmp_path):
    data = current(course_copy, load(fixtures_dir))
    data["elements"].pop("u02.l1.ex26")
    import_review(write(tmp_path, data), root=course_copy)
    result = export("u02", root=course_copy, since=True, out=tmp_path / "since.html")
    assert result.since is not None and result.since.marks == {"u02.l1.ex26": "new"}


# ---------------------------------------------------------------- content report


def test_report_lists_open_comments(course_copy, fixtures_dir, monkeypatch):
    assert report_lines(course_copy) == ["## Open review comments", "", "No open review comments."]
    import_review(fixtures_dir / "review-u02.json", root=course_copy)
    resolve(course_copy, "5e1d0c2a-7b3f-4c1e-9a6d-000000000003", "owner", "Register decision: ask the owner.")
    lines = report_lines(course_copy)
    assert lines[2] == "6 open comment(s) (status open or owner) in reviews/*.yaml."
    assert "### u02 (5)" in lines and "### specs (1)" in lines
    assert any(ln.startswith("- `u02.task.conv1/n2` Question · Hint or rule **owner**:") for ln in lines)
    assert not any("w:cornetto" in ln for ln in lines)
    assert "### specs (1)" not in report_lines(course_copy, "u02")
    monkeypatch.setattr(paths, "ROOT", course_copy)
    result = CliRunner().invoke(app, ["report", "--unit", "specs"])
    assert result.exit_code == 0 and "`cd:order-food-drink` Question · Level" in result.output


# ---------------------------------------------------------------- content approve --signoff


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def human(messages: list[str], confirm: str = "lesson-1.yaml") -> dict[str, Any]:
    return {"env": {}, "stdin": Tty(), "ask": lambda _p: confirm, "echo": messages.append}


def signed_review(
    root: Path, name: str = "Maria Rossi", comments: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    model = build_page(Context.build(load_course(root)), "u02")
    return {
        "format": 1,
        "reviewer": name,
        "channel": "page",
        "scope": "u02",
        "created": "2026-10-27T10:00:00Z",
        "files": dict(model.files),
        "elements": {e.target: e.fp for e in model.elements() if e.fp},
        "comments": comments or [],
        "signoff": {"name": name, "at": "2026-10-27T10:05:00Z", "files": dict(model.files)},
    }


def file_signoff(root: Path, tmp: Path, data: dict[str, Any], name: str = "review-u02-2026-10-27.json") -> Path:
    import_review(write(tmp, data, name), root=root)
    return Path("reviews/inbox") / name


def test_approve_with_a_signoff(course_copy, tmp_path):
    signoff = file_signoff(course_copy, tmp_path, signed_review(course_copy))
    messages: list[str] = []
    rc = approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages))
    assert rc == 0, messages
    review = approval.read_review(course_copy / LESSON)
    assert review["status"] == "approved" and review["hash"] == signed_review(course_copy)["files"][LESSON]


def test_approving_with_a_stale_signoff_fails(course_copy, tmp_path):
    signoff = file_signoff(course_copy, tmp_path, signed_review(course_copy))
    signed_hash = version_hash(course_copy, LESSON)
    path = course_copy / LESSON
    path.write_text(
        path.read_text(encoding="utf-8").replace("Si chiama Aurora.", "Si chiama Aurora!"), encoding="utf-8"
    )
    before = path.read_bytes()
    messages: list[str] = []
    rc = approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages))
    assert rc == 1
    assert messages == [
        f"stale sign-off: Maria Rossi signed {LESSON} at hash {signed_hash[:12]}…, but the file now hashes to "
        f"{version_hash(course_copy, LESSON)[:12]}…; export the review page again and ask for a new sign-off",
        f"{LESSON}: the sign-off doesn't allow approval (1 problem(s))",
    ]
    assert path.read_bytes() == before


def test_approving_with_open_comments_fails(course_copy, fixtures_dir, tmp_path):
    import_review(fixtures_dir / "review-u02.json", root=course_copy)
    signoff = file_signoff(course_copy, tmp_path, signed_review(course_copy))
    messages: list[str] = []
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages)) == 1
    assert messages[0].startswith(
        f"3 comment(s) on {LESSON} are still open: 5e1d0c2a-7b3f-4c1e-9a6d-000000000001 (open"
    )
    # Owner comments block approval too; noted, fixed, answered and declined ones don't.
    for n, status in (("1", "fixed"), ("2", "answered"), ("5", "owner")):
        resolve(course_copy, f"5e1d0c2a-7b3f-4c1e-9a6d-00000000000{n}", status, None if status == "fixed" else "…")
    messages.clear()
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages)) == 1
    assert messages[0] == (
        f"1 comment(s) on {LESSON} are still open: 5e1d0c2a-7b3f-4c1e-9a6d-000000000005 (owner, {LEDGER})"
    )
    resolve(course_copy, "5e1d0c2a-7b3f-4c1e-9a6d-000000000005", "declined", "The owner kept the note's tone.")
    messages.clear()
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages)) == 0


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("outside", "import the review first (uv run content review-import"),
        ("missing", "reviews/inbox/nope.json: no such review file"),
        ("unsigned", "has no sign-off: the teacher signs off on the review page when no comment is open"),
        ("other-name", '--by "Maria Rossi" doesn\'t match the sign-off, which is by "Anna Bianchi"'),
        ("not-covered", f"the sign-off in reviews/inbox/review-u02-2026-10-27.json doesn't cover {LESSON}"),
    ],
)
def test_signoff_refusals(course_copy, tmp_path, setup, message):
    data = signed_review(course_copy, name="Anna Bianchi" if setup == "other-name" else "Maria Rossi")
    if setup == "unsigned":
        data["signoff"] = None
    if setup == "not-covered":
        del data["signoff"]["files"][LESSON]
    signoff = file_signoff(course_copy, tmp_path, data)
    if setup == "outside":
        signoff = tmp_path / "elsewhere.json"
        shutil.copyfile(course_copy / "reviews" / "inbox" / "review-u02-2026-10-27.json", signoff)
    if setup == "missing":
        signoff = Path("reviews/inbox/nope.json")
    problems = signoff_problems(course_copy, LESSON, signoff, "Maria Rossi")
    assert any(message in p for p in problems), problems
    messages: list[str] = []
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages)) == 1
    assert approval.read_review(course_copy / LESSON)["status"] == "draft"


# ---------------------------------------------------------------- the review loop, end to end


def test_content_review_procedure_end_to_end(course_copy, fixtures_dir, tmp_path):
    """Import → fix and resolve → --since page → the teacher signs off → the owner approves with the sign-off."""
    # 1. Import (the fixture was made on the current files).
    result = import_review(write(tmp_path, current(course_copy, load(fixtures_dir))), root=course_copy)
    assert len(result.added) == 7
    # 3. Fix: the agent changes the story line the teacher commented on…
    path = course_copy / LESSON
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"Buongiorno. Vorrei un cappuccino, per favore."', '"Buongiorno! Un cappuccino, per favore."'
        ),
        encoding="utf-8",
    )
    # 4. …and records a resolution for every open comment.
    for n, status, note in (
        ("1", "fixed", None),
        ("2", "fixed", "«quanto viene» is now accepted."),
        ("3", "answered", "Yes: the hint now says «No, grazie» works too."),
        ("5", "declined", "The note keeps its friendly tone; the owner agreed."),
        ("6", "answered", "Thank you!"),
        ("7", "answered", "Ordering for a friend is Unit 2's talk task, so yes."),
    ):
        resolve(course_copy, f"5e1d0c2a-7b3f-4c1e-9a6d-00000000000{n}", status, note, "abc1234")
    assert errors(course_copy) == []
    # 6. Return: the next page shows the resolutions and marks the changed line.
    page = export("u02", root=course_copy, since=True, out=tmp_path / "next.html")
    assert page.since is not None and page.since.marks == {"u02.l1.story#3": "changed"}
    assert "since: 1 changed" in page.summary(course_copy)
    # 7. Sign-off: the teacher checks the change, marks it OK and signs off; the owner approves.
    story = {
        "id": "after-1",
        "target": "u02.l1.story#3",
        "file": LESSON,
        "quote": "Buongiorno! Un cappuccino, per favore.",
        "verdict": "ok",
        "at": "2026-10-27T10:01:00Z",
    }
    # (the agent refreshed the annotations after the fix, as `make annotate` does; approve runs `content check`)
    notes: list[str] = []
    assert run_annotate(course_copy, echo=notes.append) == 0, notes[-5:]
    signoff = file_signoff(course_copy, tmp_path, signed_review(course_copy, comments=[story]))
    assert ledger(course_copy)[-1]["resolution"]["status"] == "noted"
    messages: list[str] = []
    assert approval.approve(Path(LESSON), "Maria Rossi", root=course_copy, signoff=signoff, **human(messages)) == 0
    assert errors(course_copy) == []
