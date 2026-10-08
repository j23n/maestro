"""M1.3: review pages (`content review-export`), docs/04 § Content review loop › Review pages.

Snapshots use a small frozen course (`fixtures/review/course/`: one unit with one lesson, a task and a check, tiny
sign-off files and a docs/13 with two content questions), so content edits never change them. The page's inline CSS
and script are left out of the snapshots; the browser test (`test_review_browser.py`) covers the script. Regenerate
with `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_review_page.py` and review the diff.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from itcontent import review, schemas
from itcontent.cli import app
from itcontent.course import load_course
from itcontent.review_elements import Context, build_page
from itcontent.review_export import export, render_page

SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.fixture(scope="module")
def mini(fixtures_dir: Path) -> Path:
    return fixtures_dir / "review" / "course"


def _strip_assets(page: str) -> str:
    page = re.sub(r"<style>.*?</style>", "<style>/* page.css */</style>", page, flags=re.S)
    return re.sub(r"<script>\n.*?</script>", "<script>/* page.js */</script>", page, flags=re.S)


def _pretty(page: str) -> str:
    """The page with one element per line and the embedded data pretty-printed, so snapshot diffs are readable."""
    m = re.search(r'(<script type="application/json" id="review-data">)(.*?)(</script>)', page, flags=re.S)
    assert m, "the page embeds its data"
    data = json.dumps(json.loads(m.group(2)), indent=1, ensure_ascii=False, sort_keys=True)
    page = page[: m.start(2)] + "\n" + data + "\n" + page[m.end(2) :]
    return re.sub(r"(<article |<section |<h[234])", r"\n\1", page)


def _check_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if not os.environ.get("UPDATE_SNAPSHOTS"):
            pytest.fail(f"wrote a new snapshot {path.name}; review it and run the tests again")
    assert text == path.read_text(encoding="utf-8"), f"{name} changed; UPDATE_SNAPSHOTS=1 regenerates it"


@pytest.mark.parametrize("scope", ["u02", "specs"])
def test_page_snapshot(mini, scope, tmp_path):
    result = export(scope, root=mini, out=tmp_path / "index.html")
    _check_snapshot(f"review-{scope}.html", _pretty(_strip_assets(result.path.read_text(encoding="utf-8"))))


def test_page_is_self_contained_and_deterministic(mini, tmp_path):
    a = export("u02", root=mini, out=tmp_path / "a.html").path.read_text(encoding="utf-8")
    b = export("u02", root=mini, out=tmp_path / "b.html").path.read_text(encoding="utf-8")
    assert a == b
    assert not re.search(r"""(?:src|href)=["']?(?:https?:)?//""", a), "no network: everything is inline"
    assert "<link" not in a and "<script src" not in a
    assert a.count("<style>") == 1 and "localStorage" in a and "Download my review" in a and "Sign off" in a


def test_every_element_of_the_page(mini):
    """Each element has a verdict box, a target that resolves to its file, and the page shows what docs/04 lists."""
    course = load_course(mini)
    ctx = Context.build(course)
    model = build_page(ctx, "u02")
    page = render_page(model)
    targets = [e.target for e in model.elements()]
    assert len(targets) == len(set(targets))
    for e in model.elements():
        assert review.target_problem(course, ctx.index, e.target) is None, e.target
        assert review.target_file(course, ctx.index, e.target) == e.file, e.target
        assert f'class="el-review" data-key="{e.key}"' in page
    by = {e.target: e for e in model.elements()}
    assert "Giulia → Marco · Lei" in by["u02.l1.story#2"].body  # every story line with speaker, register, English
    assert "to eat" in by["u02.l1.story#2"].body and "Good morning!" in by["u02.l1.story#2"].body
    assert "Una is for feminine nouns." in by["u02.l1.ex01"].body  # near-misses with their hints
    assert "nearly right" in by["u02.l1.ex04"].body
    assert '<code class="src">un [cornetto]</code>' in by["u02.l1.ex04"].body  # accepted answers (patterns)
    assert "Model answer" in by["u02.l1.ex04"].body and ">un cornetto<" in by["u02.l1.ex04"].body
    assert {"u02.l1.ex25/n1", "u02.l1.ex25/end", "u02.task.conv1/n1"} <= set(by)  # conversations as node trees
    assert "nothing-to-eat" in by["u02.task.conv1/n1"].body
    assert "In Bologna many people call it a brioche." in by["w:cornetto"].body  # items with gloss, gender, note
    assert "Bar Aurora" in by["u02.task.menu"].body and "1,40" in by["u02.task.menu"].body  # real-world layout
    assert by["u02.l1.note"].kind == "note" and "Learn every noun with its article." in by["u02.l1.note"].body
    assert {"u02.check.01.audio#1", "u02.check.01.audio#2"} <= set(by)  # audio texts line by line
    steps = [e for e in model.elements() if e.kind == "step"]
    assert steps and not any(e.counted for e in steps)


