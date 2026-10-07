"""Load the whole course from `content/` and walk its structures (docs/03 § Files).

This is the one traversal of the YAML shapes that lint, annotate, check and build share. Documents are plain dicts
and lists (YAML 1.2 safe load); each walker yields a `Loc` (file + path inside the document) so every error message
can name the file, the path and, through `yamlio.locate`, the line.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths, yamlio

PathT = tuple[str | int, ...]


@dataclass(frozen=True)
class Loc:
    """Where something is: a repo-relative file and a path inside its YAML document."""

    file: str
    path: PathT = ()

    def child(self, *keys: str | int) -> Loc:
        return Loc(self.file, self.path + keys)

    def __str__(self) -> str:
        out = ""
        for p in self.path:
            out += f"[{p}]" if isinstance(p, int) else (("." if out else "") + str(p))
        return f"{self.file}{(' › ' + out) if out else ''}"


@dataclass
class Doc:
    """One loaded YAML file."""

    path: Path
    rel: str
    data: Any

    @property
    def loc(self) -> Loc:
        return Loc(self.rel)


@dataclass
class UnitFiles:
    """Everything in `content/units/NN-slug/` plus the unit's items file."""

    slug: str
    dir: Path
    spec: Doc | None
    lessons: list[Doc] = field(default_factory=list)  # lesson-1.yaml … in K order (only the files that exist)
    task: Doc | None = None
    check: Doc | None = None
    items: Doc | None = None

    @property
    def id(self) -> str:
        if self.spec and isinstance(self.spec.data, dict) and self.spec.data.get("id"):
            return str(self.spec.data["id"])
        return "u" + self.slug.split("-", 1)[0]

    @property
    def lesson_count(self) -> int:
        if self.spec and isinstance(self.spec.data, dict):
            return int(self.spec.data.get("lessons") or 0)
        return 0

    @property
    def is_final_review(self) -> bool:
        return self.id == "u99"

    @property
    def complete(self) -> bool:
        """docs/04 § Partial content: every lesson-K.yaml, task.yaml and check.yaml exist (u99: no check file)."""
        have = {d.path.name for d in self.lessons}
        want = {f"lesson-{k}.yaml" for k in range(1, self.lesson_count + 1)}
        if not want or not want <= have:
            return False
        if self.is_final_review:
            return True
        return self.task is not None and self.check is not None

    def files(self) -> list[Doc]:
        out = [d for d in (self.spec, *self.lessons, self.task, self.check, self.items) if d is not None]
        return out


@dataclass
class Course:
    root: Path
    course: Doc
    units: list[UnitFiles]  # in course.yaml order
    singles: dict[str, Doc]  # checker, syllabus, points, detection, story_bible, voices, countries, allowlist, …
    assessments: dict[str, Doc]  # placement, final
    load_errors: list[tuple[str, str]] = field(default_factory=list)  # (rel file, message)

    # ---------------------------------------------------------------- lookups

    def unit(self, unit_id: str) -> UnitFiles | None:
        return next((u for u in self.units if u.id == unit_id), None)

    def unit_order(self) -> dict[str, int]:
        return {u.id: i for i, u in enumerate(self.units)}

    def items(self) -> Iterator[tuple[UnitFiles, int, dict[str, Any]]]:
        """Every item entry of every items/uNN.yaml, in course order."""
        for u in self.units:
            if u.items and isinstance(u.items.data, dict):
                for i, item in enumerate(u.items.data.get("items") or []):
                    if isinstance(item, dict):
                        yield u, i, item

    def item_map(self) -> dict[str, dict[str, Any]]:
        return {str(it["id"]): it for _, _, it in self.items() if it.get("id")}

    def grammar_points(self) -> list[dict[str, Any]]:
        d = self.singles.get("points")
        return list((d.data or {}).get("points") or []) if d else []

    def detection_rules(self) -> list[dict[str, Any]]:
        d = self.singles.get("detection")
        return list((d.data or {}).get("rules") or []) if d else []

    def all_docs(self) -> list[Doc]:
        out = [self.course, *self.singles.values(), *self.assessments.values()]
        for u in self.units:
            out.extend(u.files())
        return sorted(out, key=lambda d: d.rel)


SINGLES = {
    "checker": "checker.yaml",
    "syllabus": "syllabus/a1-syllabus.yaml",
    "points": "grammar/points.yaml",
    "detection": "grammar/detection.yaml",
    "story_bible": "story-bible.yaml",
    "voices": "voices.yaml",
    "countries": "countries.yaml",
    "allowlist": "allowlist.yaml",
    "disambiguation": "disambiguation.yaml",
    "pronunciation": "pronunciation.yaml",
    "retired": "retired.yaml",
}
ASSESSMENTS = {"placement": "assessments/placement.yaml", "final": "assessments/final-check.yaml"}


