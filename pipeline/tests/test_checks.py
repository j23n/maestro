"""M1.8: checks 2 (level gate), 4 (alignment) and 5 (story consistency), and the check.json/check.md reports.

Mutations run on a throwaway copy of `content/` (with its lock files): edit the YAML, re-annotate, check.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import needs_data
from itcontent.annotate import run_annotate
from itcontent.checks import CheckResult, run_check, run_checks
from itcontent.checks.context import load_context
from itcontent.checks.story import Matrix, node_registers

pytestmark = needs_data

LESSON = "content/units/02-al-bar/lesson-1.yaml"
ITEMS_U02 = "content/items/u02.yaml"
STORY_END = (
    '        - {speaker: ch:giulia, to: ch:marco, register: lei, it: "Prego! Arrivederci.", '
    'en: "You\'re welcome! Goodbye."}\n'
)


def make_repo(root: Path, tmp: Path) -> Path:
    shutil.copytree(root / "content", tmp / "content")
    (tmp / "pipeline" / "data").mkdir(parents=True)
    (tmp / "pipeline" / "data" / "morph-it").symlink_to(root / "pipeline" / "data" / "morph-it")
    return tmp


@pytest.fixture
def repo(root: Path, tmp_path: Path) -> Path:
    return make_repo(root, tmp_path / "repo")


def edit(repo: Path, rel: str, old: str, new: str) -> None:
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def add_story_line(repo: Path, line: str) -> None:
    edit(repo, LESSON, STORY_END, STORY_END + f"        - {line}\n")


def annotate_and_check(repo: Path) -> CheckResult:
    out: list[str] = []
    assert run_annotate(repo, echo=out.append) == 0, "\n".join(out)
    return run_checks(repo)


def messages(result: CheckResult, level: str = "error", check: int | None = None, rule: str | None = None) -> list[str]:
    return [
        str(f)
        for f in result.findings
        if f.level == level and (check is None or f.check == check) and (rule is None or f.rule == rule)
    ]


@pytest.fixture(scope="module")
def seed(root: Path) -> CheckResult:
    return run_checks(root)


# ---------------------------------------------------------------- the seed course


def test_seed_course_passes_with_only_the_golden_unit_written(seed):
    assert seed.errors == [], "\n".join(map(str, seed.errors))
    # incomplete units are pending, never errors
    pending = [f for f in seed.findings if f.level == "pending"]
    assert {f.unit for f in pending if f.check == 4} == {u.id for u in seed.ctx.course.units}
    assert all("is incomplete" in f.message for f in pending if f.check == 4)


def test_golden_lesson_has_no_findings_of_its_own(seed):
    assert [str(f) for f in seed.findings if f.file == LESSON] == []


def test_partial_content_fallbacks_are_grouped_warnings(seed):
    partial = messages(seed, "warning", 2, "partial")
    assert any(m.startswith("warning: content/items/u02.yaml") and "u02.l2 isn't written yet" in m for m in partial)
    assert any("w:certo" in m and "w:sessanta" in m for m in partial)  # the task and check use them
    assert any("g:essere-present-sg" in m and "start of u01" in m for m in partial)


def test_golden_story_budget_and_introductions(seed):
    story = next(b for b in seed.level.budgets if b.text == "u02.l1.story")
    assert (story.new, story.recognise, story.words, story.limit) == (2, 0, 95, 0.05)  # da mangiare, glossed
    ctx = seed.ctx
    assert ctx.intros.first("w:cornetto").step == "u02.l1.step-preview"
    assert ctx.intros.first("c:da-mangiare").via == "story"
    assert ctx.intros.first("g:indefinite-article").step == "u02.l1.step-note"
    assert ctx.intros.first("g:conditional-courtesy").via == "preview"  # c:vorrei exemplifies it (chunk point)
    assert ctx.intros.first("c:cosa-prende", "recall") is None  # status R: never for production
    assert ctx.lesson_targets["u02.l1"] == (1, frozenset({"g:indefinite-article", "g:noun-gender"}))


# ---------------------------------------------------------------- check 2: the level gate


def test_abbiamo_mangiato_in_the_story_fails_the_construction_and_morphology_gates(repo):
    # glossed, so it resolves; but the passato prossimo (u09) and the noi form (u04) aren't taught in Unit 2
    add_story_line(
        repo,
        '{speaker: ch:marco, to: ch:sara, register: tu, it: "Abbiamo mangiato un cornetto!", '
        'en: "We ate a croissant!", gloss: {abbiamo mangiato: we ate}}',
    )
    result = annotate_and_check(repo)
    construction = messages(result, check=2, rule="construction")
    assert any(
        "'Abbiamo mangiato' is g:passato-prossimo-avere (u09), not taught at u02.l1.step-story" in m
        and "steps[1].text.lines[22].it" in m
        for m in construction
    ), construction
    morphology = messages(result, check=2, rule="morphology")
    assert any(
        "verb form 'mangiato' (mangiare VER:part+past+s+m)" in m and "g:passato-prossimo-avere" in m for m in morphology
    )
    assert any("verb form 'Abbiamo'" in m and "g:present-noi (u04, P)" in m for m in morphology)
    assert run_check(repo, echo=lambda _: None) == 1


def test_abbiamo_mangiato_with_later_unit_items_also_fails_the_lemma_gate(repo):
    (repo / "content/items/u03.yaml").write_text(
        "unit: u03\nreview: {status: draft, by: null, date: null, hash: null}\nitems:\n"
        "  - {id: 'w:avere', it: avere, pos: verb, gloss: to have, status: P, lesson: u03.l1}\n"
        "  - {id: 'w:mangiare', it: mangiare, pos: verb, gloss: to eat, status: P, lesson: u03.l2}\n"
        "  - {id: 'w:famiglia', it: famiglia, pos: noun, gender: f, plural: famiglie, gloss: family, status: P, "
        "lesson: u03.l1}\n",
        encoding="utf-8",
    )
    add_story_line(repo, '{speaker: narrator, it: "Marco e Sara: abbiamo mangiato!", en: "Marco and Sara: we ate!"}')
    result = annotate_and_check(repo)
    lemma = messages(result, check=2, rule="lemma")
    assert any("'abbiamo' (w:avere) is untaught at u02.l1.step-story: it is introduced in u03" in m for m in lemma)
    assert any("'mangiato' (w:mangiare) is untaught" in m for m in lemma)
    assert messages(result, check=2, rule="construction")


def test_recognise_forms_skip_the_gates_and_are_listed(repo):
    add_story_line(
        repo,
        '{speaker: ch:marco, to: ch:sara, register: tu, it: "Abbiamo mangiato!", en: "We ate!", '
        "gloss: {abbiamo: we have, mangiato: eaten}, recognise: [abbiamo, mangiato]}",
    )
    result = annotate_and_check(repo)
    assert result.errors == [], "\n".join(map(str, result.errors))
    listed = [x for x in result.level.exemptions if x.kind == "recognise"]
    assert [(x.ref, x.detail) for x in listed] == [("u02.l1.story#23", "Abbiamo, mangiato")]
    story = next(b for b in result.level.budgets if b.text == "u02.l1.story")
    assert (story.new, story.recognise) == (2, 2)


def test_allow_lines_skip_the_morphology_gate_only(repo):
    add_story_line(
        repo,
        '{speaker: narrator, it: "Marco vorrebbe un caffè.", en: "Marco would like a coffee.", '
        "gloss: {vorrebbe: would like}, allow: {reason: test}}",
    )
    result = annotate_and_check(repo)
    assert not messages(result, check=2, rule="morphology")
    # a chunk point (vorrei) outside its chunk always fails the construction gate
    assert any("'vorrebbe' is g:conditional-courtesy, which is taught only as chunks" in m for m in messages(result))
    assert [x.detail for x in result.level.exemptions if x.kind == "allow"] == ["test"]


def test_conditional_outside_the_chunk_fails_morphology(repo):
    add_story_line(repo, '{speaker: narrator, it: "Marco vorrebbe un caffè.", en: "x", gloss: {vorrebbe: would like}}')
    result = annotate_and_check(repo)
    assert any(
        "verb form 'vorrebbe'" in m and "no grammar point unlocks this form" in m
        for m in messages(result, check=2, rule="morphology")
    )


def test_new_token_budget(repo):
    add_story_line(
        repo,
        '{speaker: narrator, it: "Marco mangia, beve, legge e scrive.", en: "x", '
        "gloss: {mangia: eats, beve: drinks, legge: reads, scrive: writes}, recognise: [mangia, beve, legge, scrive]}",
    )
    result = annotate_and_check(repo)
    budget = messages(result, check=2, rule="budget")
    assert len(budget) == 1 and "2 new + 4 recognise of 100 word tokens in u02.l1.story = 6.0%, above 5%" in budget[0]
    assert "steps[1].text (line" in budget[0]


def test_production_gate_rejects_recognition_items_in_model_answers(repo):
    edit(
        repo,
        LESSON,
        "answer: \"{quant'è|quanto è|quanto costa|scusi quant'è|scusi quanto costa}\"",
        'answer: "{cosa prende|quant\'è}"',
    )
    result = annotate_and_check(repo)
    prod = messages(result, check=2, rule="production")
    assert any(
        "'cosa' (c:cosa-prende) in a model answer at u02.l1.step-practice: c:cosa-prende has status R for recall" in m
        for m in prod
    ), prod


def test_other_expansions_are_not_gated(seed):
    # ex07's alternatives use `quanto costa` (u02.l2) and `quanto è` (no item): accepted, never gated
    assert not [f for f in seed.findings if "steps[3].block[6]" in f.where]


def test_an_item_whose_written_lesson_does_not_introduce_it_is_an_error(repo):
    edit(
        repo,
        ITEMS_U02,
        "status: P, lesson: u02.l2}\n  - {id: 'w:latte'",
        "status: P, lesson: u02.l1}\n  - {id: 'w:latte'",
    )
    result = annotate_and_check(repo)
    intro = messages(result, check=2, rule="introduction")
    assert intro == [
        f"error: {ITEMS_U02} › items[8].lesson (line 14): check 2 · introduction: w:certo names lesson u02.l1, but "
        "u02.l1 doesn't introduce it: put it in a preview batch, gloss it as new in the story, or change `lesson`"
    ]


def test_stale_lock_files_are_errors(repo):
    edit(repo, LESSON, '"Mmm! Buono!"', '"Mmm! Buono buono!"')  # no `make annotate`
    result = run_checks(repo)
    assert any("lesson-1.json is stale" in m and "run `make annotate`" in m for m in messages(result, check=0))
    assert not [f for f in result.findings if f.file == LESSON and f.check == 2]


# ---------------------------------------------------------------- check 5: story consistency


def test_tu_line_from_giulia_to_marco_fails_the_register_matrix(repo):
    edit(
        repo,
        LESSON,
        '{speaker: ch:giulia, to: ch:marco, register: lei, it: "Buongiorno! Cosa prende?"',
        '{speaker: ch:giulia, to: ch:marco, register: tu, it: "Buongiorno! Cosa prende?"',
    )
    result = annotate_and_check(repo)
    assert messages(result, check=5) == [
        f"error: {LESSON} › steps[1].text.lines[1].register (line 27): check 5 · register: line u02.l1.story#2: "
        "ch:giulia says tu to ch:marco at u02.l1.step-story, but the story bible says lei (registers[14]: "
        "ch:giulia → ch:marco: lei, tu from u05.l1.step-story). Fix the line, not the bible"
    ]


def test_register_heuristics(repo):
    add_story_line(
        repo, '{speaker: ch:giulia, to: ch:marco, register: lei, it: "Sei di Bologna?", en: "Are you from Bologna?"}'
    )
    edit(repo, LESSON, 'it: "Bene, grazie. E tu?"', 'it: "Bene, grazie. E Lei?"')  # Marco to Sara, tu
    result = annotate_and_check(repo)
    warnings = messages(result, "warning", 5)
    assert any("line u02.l1.story#23 is lei but has second-person-singular form(s) 'Sei'" in m for m in warnings)
    assert any("line u02.l1.story#13 is tu but has formal form(s) 'Lei'" in m for m in warnings)
    assert result.errors == []


def test_conversation_register_and_unknown_speakers(repo):
    edit(repo, LESSON, "      with: ch:giulia\n      register: lei", "      with: ch:giulia\n      register: tu")
    add_story_line(repo, '{speaker: ch:nobody, it: "Ciao!", en: "Hi!"}')
    result = annotate_and_check(repo)
    errs = messages(result, check=5)
    assert any("conversation u02.l1.ex25: ch:giulia says tu to ch:you at u02.l1.step-use" in m for m in errs)
    assert any("conversation u02.l1.ex25: ch:you says tu to ch:giulia" in m for m in errs)
    assert any("speaker ch:nobody isn't in story-bible.yaml" in m for m in errs)


def test_register_matrix_precedence_and_switch_points(seed):
    ctx = seed.ctx
    m = Matrix(ctx)
    u = ctx.unit_index

    def reg(a: str, b: str, unit: str) -> list[str]:
        return [r.register for r in m.lookup(a, b, u[unit])]

    assert reg("ch:luca", "ch:rossi", "u03") == ["lei"]  # exact pair beats (ch:luca, '*')
    assert reg("ch:luca", "ch:sara", "u03") == ["tu"]  # (speaker, '*')
    assert reg("ch:sara", "ch:luca", "u03") == ["tu"]  # ('*', addressee)
    assert reg("ch:extra", "ch:luca", "u03") == ["tu"]  # exact beats (ch:extra, '*') and ('*', ch:luca)
    assert m.lookup("ch:zia-rosa", "ch:sara", u["u11"]) == []
    row = m.lookup("ch:giulia", "ch:marco", u["u05"])[0]
    switch = ctx.step_pos("u05.l1.step-story")
    assert switch == (u["u05"], 1, 0)  # lesson not written yet: its start
    assert m.allowed(row, (u["u04"], 3, 2)) == {"lei"}
    assert m.allowed(row, switch) == {"lei", "tu"}
    assert m.allowed(row, (u["u05"], 2, 0)) == {"tu"}
    assert ctx.step_pos("u05.step-conversation-1") == (u["u05"], 900, 1)


def test_overlapping_register_rows_are_story_bible_errors(repo):
    edit(
        repo,
        "content/story-bible.yaml",
        "  - {from: ch:sara, to: ch:marco, register: tu, units: all}\n",
        "  - {from: ch:sara, to: ch:marco, register: tu, units: all}\n"
        "  - {from: ch:sara, to: ch:marco, register: lei, units: [u02, u03]}\n",
    )
    result = annotate_and_check(repo)
    assert any(
        "registers[8] and registers[9] both cover ch:sara → ch:marco in u02" in m for m in messages(result, check=5)
    )


def test_node_registers_follow_the_graph():
    ex = {
        "register": "lei",
        "start": "a",
        "nodes": {
            "a": {"expect": [{"next": "b"}]},
            "b": {"register": "tu", "expect": [{"next": "c"}]},
            "c": {"final": True},
            "z": {},
        },
    }
    assert node_registers(ex) == {"a": ("lei", None), "b": ("tu", "b"), "c": ("tu", "b"), "z": ("lei", None)}


# ---------------------------------------------------------------- check 4: alignment


def test_alignment_errors_on_written_files(repo):
    edit(repo, LESSON, "      - examples: [u02.l1.story#3, u02.l1.story#16, u02.l1.story#11]\n", "")
    edit(
        repo,
        LESSON,
        "        tags: [sy:cefr.reading]\n        prompt_it:",
        "        tags: [topic:food-drink]\n        prompt_it:",
    )
    edit(repo, LESSON, "          - {item: w:amico, skill: read}\n", "")
    result = annotate_and_check(repo)
    errs = messages(result, check=4)
    assert any("note u02.l1.note has 0 example(s) from its lesson's story (u02.l1.story)" in m for m in errs)
    assert any("u02.l1.ex21 has no cd: or sy: tag" in m for m in errs)
    assert any("u02.l1.ex20: 5 targets for 6 pairs" in m for m in errs)


def test_complete_units_get_unit_level_alignment(repo):
    edit(repo, "content/units/02-al-bar/unit.yaml", "lessons: 3", "lessons: 1")  # now lesson 1, task and check exist
    result = annotate_and_check(repo)
    assert not [f for f in result.findings if f.level == "pending" and f.unit == "u02"]
    errs = messages(result, check=4)
    assert sorted(m.split("check 4 · ")[1] for m in errs) == [
        "note: g:noun-plural is a P point of u02, but no note in u02 introduces it (list it in a note's `grammar`)",
        "note: g:numbers-to-100 is a P point of u02, but no note in u02 introduces it (list it in a note's `grammar`)",
    ]


# ---------------------------------------------------------------- reports and the command


def test_reports_are_written_deterministically(repo):
    out: list[str] = []
    assert run_annotate(repo, echo=out.append) == 0
    assert run_check(repo, echo=out.append) == 0
    assert out[-1].startswith("check: 0 error(s)")
    first = {n: (repo / "build/reports" / n).read_bytes() for n in ("check.json", "check.md")}
    assert run_check(repo, echo=out.append) == 0
    assert first == {n: (repo / "build/reports" / n).read_bytes() for n in ("check.json", "check.md")}
    data = json.loads(first["check.json"])
    assert data["format"] == 1 and data["scope"] == "all" and data["summary"]["error"] == 0
    assert {"level", "check", "rule", "file", "path", "keys", "line", "message", "unit"} <= set(data["findings"][0])
    md = first["check.md"].decode()
    for heading in ("# Content check", "## Findings", "## Units", "## Level gate (check 2)"):
        assert heading in md
    assert "| u02.l1.story | story | 95 | 2 | 0 | 2.1% | 5% |" in md


def test_json_and_unit_scope(repo):
    out: list[str] = []
    assert run_annotate(repo, echo=out.append) == 0
    out.clear()
    assert run_check(repo, unit="u02", as_json=True, echo=out.append) == 0
    data = json.loads(out[0])
    assert data["scope"] == "u02" and [u["id"] for u in data["units"]] == ["u02"]
    assert {f["unit"] for f in data["findings"]} == {"u02"}
    assert run_check(repo, unit="u42", echo=out.append) == 2


def test_context_reads_lock_files_without_morph_it(root):
    ctx = load_context(root)
    golden = [s for s in ctx.strings if s.file == LESSON]
    assert golden and all(s.pos is not None and s.pos[0] == ctx.unit_index["u02"] for s in golden)
    line = next(s for s in golden if s.ref == "u02.l1.story#3")
    assert line.step == "u02.l1.step-story" and line.line is not None and line.line["speaker"] == "ch:marco"
