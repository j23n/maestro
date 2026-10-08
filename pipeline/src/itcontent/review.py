"""Shared pieces of the content review loop (docs/04 § Content review loop, ADR-22).

The review page (`review_export`), the import (`review_import`), the ledger (`ledger`), answer adjudication
(`adjudication`) and `content lint` all use these: the categories and verdicts the teacher picks from, which files a
review scope covers, the "version hash" a review file records for each file, and how a comment's `target` resolves.

Targets (docs/04 § The review file) are IDs (`u02.l1.ex07`, `w:cornetto`, `ch:giulia`, `us`), text lines
(`u02.l1.story#3`), conversation nodes (`u02.task.conv1/n2`), paths into a spec file (`u02.can_do[1]`, `u02.tasks`,
`story-bible.places[2]`, `countries.other`) and the content questions of docs/13 (`CQ3`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itcontent import approval, ids
from itcontent.course import Course, ExerciseRef, TextRef, walk_course
from itcontent.index import Index

# The categories of a comment, in the order the page and the app show them. The keys are the review file's
# `category` values (schemas/review-file.schema.json lists the same keys; a test checks the schema and the app's
# `ReviewComment.Category` agree with this table).
CATEGORIES: dict[str, str] = {
    "italian-error": "Italian error",
    "naturalness": "Unnatural",
    "level": "Level",
    "answer-key": "Answer key",
    "hint-or-rule": "Hint or rule",
    "english": "English",
    "culture-or-facts": "Culture or facts",
    "audio": "Audio",
    "other": "Other",
}
VERDICTS: dict[str, str] = {"ok": "OK", "change": "Change", "question": "Question"}
# Ledger resolutions. `noted` is set by review-import for an OK verdict with nothing to act on.
RESOLUTIONS: tuple[str, ...] = ("open", "fixed", "answered", "declined", "owner", "noted")
UNRESOLVED: tuple[str, ...] = ("open", "owner")  # these block sign-off and `content approve --signoff`
ADJUDICATIONS: dict[str, str] = {"accept": "Accept", "near": "Near-miss", "wrong": "Wrong"}

SCOPE = re.compile(r"^(?:specs|assessments|u\d{2})$")
DECISIONS = "docs/13-decisions.md"
QUESTION = re.compile(r"^CQ\d+$")
# A path into a spec file: `<file>.<key>[i].<key>…`. `uNN` is the unit spec (docs/03 § Unit spec).
SPEC_FILES = {
    "story-bible": "content/story-bible.yaml",
    "countries": "content/countries.yaml",
    "syllabus": "content/syllabus/a1-syllabus.yaml",
    "points": "content/grammar/points.yaml",
}
SPEC_PATH = re.compile(r"^(u\d{2}|story-bible|countries|syllabus|points)((?:\.[a-z_]+(?:\[\d+\])*)+)$")


def scope_title(scope: str) -> str:
    if scope == "specs":
        return "Sign-off files"
    if scope == "assessments":
        return "Placement and final check"
    if scope == "u99":
        return "Final review"
    return f"Unit {int(scope[1:])}"


# ---------------------------------------------------------------- files and version hashes


def scope_files(course: Course, scope: str) -> list[str]:
    """The files a review page for `scope` shows (and its sign-off covers), in page order."""
    if scope == "specs":
        out = [course.singles[k].rel for k in ("syllabus", "points") if k in course.singles]
        out += [u.spec.rel for u in course.units if u.spec is not None]
        out += [course.singles[k].rel for k in ("story_bible", "countries") if k in course.singles]
        if (course.root / DECISIONS).is_file() and questions(course.root):
            out.append(DECISIONS)
        return out
    if scope == "assessments":
        return [course.assessments[k].rel for k in ("placement", "final") if k in course.assessments]
    unit = course.unit(scope)
    if unit is None:
        return []
    docs = [unit.items, *unit.lessons, unit.task, unit.check]
    return [d.rel for d in docs if d is not None]


def section_text(text: str, heading: str) -> str | None:
    """The markdown section that starts at the `## <heading>` line, up to the next `## ` heading (LF line ends)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and ln[3:].startswith(heading)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).rstrip("\n") + "\n"


QUESTIONS_HEADING = "Content questions"


def version_hash(root: Path, rel: str) -> str | None:
    """The hash a review file records for `rel` (its `files` map): the approval hash for content YAML
    (docs/04 § Approval hash); for docs/13, the sha256 of its content-questions section only, so the decisions
    log can grow without making the teacher's answers stale. None if the file doesn't exist."""
    path = root / rel
    if not path.is_file():
        return None
    if rel == DECISIONS:
        section = section_text(path.read_text(encoding="utf-8"), QUESTIONS_HEADING) or ""
        return hashlib.sha256(section.encode("utf-8")).hexdigest()
    return approval.file_hash(path)