def _load(root: Path, rel: str, errors: list[tuple[str, str]]) -> Doc | None:
    p = root / rel
    if not p.is_file():
        return None
    try:
        return Doc(p, p.relative_to(root).as_posix(), yamlio.load(p))
    except yamlio.ContentYAMLError as exc:
        errors.append((p.relative_to(root).as_posix(), str(exc)))
        return None


def load_course(root: Path | None = None) -> Course:
    root = (root or paths.ROOT).resolve()
    errors: list[tuple[str, str]] = []
    course = _load(root, "content/course.yaml", errors)
    if course is None:
        raise SystemExit(f"{root}/content/course.yaml is missing or does not parse: {errors}")
    singles = {k: d for k, rel in SINGLES.items() if (d := _load(root, f"content/{rel}", errors)) is not None}
    assessments = {k: d for k, rel in ASSESSMENTS.items() if (d := _load(root, f"content/{rel}", errors)) is not None}
    units = []
    for slug in (course.data or {}).get("units") or []:
        udir = root / "content" / "units" / str(slug)
        spec = _load(root, f"content/units/{slug}/unit.yaml", errors)
        uf = UnitFiles(slug=str(slug), dir=udir, spec=spec)
        lesson_paths = sorted(
            udir.glob("lesson-*.yaml"),
            key=lambda p: int(p.stem.split("-")[1]) if p.stem.split("-")[1].isdigit() else 999,
        )
        for lp in lesson_paths:
            d = _load(root, lp.relative_to(root).as_posix(), errors)
            if d is not None:
                uf.lessons.append(d)
        uf.task = _load(root, f"content/units/{slug}/task.yaml", errors)
        uf.check = _load(root, f"content/units/{slug}/check.yaml", errors)
        uf.items = _load(root, f"content/items/{uf.id}.yaml", errors)
        units.append(uf)
    return Course(root=root, course=course, units=units, singles=singles, assessments=assessments, load_errors=errors)


# ---------------------------------------------------------------- walking lessons, tasks, checks


@dataclass(frozen=True)
class ExerciseRef:
    """One exercise as authored, with where it sits."""

    data: dict[str, Any]
    loc: Loc
    unit_id: str
    container: str  # lesson | task | check | placement | final
    step_id: str | None  # lesson step, or None (task/check exercises map to unit-level steps at build time)
    step_kind: str | None
    role: str  # learn | check | placement | final | comprehension
    section: str | None = None  # check/final section id
    part: str | None = None  # practice: block | mix

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))

    @property
    def format(self) -> str:
        return str(self.data.get("format", ""))


@dataclass(frozen=True)
class TextRef:
    """One text (story, listening, reading, inline source or audio text) with where it sits."""

    data: dict[str, Any]
    loc: Loc
    unit_id: str
    step_id: str | None
    owner: str  # step | exercise-audio | exercise-source | relay-source
    exercise_id: str | None = None

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))


def lesson_steps(doc: Doc) -> Iterator[tuple[int, dict[str, Any]]]:
    for i, step in enumerate((doc.data or {}).get("steps") or []):
        if isinstance(step, dict):
            yield i, step


def _exercise_texts(ex: dict[str, Any], loc: Loc, unit_id: str, step_id: str | None) -> Iterator[TextRef]:
    ex_id = str(ex.get("id", ""))
    at = ex.get("audio_text")
    if isinstance(at, dict):
        yield TextRef(at, loc.child("audio_text"), unit_id, step_id, "exercise-audio", ex_id)
    src = ex.get("source")
    if isinstance(src, dict):
        if isinstance(src.get("text"), dict):
            yield TextRef(src["text"], loc.child("source", "text"), unit_id, step_id, "exercise-source", ex_id)
        if isinstance(src.get("audio_text"), dict):
            yield TextRef(
                src["audio_text"], loc.child("source", "audio_text"), unit_id, step_id, "exercise-source", ex_id
            )


