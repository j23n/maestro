"""M1.1: JSON Schemas for every content type, review files and ledgers; `lint` maps files to them by path.

Each invalid fixture in fixtures/invalid/ is placed at a target path in a copy of the seed course; the test expects the
exact finding line, which names the file, the YAML path, the line and the problem.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from itcontent import ids, schemas
from itcontent.cli import app
from itcontent.lint import content_files, lint_findings, run_lint

LESSON = "content/units/03-la-famiglia/lesson-1.yaml"
E = "error: " + LESSON

# fixture → (target path, expected finding lines)
CASES: dict[str, tuple[str, list[str]]] = {
    "lesson-unknown-step-kind.yaml": (
        LESSON,
        [
            f"{E} › steps[0].kind (line 6): unknown step kind 'quiz' "
            "(allowed: preview, story, listening, reading, note, practice, sounds, use)"
        ],
    ),
    "lesson-missing-targets.yaml": (
        LESSON,
        [f"{E} › steps[0].block[0] (line 9): missing required key 'targets' (format cloze)"],
    ),
    "lesson-missing-tags.yaml": (
        LESSON,
        [f"{E} › steps[0].block[0] (line 9): missing required key 'tags' (format recall)"],
    ),
    "lesson-unknown-format.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].format (line 10): unknown format 'fill-in' (docs/06: cloze, recall, "
            "sentence-building, dictation, sound-pair, repeat, choice, true-false, match, conversation, talk, "
            "writing, relay)"
        ],
    ),
    "lesson-unknown-key.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].prompt_eng (line 14): unknown key 'prompt_eng' (format recall); allowed: answer, "
            "audio_after, context_it, format, hint, id, lemmas, near, prompt_en, rule, score, source, tags, targets"
        ],
    ),
    "lesson-format-not-allowed.yaml": (
        LESSON,
        [f"{E} › steps[0].exercises[0].format (line 10): format 'repeat' isn't allowed here (allowed: sound-pair)"],
    ),
    "lesson-bad-id.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].id (line 9): "
            "'u03.l1.ex1' is not a valid exercise ID like u02.l1.ex07 (docs/03 § IDs)"
        ],
    ),
    "lesson-wrong-type.yaml": (
        LESSON,
        [f"{E} › steps[0].block[0].answer (line 15): expected integer, got string (good)"],
    ),
    "lesson-cloze-two-gaps.yaml": (
        LESSON,
        [
            f"{E} › steps[0].block[0].text (line 13): a cloze text needs exactly one gap [[…]]: "
            "'Vorrei [[un]] caffè e [[una]] spremuta.'"
        ],
    ),
    "lesson-register-without-to.yaml": (
        LESSON,
        [f"{E} › steps[0].text.lines[0] (line 12): 'register' needs 'to' as well"],
    ),
    "lesson-approved-without-hash.yaml": (
        LESSON,
        [
            f"{E} › review.date (line 4): an approved file needs review.date (set by content approve)",
            f"{E} › review.hash (line 4): an approved file needs review.hash (set by content approve)",
        ],
    ),
    "lesson-yaml-parse-error.yaml": (
        LESSON,
        [E + " (line 4): does not parse: expected ',' or '}', but got '<scalar>' (while parsing a flow mapping)"],
    ),
    "items-noun-without-gender.yaml": (
        "content/items/u03.yaml",
        [
            "error: content/items/u03.yaml › items[0] (line 5): "
            "a noun needs gender and plural (plural: invariable if it doesn't change)"
        ],
    ),
    "detection-bad-regex.yaml": (
        "content/grammar/detection.yaml",
        [
            "error: content/grammar/detection.yaml › rules[0].detect[0].seq[0].form (line 6): "
            "'^(un|uno|una|un'$' is not a valid regular expression (missing ), unterminated subpattern at position 1)"
        ],
    ),
    "voices-hd-voice.yaml": (
        "content/voices.yaml",
        [
            "error: content/voices.yaml › voices.narrator.voice (line 3): "
            "'it-IT-Isabella:DragonHDLatestNeural' is not a standard neural voice name like it-IT-ElsaNeural "
            "(HD voices can't be used, ADR-07)",
            "error: content/voices.yaml › voices.marco (line 4): unknown key 'marco'; "
            "allowed: narrator, announcer, items, ch:<character>, ch:you (m and f voices), ch:extra (a pool)",
        ],
    ),
    "stray-file.yaml": (
        "content/units/02-al-bar/notes.yaml",
        [
            "warning: content/units/02-al-bar/notes.yaml: no schema covers this file; is it in the right place? "
            "(docs/03 § Files)"
        ],
    ),
    "ledger-bad-resolution.yaml": (
        "reviews/u02.yaml",
        [
            "error: reviews/u02.yaml › comments[0].resolution.status (line 14): "
            "'done' is not a valid resolution status (allowed: open, fixed, answered, declined, owner, noted)",
            "error: reviews/u02.yaml › comments[1].resolution.note (line 22): "
            "an answered, declined or owner resolution needs a note for the teacher",
        ],
    ),
    "review-file-bad-verdict.json": (
        "reviews/inbox/review-u02-2026-10-20.json",
        [
            "error: reviews/inbox/review-u02-2026-10-20.json › files.content/units/02-al-bar/lesson-1.yaml (line 7): "
            "'not-a-hash' is not an approval hash (sha256 hex, docs/04 § Approval hash)",
            "error: reviews/inbox/review-u02-2026-10-20.json › comments[0].verdict (line 14): "
            "'maybe' is not a valid verdict (allowed: ok, change, question)",
        ],
    ),
}


@pytest.mark.parametrize("fixture", sorted(CASES))
def test_invalid_fixture_reports_file_path_line_and_problem(fixture, course_copy, place):
    target, expected = CASES[fixture]
    place(fixture, target)
    found = [str(f) for f in lint_findings(course_copy)]
    for line in expected:
        assert line in found, "\n".join(found)


def test_live_course_has_no_schema_findings(root):
    findings = [f for f in lint_findings(root) if f.level != "pending"]
    assert findings == [], "\n".join(map(str, findings))


def test_every_content_file_maps_to_a_schema(root):
    for p in content_files(root):
        rel = p.relative_to(root).as_posix()
        assert schemas.schema_for(rel), rel
    assert schemas.schema_for("reviews/u02.yaml") == "review-ledger"
    assert schemas.schema_for("reviews/inbox/review-u02-2026-10-20.json") == "review-file"
    assert schemas.schema_for("content/units/02-al-bar/notes.yaml") is None


def test_every_schema_is_valid_draft_2020_12_and_loads():
    names = schemas.schema_names()
    assert {"lesson", "task", "check", "unit", "items", "review-file", "review-ledger", "exercises/cloze"} <= set(names)
    for name in names:
        doc = json.loads((schemas.SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(doc)
        assert doc["$id"].endswith(f"/schemas/{name}.schema.json"), name
        schemas.validator(name)
    schemas.format_checker()  # every `id:` format names kinds that exist in ids.PATTERNS


def test_one_schema_per_exercise_format_and_enums_match_ids():
    for fmt in ids.FORMATS:
        doc = json.loads((schemas.SCHEMA_DIR / "exercises" / f"{fmt}.schema.json").read_text(encoding="utf-8"))
        assert doc["properties"]["format"] == {"const": fmt}
    dispatch = json.loads((schemas.SCHEMA_DIR / "exercise.schema.json").read_text(encoding="utf-8"))
    assert tuple(dispatch["properties"]["format"]["enum"]) == ids.FORMATS
    lesson = json.loads((schemas.SCHEMA_DIR / "lesson.schema.json").read_text(encoding="utf-8"))
    assert tuple(lesson["$defs"]["step"]["properties"]["kind"]["enum"]) == ids.LESSON_STEP_KINDS
    common = json.loads((schemas.SCHEMA_DIR / "common.schema.json").read_text(encoding="utf-8"))
    assert tuple(common["$defs"]["skill"]["enum"]) == ids.SKILL_LIST
    final = json.loads((schemas.SCHEMA_DIR / "final-check.schema.json").read_text(encoding="utf-8"))
    assert tuple(final["properties"]["sections"]["items"]["properties"]["id"]["enum"]) == ids.SECTIONS


def test_id_formats_come_from_ids_py():
    """The schemas check IDs with ids.is_valid, so a pattern change in ids.py reaches every schema."""
    data = {"unit": "u02", "review": {"status": "draft"}, "items": [{"id": "w:Caffè"}]}
    msgs = [m for _, m in schemas.validate("items", data)]
    assert "'w:Caffè' is not a valid word, chunk or sound ID like w:cornetto (docs/03 § IDs)" in msgs


def test_yaml_dates_validate_as_iso_strings():
    """An unquoted YAML date loads as a date object; the schemas see it as its ISO string."""
    review = {"status": "approved", "by": "A. Teacher", "date": dt.date(2026, 10, 7), "hash": "0" * 64}
    country = {"id": "ca", "en": "Canada", "it": "Canada", "home_phrase": "in Canada", "m": "canadese", "f": "canadese"}
    assert schemas.validate("countries", {"review": review, "countries": [country], "other": {"en": "Other"}}) == []
    review["date"] = "7 Oct 2026"
    assert schemas.validate("countries", {"review": review, "countries": [country], "other": {"en": "Other"}}) == [
        (("review", "date"), "'7 Oct 2026' is not a date like 2026-10-07")
    ]


def test_lint_json_output(course_copy, place):
    place("lesson-missing-tags.yaml", LESSON)
    lines: list[str] = []
    assert run_lint(course_copy, echo=lines.append, as_json=True) == 1
    out = json.loads("\n".join(lines))
    assert out["summary"]["error"] >= 1
    f = next(f for f in out["findings"] if f["message"].startswith("missing required key 'tags'"))
    assert f == {
        "level": "error",
        "file": LESSON,
        "path": "steps[0].block[0]",
        "keys": ["steps", 0, "block", 0],
        "line": 9,
        "message": "missing required key 'tags' (format recall)",
    }


def test_cli_lint_json_on_the_live_course(root):
    result = CliRunner().invoke(app, ["lint", "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["summary"]["error"] == 0