def test_a_conversation_shows_the_learners_register_when_it_differs(mini, tmp_path):
    import shutil

    shutil.copytree(mini, tmp_path / "c")
    task = tmp_path / "c" / "content" / "units" / "02-al-bar" / "task.yaml"
    text = task.read_text(encoding="utf-8")
    assert "    with: ch:giulia\n    register: lei\n" in text
    task.write_text(text.replace("    register: lei\n", "    register: tu\n    learner_register: lei\n", 1), "utf-8")
    by = {e.target: e for e in build_page(Context.build(load_course(tmp_path / "c")), "u02").elements()}
    assert "Giulia · tu (you answer with Lei); starts at" in by["u02.task.conv1"].body
    assert "learner_register" not in by["u02.task.conv1"].body  # shown in words, not as a raw field
    assert "Giulia · Lei; starts at" in by["u02.l1.ex25"].body  # the same register both ways: nothing added


def test_specs_page_covers_the_signoff_files_and_content_questions(mini):
    course = load_course(mini)
    model = build_page(Context.build(course), "specs")
    assert list(model.files) == [
        "content/syllabus/a1-syllabus.yaml",
        "content/grammar/points.yaml",
        "content/units/02-al-bar/unit.yaml",
        "content/story-bible.yaml",
        "content/countries.yaml",
        "docs/13-decisions.md",
    ]
    targets = {e.target for e in model.elements()}
    assert {
        "sy:gr.articles",
        "g:indefinite-article",
        "u02",
        "cd:order-food-drink",
        "u02.grammar",
        "u02.tasks",
    } <= targets
    assert {"u02.check.items", "ch:giulia", "story-bible.places[0]", "story-bible.registers[0]"} <= targets
    assert {"story-bible.facts_to_check[0]", "ca", "countries.other", "CQ1", "CQ2"} <= targets
    cq1 = next(e for e in model.elements() if e.target == "CQ1")
    assert cq1.file == "docs/13-decisions.md" and "brioche" in cq1.body


def test_the_real_course_pages_resolve(root):
    """On the real content every scope builds, keys are unique and every target resolves to the element's file."""
    course = load_course(root)
    ctx = Context.build(course)
    for scope in ("specs", "assessments", *(u.id for u in course.units)):
        model = build_page(ctx, scope)
        keys = [e.key for e in model.elements()]
        assert len(keys) == len(set(keys)), scope
        assert set(model.files) == set(review.scope_files(course, scope)), scope
        for e in model.elements():
            assert review.target_problem(course, ctx.index, e.target) is None, (scope, e.target)
            assert review.target_file(course, ctx.index, e.target) == e.file, (scope, e.target)


def test_docs13_hash_covers_only_the_content_questions(tmp_path, mini):
    import shutil

    shutil.copytree(mini, tmp_path / "c")
    path = tmp_path / "c" / review.DECISIONS
    before = review.version_hash(tmp_path / "c", review.DECISIONS)
    path.write_text(path.read_text(encoding="utf-8") + "\n- 2026-11-01: a proposal\n", encoding="utf-8")
    assert review.version_hash(tmp_path / "c", review.DECISIONS) == before  # the decisions log can grow
    path.write_text(path.read_text(encoding="utf-8").replace("as listed", "as listed, but 1,30"), encoding="utf-8")
    assert review.version_hash(tmp_path / "c", review.DECISIONS) != before


# ---------------------------------------------------------------- accepted answers, expanded