def walk_lesson(doc: Doc, unit_id: str) -> Iterator[ExerciseRef | TextRef]:
    for i, step in lesson_steps(doc):
        sloc = doc.loc.child("steps", i)
        kind = step.get("kind")
        sid = step.get("id")
        if kind in ("story", "listening", "reading") and isinstance(step.get("text"), dict):
            yield TextRef(step["text"], sloc.child("text"), unit_id, sid, "step")
        lists: list[tuple[str, str | None]] = []
        if kind == "story":
            lists.append(("questions", None))
        if kind in ("listening", "reading", "sounds"):
            lists.append(("exercises", None))
        if kind == "practice":
            lists += [("block", "block"), ("mix", "mix")]
        for key, part in lists:
            for j, ex in enumerate(step.get(key) or []):
                if not isinstance(ex, dict):
                    continue
                eloc = sloc.child(key, j)
                role = (
                    "comprehension"
                    if (kind == "story" or (kind in ("listening", "reading") and not ex.get("targets")))
                    else "learn"
                )
                yield ExerciseRef(ex, eloc, unit_id, "lesson", sid, kind, role, part=part)
                yield from _exercise_texts(ex, eloc, unit_id, sid)
        if kind == "use" and isinstance(step.get("exercise"), dict):
            ex = step["exercise"]
            eloc = sloc.child("exercise")
            yield ExerciseRef(ex, eloc, unit_id, "lesson", sid, kind, "learn")
            yield from _exercise_texts(ex, eloc, unit_id, sid)


def walk_task(doc: Doc, unit_id: str) -> Iterator[ExerciseRef | TextRef]:
    data = doc.data or {}
    for j, ex in enumerate(data.get("conversations") or []):
        if isinstance(ex, dict):
            eloc = doc.loc.child("conversations", j)
            yield ExerciseRef(ex, eloc, unit_id, "task", None, "conversation", "learn")
            yield from _exercise_texts(ex, eloc, unit_id, None)
    for key in ("talk", "writing", "relay"):
        ex = data.get(key)
        if isinstance(ex, dict):
            eloc = doc.loc.child(key)
            yield ExerciseRef(ex, eloc, unit_id, "task", None, key, "learn")
            if key == "relay" and isinstance(ex.get("source"), dict) and isinstance(ex["source"].get("text"), dict):
                yield TextRef(
                    ex["source"]["text"], eloc.child("source", "text"), unit_id, None, "relay-source", str(ex.get("id"))
                )
                at = ex["source"].get("audio_text")
                if isinstance(at, dict):
                    yield TextRef(
                        at, eloc.child("source", "audio_text"), unit_id, None, "relay-source", str(ex.get("id"))
                    )
            elif key != "relay":
                yield from _exercise_texts(ex, eloc, unit_id, None)
            elif isinstance(ex.get("source"), dict) and isinstance(ex["source"].get("audio_text"), dict):
                yield TextRef(
                    ex["source"]["audio_text"],
                    eloc.child("source", "audio_text"),
                    unit_id,
                    None,
                    "relay-source",
                    str(ex.get("id")),
                )


def walk_check(doc: Doc, unit_id: str, container: str = "check") -> Iterator[ExerciseRef | TextRef]:
    role = {"check": "check", "final": "final", "placement": "placement"}[container]
    data = doc.data or {}
    groups = data.get("sections") or data.get("blocks") or []
    group_key = "sections" if data.get("sections") is not None else "blocks"
    for s, sec in enumerate(groups):
        if not isinstance(sec, dict):
            continue
        section = str(sec.get("id") or sec.get("unit") or s)
        for j, ex in enumerate(sec.get("exercises") or []):
            if isinstance(ex, dict):
                eloc = doc.loc.child(group_key, s, "exercises", j)
                yield ExerciseRef(ex, eloc, unit_id, container, None, None, role, section=section)
                yield from _exercise_texts(ex, eloc, unit_id, None)


def walk_unit(u: UnitFiles) -> Iterator[ExerciseRef | TextRef]:
    for doc in u.lessons:
        yield from walk_lesson(doc, u.id)
    if u.task:
        yield from walk_task(u.task, u.id)
    if u.check:
        yield from walk_check(u.check, u.id)


def walk_course(course: Course) -> Iterator[ExerciseRef | TextRef]:
    for u in course.units:
        yield from walk_unit(u)
    if "placement" in course.assessments:
        yield from walk_check(course.assessments["placement"], "u00", "placement")
    if "final" in course.assessments:
        yield from walk_check(course.assessments["final"], "u99", "final")


def exercises(course: Course) -> Iterator[ExerciseRef]:
    return (x for x in walk_course(course) if isinstance(x, ExerciseRef))


def texts(course: Course) -> Iterator[TextRef]:
    return (x for x in walk_course(course) if isinstance(x, TextRef))