@dataclass(frozen=True)
class Question:
    id: str  # CQ1
    question: str
    default: str


def questions(root: Path) -> list[Question]:
    """The content questions for the content lead (docs/13 § Content questions), from the section's table."""
    path = root / DECISIONS
    if not path.is_file():
        return []
    section = section_text(path.read_text(encoding="utf-8"), QUESTIONS_HEADING) or ""
    out = []
    for line in section.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) >= 3 and QUESTION.match(cells[0]):
            out.append(Question(cells[0], cells[1], cells[2]))
    return out


def fingerprint(data: Any) -> str:
    """A short, stable hash of an element's data: what the page shows. `--since` compares it to mark changes."""
    from itcontent.schemas import to_jsonable

    blob = json.dumps(to_jsonable(data), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- targets


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def resolve_path(node: Any, path: str) -> Any:
    """Walk `.key[i].key` from `node`; None when a step doesn't exist."""
    for part in path.split(".")[1:]:
        m = re.fullmatch(r"([a-z_]+)((?:\[\d+\])*)", part)
        if node is None or not m:
            return None
        node = _map(node).get(m.group(1))
        for idx in re.findall(r"\[(\d+)\]", m.group(2)):
            seq = _seq(node)
            node = seq[int(idx)] if int(idx) < len(seq) else None
    return node


def spec_doc(course: Course, prefix: str) -> tuple[str, Any] | None:
    """(file, data) of the spec file a spec path starts with."""
    if re.fullmatch(r"u\d{2}", prefix):
        unit = course.unit(prefix)
        return (unit.spec.rel, unit.spec.data) if unit and unit.spec else None
    rel = SPEC_FILES.get(prefix)
    doc = next((d for d in course.all_docs() if d.rel == rel), None)
    return (doc.rel, doc.data) if doc else None


def target_file(course: Course, index: Index, target: str) -> str | None:
    """The file a target lives in, or None when it doesn't resolve."""
    if target_problem(course, index, target) is not None:
        return None
    if QUESTION.match(target):
        return DECISIONS
    m = SPEC_PATH.match(target)
    if m and not (ids.kind_of(target) and index.exists(target)):
        found = spec_doc(course, m.group(1))
        return found[0] if found else None
    base = target.split("/", 1)[0].split("#", 1)[0]
    if base.startswith("gen:"):
        base = base.split(":", 2)[2]
    d = index.get(base)
    return d.loc.file if d else None


def target_problem(course: Course, index: Index, target: str) -> str | None:
    """None if `target` names something that exists, else why not (for import and lint messages)."""
    if QUESTION.match(target):
        return (
            None
            if any(q.id == target for q in questions(course.root))
            else f"no content question {target} in {DECISIONS}"
        )
    if ids.kind_of(target) is not None and index.exists(target):
        return None
    m = SPEC_PATH.match(target)
    if m:
        found = spec_doc(course, m.group(1))
        if found is None:
            return f"unknown target '{target}': there is no spec file for '{m.group(1)}'"
        return None if resolve_path(found[1], target) is not None else f"unknown target '{target}' in {found[0]}"
    if ids.kind_of(target) is not None:
        problem = index.problem(target)
        return f"unknown target '{target}'" if problem in (None, "missing") else f"target '{target}': {problem}"
    return f"unknown target '{target}' (not an ID, a text line, a conversation node, a spec path or a question)"


# ---------------------------------------------------------------- finding exercises and texts by ID


def find_exercise(course: Course, exercise_id: str) -> ExerciseRef | None:
    return next((x for x in walk_course(course) if isinstance(x, ExerciseRef) and x.id == exercise_id), None)


def find_text(course: Course, text_id: str) -> TextRef | None:
    return next((x for x in walk_course(course) if isinstance(x, TextRef) and x.id == text_id), None)


def unit_of_comment(target: str, file: str | None) -> str:
    """The unit a comment belongs to in `content report` (`specs` for sign-off files, `assessments`)."""
    if file:
        m = re.match(r"^content/units/(\d{2})-[^/]+/(?!unit\.yaml$)", file)
        if m:
            return f"u{m.group(1)}"
        m = re.match(r"^content/items/(u\d{2})\.yaml$", file)
        if m:
            return m.group(1)
        if file.startswith("content/assessments/"):
            return "assessments"
        return "specs"
    unit = ids.unit_of(target)
    return unit or "specs"


def load_json(path: Path) -> tuple[Any, str | None]:
    """(data, problem) for a review file."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path}: can't read it ({exc})"
    except json.JSONDecodeError as exc:
        return None, f"{path}: not a review file: line {exc.lineno}: {exc.msg}"