def test_accepted_answers_are_expanded_with_the_graders_expander(mini):
    """Every accepted answer as written, grouped by pattern, focus underlined, the model answer first (docs/03)."""
    ctx = Context.build(load_course(mini))
    by = {e.target: e for e in build_page(ctx, "u02").elements()}
    ex04 = by["u02.l1.ex04"].body
    assert '<li lang="it" class="model">un <b class="focus">cornetto</b></li>' in ex04 and "1 answer<" in ex04
    assert 'Model answer</span> <span lang="it" class="it">un cornetto</span>' in ex04
    node = by["u02.l1.ex25/n1"].body
    assert "8 answers" in node  # (buongiorno )(vorrei )un cornetto( per favore)
    assert '<li lang="it" class="model">buongiorno vorrei un cornetto per favore</li>' in node
    assert '<li lang="it">un cornetto</li>' in node
    assert "vorrei una cornetto · una cornetto" in node  # near-miss patterns expanded too
    amico = by["w:amico"].body
    assert "4 answers" in amico and '<li lang="it" class="model">l&#x27;amico</li>' in amico
    cloze = by["u02.l1.ex01"].body
    assert '<mark class="gap">un</mark>' in cloze and "Vorrei un cornetto, per favore." in cloze
    assert ctx.model("{quant'è|quanto è}") == "quant'è"
    assert "Pattern error: unknown slot {NOME}" in ctx.answers(["mi chiamo {NOME}"])
    assert ctx.model("mi chiamo {NOME}") == "mi chiamo {NOME}"  # a broken pattern is shown as written


def test_another_expander_can_be_passed(mini):
    ctx = Context.build(load_course(mini), expander=lambda source: [source.upper(), "alt"])
    body = {e.target: e for e in build_page(ctx, "u02").elements()}["u02.l1.ex04"].body
    assert '<li lang="it" class="model">UN [CORNETTO]</li><li lang="it">alt</li>' in body and "2 answers" in body


# ---------------------------------------------------------------- categories are one list everywhere


def test_categories_match_the_schema_and_the_app(root):
    keys = list(review.CATEGORIES)
    assert keys == [
        "italian-error",
        "naturalness",
        "level",
        "answer-key",
        "hint-or-rule",
        "english",
        "culture-or-facts",
        "audio",
        "other",
    ]
    schema = json.loads((root / "schemas" / "review-file.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["commentFields"]["properties"]["category"]["enum"] == [*keys, None]
    swift = root / "App" / "Italiano" / "Features" / "ReviewMode" / "ReviewFile.swift"
    if swift.is_file():
        text = swift.read_text(encoding="utf-8")
        block = text[text.index("enum Category") : text.index("var label")]
        cases = re.findall(r'case (\w+)(?: = "([a-z-]+)")?', block)
        assert [raw or name for name, raw in cases] == keys
        labels = dict(re.findall(r'case \.(\w+): "([^"]+)"', text))
        assert [labels[name] for name, _ in cases] == list(review.CATEGORIES.values())
    assert schemas.validate("review-file", _file(category="naturalness")) == []
    assert schemas.validate("review-file", _file(category="grammar")) == [
        (
            ("comments", 0, "category"),
            "'grammar' is not a review category (allowed: italian-error, naturalness, level, answer-key, "
            "hint-or-rule, english, culture-or-facts, audio, other)",
        )
    ]


def _file(**comment) -> dict:
    c = {"id": "a", "target": "u02.l1.ex07", "file": "content/units/02-al-bar/lesson-1.yaml", "verdict": "change"}
    c.update({"at": "2026-10-20T09:15:00Z", **comment})
    return {
        "format": 1,
        "reviewer": "M",
        "channel": "page",
        "scope": "u02",
        "created": "2026-10-20T09:12:00Z",
        "files": {},
        "comments": [c],
    }


# ---------------------------------------------------------------- the command


def test_cli_review_export(mini, tmp_path, monkeypatch):
    from itcontent import paths

    monkeypatch.setattr(paths, "ROOT", mini)
    monkeypatch.setattr(paths, "REPORTS", tmp_path / "reports")
    out = tmp_path / "page.html"
    result = CliRunner().invoke(app, ["review-export", "--unit", "u02", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "elements" in result.output and out.is_file()
    for args in (["review-export"], ["review-export", "--specs", "--unit", "u02"], ["review-export", "--unit", "2"]):
        assert CliRunner().invoke(app, args).exit_code == 2
    result = CliRunner().invoke(app, ["review-export", "--unit", "u07", "--out", str(out)])
    assert result.exit_code == 1 and "no unit u07" in result.output
