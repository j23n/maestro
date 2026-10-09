"""M1.2: ID formats and placement, uniqueness, slug collisions, references (pending vs error), exercise rules,
ids.lock, retired.yaml and review-ledger targets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from itcontent import approval, ids
from itcontent.course import load_course
from itcontent.index import build_index
from itcontent.lint import lint_findings

LESSON = "content/units/03-la-famiglia/lesson-1.yaml"
ITEMS = "content/items/u03.yaml"
E = "error: " + LESSON
EI = "error: " + ITEMS

# fixture → (target path, expected finding lines); "{actual}" is the placed file's approval hash (12 hex digits)
CASES: dict[str, tuple[str, list[str]]] = {
    "items-duplicate-id.yaml": (
        ITEMS,
        [
            f"{EI} › items[0].id (line 5): duplicate ID 'w:caffe': already defined at "
            "content/items/u02.yaml › items[0].id (line 6)"
        ],
    ),
    "items-slug-collision.yaml": (
        ITEMS,
        [
            f"{EI} › items[0].id (line 6): w:pesca collides with w:pesca-fishing (content/items/u03.yaml › "
            "items[1].id (line 7)): both slug to 'pesca', and only one item of a homograph group keeps a plain ID, "
            "so the newcomer needs a ~sense suffix (e.g. w:pesca~<sense>)",
            f"{EI} › items[1].id (line 7): w:pesca-fishing collides with w:pesca (content/items/u03.yaml › "
            "items[0].id (line 6)): both slug to 'pesca', and only one item of a homograph group keeps a plain ID, "
            "so the newcomer needs a ~sense suffix (e.g. w:pesca~<sense>)",
        ],
    ),
    "items-wrong-lesson.yaml": (
        ITEMS,
        [
            f"{EI} › items[0].lesson (line 5): w:foto is a u03 item, so its lesson is in u03, not u02.l1",
            f"{EI} › items[1].lesson (line 6): u03 has 3 lessons; there is no u03.l4",
        ],
    ),
    "items-chunk-id-and-slash.yaml": (
        ITEMS,
        [
            f"{EI} › items[0].id (line 6): w:ho-fame: a chunk item's ID starts with c:",
            f"{EI} › items[0].it (line 6): w:ho-fame: a chunk written with '/' ('ho fame / ho sete') needs a "
            "recall_answer (docs/05 § Review session builder)",
        ],
    ),
    "lesson-id-mismatch.yaml": (
        LESSON,
        [
            f"{E} › id (line 3): lesson ID u03.l2 doesn't match its file (expected u03.l1)",
            f"{E} › steps[0].id (line 8): step ID u03.l2.step-note doesn't match the step's kind story "
            "(expected u03.l2.step-story[-N])",
            f"{E} › steps[0].text.id (line 10): text ID u02.l1.foto doesn't fit here: expected u03.l2.<name>",
            f"{E} › steps[1].block[0].id (line 17): exercise ID u02.l1.ex30 doesn't fit here: expected u03.l2.exNN",
        ],
    ),
    "lesson-unknown-references.yaml": (
        LESSON,
        [
            f"{E} › steps[0].text.lines[0].speaker (line 13): unknown character 'ch:paolo'",
            f"{E} › steps[1].block[0].targets[0].item (line 19): unknown item 'w:gatto'",
            f"{E} › steps[1].block[0].targets[1].item (line 19): unknown grammar point 'g:possessive-pronouns'",
            f"{E} › steps[1].block[0].tags[0] (line 20): unknown can-do 'cd:talk-about-cats'",
            # the same sound is only pending when the Unit 3 spec names it (see test_pending_vs_error)
            f"{E} › steps[1].block[1].targets[0].item (line 25): unknown sound 's:gli-gn'",
        ],
    ),
    "lesson-line-out-of-range.yaml": (
        LESSON,
        [
            f"{E} › steps[0].body[0].examples[1] (line 12): text u02.l1.story has 22 lines; there is no line 30",
            f"{E} › steps[1].block[0].source (line 20): "
            "text u02.task.menu is a real-world layout without numbered lines",
        ],
    ),
    "lesson-match-count.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].targets (line 11): a match has one target per pair: 3 targets for 2 pairs "
            "(targets[i] belongs to pairs[i])"
        ],
    ),
    "lesson-exercise-rules.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].answer (line 16): answer 3 is not an option index: there are 3 options (0–2)",
            f"{E} › steps[0].block[1].answer[1] (line 23): answer 'vorrei una caffè oggi' uses 'una', not among the "
            "tiles and leaves out the tile 'un' (an answer orders all the tiles)",
            f"{E} › steps[0].block[2].play (line 30): play 'echo' is not one of the pair (eco, ecco)",
        ],
    ),
    "lesson-conversation-graph.yaml": (
        LESSON,
        [
            f"{E} › steps[0].exercise.start (line 17): start node 'n0' doesn't exist (nodes: n1)",
            f"{E} › steps[0].exercise.nodes (line 18): no node is final: true, so the conversation never ends",
            f"{E} › steps[0].exercise.nodes.n1.expect[0].goal (line 23): goal 'drink' is not one of this "
            "conversation's goals (order)",
            f"{E} › steps[0].exercise.nodes.n1.expect[0].next (line 23): next node 'n2' doesn't exist (nodes: n1)",
            f"warning: {LESSON} › steps[0].exercise.goals[0].id (line 16): no intent completes goal 'order'",
        ],
    ),
    "lesson-preview-duplicate.yaml": (
        LESSON,
        [f"{E} › steps[0].batches[1][1] (line 8): w:caffe is already in this preview at steps[0].batches[0][0]"],
    ),
    "unit-grammar-mismatch.yaml": (
        "content/units/03-la-famiglia/unit.yaml",
        [
            "error: content/units/03-la-famiglia/unit.yaml › grammar (line 11): g:possessives is a u03 point in "
            "points.yaml but isn't listed here",
            "error: content/units/03-la-famiglia/unit.yaml › grammar[6].status (line 18): points.yaml gives g:molto "
            "status P, this unit spec says R",
            "error: content/units/03-la-famiglia/unit.yaml › grammar[7].id (line 19): g:essere-present-sg belongs to "
            "u01 in points.yaml, not u03",
            "error: content/units/03-la-famiglia/unit.yaml › tasks.conversation[0].id (line 30): a task conversation "
            "of u03 is named u03.task.<name>, not u02.task.conv1",
        ],
    ),
    "ids-lock-missing-id.lock": (
        "content/ids.lock",
        [
            "error: content/ids.lock (line 3): released ID 'u02.l1.ex12' no longer exists: restore it, or retire it "
            "in content/retired.yaml (ADR-14)"
        ],
    ),
    "retired-reused.yaml": (
        "content/retired.yaml",
        [
            "error: content/retired.yaml › retired[0].id (line 3): retired ID 'w:caffe' is reused at "
            "content/items/u02.yaml › items[0].id (line 6): retired IDs are never reused (ADR-14)",
            "error: content/retired.yaml › retired[0].replaced_by (line 3): unknown item 'w:caffe~espresso'",
        ],
    ),
    "approved-stale-hash.yaml": (
        ITEMS,
        [
            f"{EI} › review.hash (line 3): the file changed after approval: review.hash is 3f9c0e1a2b4d…, the file "
            "now hashes to {actual}… (docs/04 § Approval hash). Approved content changes only after the owner runs "
            "content reopen"
        ],
    ),
    "ledger-unknown-target.yaml": (
        "reviews/u02.yaml",
        [
            "error: reviews/u02.yaml › comments[0].target (line 7): comment c-0001: unknown target 'u02.l1.ex99'",
            "warning: reviews/u02.yaml › comments[1].target (line 17): comment c-0002: unknown target 'u02.l1.ex16' "
            "(resolved as fixed)",
        ],
    ),
}


def strs(root: Path) -> list[str]:
    return [str(f) for f in lint_findings(root)]


def test_every_fixture_in_the_folder_is_covered(fixtures_dir):
    from test_lint_schemas import CASES as SCHEMA_CASES

    on_disk = {p.name for p in (fixtures_dir / "invalid").iterdir()}
    assert on_disk == set(CASES) | set(SCHEMA_CASES)
    assert not set(CASES) & set(SCHEMA_CASES)


@pytest.mark.parametrize("fixture", sorted(CASES))
def test_invalid_fixture_reports_file_path_line_and_problem(fixture, course_copy, place):
    target, expected = CASES[fixture]
    path = place(fixture, target)
    found = strs(course_copy)
    actual = approval.file_hash(path)[:12]
    for line in expected:
        assert line.replace("{actual}", actual) in found, "\n".join(found)


def test_seed_content_lints_clean_with_pending_information(seed_root):
    findings = lint_findings(seed_root)
    assert [f for f in findings if f.level != "pending"] == []
    pending = {str(f) for f in findings}
    assert (
        "pending: content/units/03-la-famiglia/unit.yaml › sounds[0] (line 37): sound 's:gli-gn' doesn't exist yet"
        in pending
    )


def test_pending_vs_error(seed_root):
    """docs/04 § Commands: missing units, lessons, steps, items or sounds are pending in unit specs, the syllabus,
    the story bible's switch_at, disambiguation.yaml (and items' lessons); everything else missing is an error."""
    pending = [str(f) for f in lint_findings(seed_root) if f.level == "pending"]
    expect = [
        "pending: content/story-bible.yaml › registers[14].switch_at (line 117): step 'u05.l1.step-story' "
        "doesn't exist yet (1 more reference in this file)",
        "pending: content/disambiguation.yaml › defaults.porta (line 32): item 'w:porta~door' doesn't exist yet",
        "pending: content/syllabus/a1-syllabus.yaml › items[82].covered_by[0] (line 110): sound 's:silent-h' "
        "doesn't exist yet",
        "pending: content/items/u00.yaml › items[0].lesson (line 8): lesson 'u00.l1' doesn't exist yet "
        "(18 more references in this file)",
        "pending: content/units/00-benvenuti/unit.yaml › tasks.conversation[0].id (line 47): exercise "
        "'u00.task.conv1' doesn't exist yet",
    ]
    for line in expect:
        assert line in pending, "\n".join(pending)


def slug_findings(root: Path) -> list[str]:
    return [str(f) for f in lint_findings(root) if "slug to" in f.message]


def test_homograph_newcomers_carry_the_sense_suffix(course_copy):
    """docs/03 § IDs: in a homograph group one item keeps its plain ID and newcomers carry ~sense, so Unit 1's w:a,
    w:e, w:o and w:di keep their names when the Unit 0 letters join them."""
    assert slug_findings(course_copy) == []
    items = course_copy / "content/items/u00.yaml"
    letters = "".join(
        f"  - {{id: 'w:{w}~letter', it: {w}, pos: noun, gender: f, plural: invariable, gloss: the letter "
        f"{w.upper()}, status: P, lesson: u00.l2}}\n"
        for w in ("a", "e", "o", "di")
    )
    items.write_text(items.read_text(encoding="utf-8") + letters, encoding="utf-8")
    assert slug_findings(course_copy) == []  # a ~sense newcomer, even in an earlier unit than the plain ID
    # a second plain ID is an error on both (lint can't tell which came first) ...
    items.write_text(
        items.read_text(encoding="utf-8")
        + "  - {id: 'w:di-letter', it: di, pos: noun, gender: f, plural: invariable, gloss: the letter D, status: P, "
        "lesson: u00.l2}\n",
        encoding="utf-8",
    )
    found = slug_findings(course_copy)
    assert [f.split(" collides")[0].rsplit(": ", 1)[1] for f in found] == ["w:di-letter", "w:di"], found
    assert all("so the newcomer needs a ~sense suffix (e.g. w:di~<sense>)" in f for f in found)
    # ... unless one is released (ids.lock): it keeps its name and only the other is an error
    (course_copy / "content/ids.lock").write_text("w:di\n", encoding="utf-8")
    (finding,) = slug_findings(course_copy)
    assert finding.startswith("error: content/items/u00.yaml › items[") and "w:di-letter collides with w:di " in finding
    assert "keeps a plain ID (the released w:di), so w:di-letter needs a ~sense suffix" in finding


def test_unit_spec_task_conversation_must_exist_once_the_task_is_written(course_copy):
    task = course_copy / "content/units/02-al-bar/task.yaml"
    task.write_text(task.read_text(encoding="utf-8").replace("u02.task.conv1", "u02.task.breakfast"), encoding="utf-8")
    found = strs(course_copy)
    assert (
        "error: content/units/02-al-bar/unit.yaml › tasks.conversation[0].id (line 50): "
        "content/units/02-al-bar/task.yaml has no conversation u02.task.conv1"
    ) in found


def test_unit_id_matches_its_folder(course_copy):
    spec = course_copy / "content/units/03-la-famiglia/unit.yaml"
    spec.write_text(spec.read_text(encoding="utf-8").replace("id: u03", "id: u13"), encoding="utf-8")
    assert (
        "error: content/units/03-la-famiglia/unit.yaml › id (line 5): unit ID u13 doesn't match its folder "
        "03-la-famiglia (expected u03)"
    ) in strs(course_copy)


def test_unlisted_unit_folder_and_orphan_items_file(course_copy):
    (course_copy / "content/units/13-extra").mkdir()
    (course_copy / "content/units/13-extra/unit.yaml").write_text("id: u13\n", encoding="utf-8")
    (course_copy / "content/items/u13.yaml").write_text(
        "unit: u13\nreview: {status: draft}\nitems: []\n", encoding="utf-8"
    )
    found = strs(course_copy)
    assert (
        "warning: content/units/13-extra/unit.yaml: unit folder 13-extra is not in content/course.yaml, "
        "so nothing in it is built"
    ) in found
    assert "error: content/items/u13.yaml: there is no unit u13 in content/course.yaml for this items file" in found


def test_ids_lock_accepts_generated_and_retired_ids(course_copy):
    lock = course_copy / "content/ids.lock"
    lock.write_text(
        "\n".join(
            [
                "# released by 0.1.0",
                "u02 0.1.0",
                "u02.l1.step-preview.b1.w-caffe",
                "u02.l1.step-preview.b2.match",
                "u02.step-conversation-1",
                "u02.step-check",
                "gen:recall:w:cornetto",
                "u02.l1.story#22",
                "u02.task.conv1/n3b",
                "ch:narrator",
                "topic:food-drink",
                "us",
                "w:gelato",
                "not an id",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    retired = course_copy / "content/retired.yaml"
    retired.write_text(
        "retired:\n  - {id: 'w:gelato', retired_in: 0.2.0, reason: moved to Unit 10, replaced_by: null}\n",
        encoding="utf-8",
    )
    lock_findings = [str(f) for f in lint_findings(course_copy) if f.file == "content/ids.lock"]
    assert lock_findings == ["error: content/ids.lock (line 14): 'not' is not an ID (docs/03 § IDs)"]


def test_index_resolves_generated_ids_and_lines(seed_root):
    ix = build_index(load_course(seed_root))
    for ref in [
        "u02.l1.step-preview.b2.c-cosa-prende",
        "u02.step-opener",
        "u02.step-talk",
        "u02.step-relay",
        "u02.step-fluency",
        "gen:read:c:vorrei",
        "u02.l1.story#1",
        "u02.check.07/end",
        "u02.check.01.audio#2",
        "narrator",
        "ch:announcer",
    ]:
        assert ix.problem(ref) is None, ref
    assert ix.problem("u02.step-writing") == "missing"  # Unit 2 has no writing task
    assert ix.problem("u02.l1.story#23") == "text u02.l1.story has 22 lines; there is no line 23"
    assert ix.problem("u02.task.conv1/n9") == "conversation u02.task.conv1 has no node 'n9'"


def test_id_helpers():
    assert ids.split_line_ref("u02.l1.story#3") == ("u02.l1.story", 3)
    assert ids.split_line_ref("u02.l1.story") is None
    assert ids.step_kind_of("u02.l1.step-story-2") == "story"
    assert ids.step_kind_of("u02.step-conversation-1") == "conversation"
    assert ids.unit_of("u02.l1.ex07") == "u02" and ids.lesson_of("u02.l1.ex07") == "u02.l1"
    assert ids.unit_from_folder("02-al-bar") == "u02"
    assert ids.base_of("w:pesca~fruit") == "w:pesca"
    assert ids.describe("can_do|syllabus") == "can-do or syllabus entry"
    good = {
        "u02.task.conv1.audio": "text",
        "pl.03.audio#1": "text_line",
        "fin.listening.01.audio": "text",
        "u02.task.conv1/n3b": "conversation_node_ref",
        "u02.l1.step-story": "step",
        "u02.step-check": "step",
        "kind:listening": "coverage_ref",
        "format:sound-pair": "coverage_ref",
        "section:structures": "coverage_ref",
        "u02.can_do[1].text": "spec_path",
        "narrator": "speaker",
        "s:double-consonants": "lexical_item",
    }
    for value, kind in good.items():
        assert ids.is_valid(value, kind), (value, kind)
    for value, kind in {"g:articles": "lexical_item", "kind:quiz": "coverage_ref", "u02.l1.step-quiz": "step"}.items():
        assert not ids.is_valid(value, kind), (value, kind)
