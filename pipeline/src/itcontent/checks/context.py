"""What checks 1–5 share (docs/04 § The ten quality checks): the course, its annotation lock files read back as
strings and tokens, course positions, and where every item and grammar point is introduced.

**The lock files are the input.** `content check` never re-annotates: it reads `content/.annotations/**.json`
(`make check-content` runs `annotate --check` first, so they are fresh). As a guard, each lock file is compared with
the strings `annotate` would collect from its YAML today (path, role and text, in order); a lock file that is missing,
left over or out of step is an error ("run `make annotate`") and its file is not checked further. Changes that only
alter how strings resolve (an items file, the allowlist) are caught by `annotate --check`, not here.

**Course positions** (`Pos`) order everything a learner meets (docs/06 § Unit-level steps): `(unit index, rank,
step index)` with rank 0 for the opener, K for lesson K's steps, 900 + N for task conversation N (talk, writing and
relay follow), 950 for the unit check, 960 for a placement block (at the unit it tests: its exercises may use that
unit's material) and 990 for fluency. The final check sits at the final review unit's check.

**Introductions** follow docs/05 § Introductions (preview, story/listening/reading `new` tokens, notes, sounds steps,
and R/chunk points through an exemplifying preview chunk or a story detection in their own unit), with the
partial-content fallbacks of docs/04: an item whose `lesson` isn't written yet, or a grammar point whose note isn't
written yet, counts as introduced at the start of its unit. Written content that relies on a fallback gets a warning
(one per missing lesson, one per unit for grammar points).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import annotate, ids, paths
from itcontent.course import (
    Course,
    Doc,
    ExerciseRef,
    Loc,
    NoteRef,
    PathT,
    TextRef,
    UnitFiles,
    lesson_steps,
    load_course,
    walk_check,
    walk_lesson,
    walk_notes,
    walk_task,
)
from itcontent.detection import DetectionRuleError, Detector
from itcontent.findings import Finding, format_path
from itcontent.index import unit_level_steps
from itcontent.morphit import Analysis, parse_tag
from itcontent.resolve import lesson_k
from itcontent.tokenize import WORD, fold

Pos = tuple[int, int, int]

OPENER, TASK, CHECK, PLACEMENT, FLUENCY = 0, 900, 950, 960, 990
TASK_RANKS = {"talk": TASK + 1, "writing": TASK + 2, "relay": TASK + 3}
SKILLS = ("read", "listen", "recall", "speak")
TEXT_STEPS = ("story", "listening", "reading")

# token flags (docs/03 § Annotation lock files)
NEW = "new"
RECOGNISE = "recognise"
LEXICAL_ARTICLE = "lexical_article"
ALLOWLISTED = "allowlisted"
SYNTHETIC = "synthetic"
SOUND = "sound"
UNRESOLVED = "unresolved"
PENDING = "pending"


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


# ---------------------------------------------------------------- findings


@dataclass(frozen=True)
class CheckFinding(Finding):
    """A check finding: a lint-style finding plus the check (1–5) and rule that produced it."""

    check: int = 0
    rule: str = ""
    unit: str = ""  # the unit the finding is about ("" = course-wide); `content check --unit` filters on it

    @property
    def label(self) -> str:
        return f"check {self.check} · {self.rule}" if self.rule else f"check {self.check}"

    def __str__(self) -> str:
        loc = f"{self.file}{(' › ' + self.where) if self.where else ''}"
        line = f" (line {self.line})" if self.line else ""
        return f"{self.level}: {loc}{line}: {self.label}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        return {**super().as_dict(), "check": self.check, "rule": self.rule, "unit": self.unit or None}


# ---------------------------------------------------------------- annotated strings


@dataclass(frozen=True)
class Tok:
    """One token of a lock file string."""

    i: int
    surface: str
    kind: str
    analyses: tuple[Analysis, ...] = ()
    item: str | None = None
    chunk: str | None = None
    head: int | None = None
    flags: frozenset[str] = frozenset()
    gloss: str | None = None

    @property
    def norm(self) -> str:
        return fold(self.surface)

    @property
    def is_word(self) -> bool:
        return self.kind == WORD

    @property
    def ref(self) -> str | None:
        """The word or chunk item this token stands for (a lexical article stands for its noun)."""
        if self.chunk:
            return self.chunk
        return self.item if self.item and self.item.startswith(("w:", "c:")) else None


@dataclass(frozen=True)
class Det:
    point: str
    start: int
    end: int


@dataclass
class Str:
    """One annotated string (a lock-file entry) with everything the checks need to know about where it sits."""

    file: str
    path: PathT
    role: str
    text: str
    tokens: list[Tok]
    detections: list[Det]
    container: str  # lesson | task | check | placement | final | unit | items
    unit: str  # the unit the string belongs to (a placement block's unit)
    ref: str | None = None
    model: bool | None = None
    index: int | None = None
    gap: tuple[int, int] | None = None
    pos: Pos | None = None
    step: str | None = None
    lesson: str | None = None
    text_ref: TextRef | None = None
    exercise: ExerciseRef | None = None
    note: NoteRef | None = None
    line: dict[str, Any] | None = None  # the text line of a `line` string

    @property
    def loc(self) -> Loc:
        return Loc(self.file, self.path)

    @property
    def where(self) -> str:
        return format_path(self.path)


def parse_analysis(text: str, synthetic: bool = False) -> Analysis:
    lemma, _, tag = text.rpartition(" ")
    cat, feats = parse_tag(tag)
    return Analysis(lemma, cat, feats, synthetic=synthetic)


def _tok(i: int, t: dict[str, Any]) -> Tok:
    flags = frozenset(str(f) for f in t.get("flags") or ())
    synthetic = SYNTHETIC in flags
    return Tok(
        i=i,
        surface=str(t.get("surface", "")),
        kind=str(t.get("kind", "")),
        analyses=tuple(parse_analysis(str(a), synthetic) for a in t.get("analyses") or ()),
        item=t.get("item"),
        chunk=t.get("chunk"),
        head=t.get("head"),
        flags=flags,
        gloss=t.get("gloss"),
    )


# ---------------------------------------------------------------- steps and positions


@dataclass(frozen=True)
class Step:
    id: str
    kind: str
    pos: Pos
    unit: str
    lesson: str | None = None
    data: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
    loc: Loc | None = None


LESSON_STEP = re.compile(r"^(u\d{2})\.l(\d+)\.step-[a-z]+(?:-\d+)?$")
UNIT_STEP = re.compile(r"^(u\d{2})\.step-([a-z]+)(?:-(\d+))?$")


@dataclass(frozen=True)
class Place:
    pos: Pos | None
    step: str | None
    lesson: str | None
    unit: str


# ---------------------------------------------------------------- introductions


@dataclass(frozen=True)
class Intro:
    pos: Pos
    step: str  # the step that introduces, or `uNN.step-opener` for the start-of-unit fallback
    via: str  # preview | story | note | sounds | unit-start | lesson-start
    skills: frozenset[str]

    @property
    def fallback(self) -> bool:
        return self.via in ("unit-start", "lesson-start")


class Introductions:
    """Where each item and grammar point is introduced, per skill."""

    def __init__(self) -> None:
        self.by_ref: dict[str, list[Intro]] = {}

    def add(self, ref: str, intro: Intro) -> None:
        lst = self.by_ref.setdefault(ref, [])
        if intro not in lst:
            lst.append(intro)
            lst.sort(key=lambda x: (x.pos, x.fallback))

    def find(self, ref: str, pos: Pos, skill: str | None = None) -> Intro | None:
        """The first introduction of `ref` at or before `pos` (for `skill`, if given); written ones win ties."""
        for x in self.by_ref.get(ref, ()):
            if x.pos <= pos and (skill is None or skill in x.skills):
                return x
        return None

    def first(self, ref: str, skill: str | None = None) -> Intro | None:
        for x in self.by_ref.get(ref, ()):
            if skill is None or skill in x.skills:
                return x
        return None

    def written(self, ref: str) -> list[Intro]:
        return [x for x in self.by_ref.get(ref, ()) if not x.fallback]


def item_skills(status: Any) -> dict[str, str]:
    """`status: P` → every skill P; `{read: P, recall: R}` → those skills."""
    if isinstance(status, str):
        return dict.fromkeys(SKILLS, status)
    if isinstance(status, dict):
        return {str(k): str(v) for k, v in status.items() if k in SKILLS}
    return {}


def preview_skills(status: Any) -> frozenset[str]:
    """docs/05: a preview (or placement) introduces read and listen, plus recall and speak where that skill is P."""
    st = item_skills(status)
    return frozenset({"read", "listen"} | {s for s in ("recall", "speak") if st.get(s) == "P"})


# ---------------------------------------------------------------- the context


@dataclass
class FallbackUse:
    """Written content that relies on a start-of-unit fallback introduction (reported as one warning per group)."""

    refs: dict[str, int] = field(default_factory=dict)  # item or point → number of uses
    first: Loc | None = None


class CheckContext:
    """Everything checks 1–5 read, built once per run."""

    def __init__(self, root: Path, course: Course) -> None:
        self.root = root
        self.course = course
        self.findings: list[CheckFinding] = []
        self._lines = None
        self.unit_index = course.unit_order()
        self.unit_ids = [u.id for u in course.units]
        self.items: dict[str, dict[str, Any]] = {}
        self.item_unit: dict[str, str] = {}
        self.item_loc: dict[str, Loc] = {}
        for u, i, it in course.items():
            if isinstance(it.get("id"), str):
                self.items[it["id"]] = it
                self.item_unit[it["id"]] = u.id
                if u.items:
                    self.item_loc[it["id"]] = u.items.loc.child("items", i)
        self.points: dict[str, dict[str, Any]] = {}
        self.point_loc: dict[str, Loc] = {}
        pdoc = course.singles.get("points")
        for i, p in enumerate(course.grammar_points()):
            if isinstance(p.get("id"), str):
                self.points[p["id"]] = p
                if pdoc:
                    self.point_loc[p["id"]] = pdoc.loc.child("points", i)
        try:
            self.detector = Detector(course.detection_rules())
        except DetectionRuleError as exc:
            self.detector = Detector([])
            self.add("error", 2, "rules", Loc("content/grammar/detection.yaml"), str(exc))
        checker = course.singles.get("checker")
        self.checker: dict[str, Any] = _map(checker.data) if checker else {}
        self.steps: dict[str, Step] = {}
        self.pos_step: dict[Pos, str] = {}
        self.strings: list[Str] = []
        self.files: dict[str, tuple[Doc, str, str]] = {}  # rel → (doc, kind, unit id) of every annotatable file
        self.checked_files: set[str] = set()  # files whose lock is fresh
        self.intros = Introductions()
        self.lesson_targets: dict[str, tuple[int, frozenset[str]]] = {}
        self.fallback_items: dict[str, FallbackUse] = {}  # missing lesson → uses
        self.fallback_points: dict[str, FallbackUse] = {}  # unit → uses
        self._build_steps()
        self._load_strings()
        self._build_introductions()

    # ------------------------------------------------------------ findings

    def add(self, level: str, check: int, rule: str, loc: Loc, message: str, *, unit: str | None = None) -> None:
        self.findings.append(
            CheckFinding(
                level,
                loc.file,
                format_path(loc.path),
                message,
                None,
                tuple(loc.path),
                check=check,
                rule=rule,
                unit=unit if unit is not None else self.unit_of_file(loc.file),
            )
        )

    def unit_of_file(self, rel: str) -> str:
        """`content/units/02-al-bar/…` and `content/items/u02.yaml` (and their lock files) → `u02`; else ""."""
        m = re.match(r"^content/(?:\.annotations/)?units/([^/]+)/", rel)
        if m:
            for u in self.course.units:
                if u.slug == m.group(1):
                    return u.id
            return ids.unit_from_folder(m.group(1))
        m = re.match(r"^content/(?:\.annotations/)?items/(u\d{2})\.", rel)
        return m.group(1) if m else ""

    def line_of(self, file: str, path: PathT) -> int | None:
        if self._lines is None:
            from itcontent.lint import Lines

            self._lines = Lines(self.root)
        return self._lines(file, path)

    def with_lines(self, findings: Iterable[CheckFinding]) -> list[CheckFinding]:
        out = []
        for f in set(findings):
            if f.line is None:
                f = CheckFinding(
                    f.level,
                    f.file,
                    f.where,
                    f.message,
                    self.line_of(f.file, f.path),
                    f.path,
                    f.related,
                    f.check,
                    f.rule,
                    f.unit,
                )
            out.append(f)
        return sorted(out, key=lambda f: (*f.sort_key(), f.check, f.rule))

    # ------------------------------------------------------------ units, items, points

    def unit(self, unit_id: str) -> UnitFiles | None:
        return self.course.unit(unit_id)

    def unit_of_pos(self, pos: Pos) -> str:
        return self.unit_ids[pos[0]] if 0 <= pos[0] < len(self.unit_ids) else "?"

    def point_unit(self, point: str) -> str:
        return str(self.points.get(point, {}).get("unit", ""))

    def point_status(self, point: str) -> str:
        return str(self.points.get(point, {}).get("status", ""))

    def item_status(self, item: str) -> dict[str, str]:
        return item_skills(self.items.get(item, {}).get("status"))

    def written_lessons(self) -> dict[str, tuple[UnitFiles, Doc]]:
        out = {}
        for u in self.course.units:
            for doc in u.lessons:
                lid = _map(doc.data).get("id")
                if isinstance(lid, str):
                    out[lid] = (u, doc)
        return out

    # ------------------------------------------------------------ steps

    def _add_step(self, step: Step) -> None:
        self.steps.setdefault(step.id, step)
        self.pos_step.setdefault(step.pos, step.id)

    def _build_steps(self) -> None:
        for ui, u in enumerate(self.course.units):
            self._add_step(Step(f"{u.id}.step-opener", "opener", (ui, OPENER, 0), u.id))
            for doc in u.lessons:
                lid = str(_map(doc.data).get("id") or f"{u.id}.l{doc.path.stem.split('-')[-1]}")
                k = lesson_k(lid)
                for s, step in lesson_steps(doc):
                    sid = step.get("id")
                    if isinstance(sid, str):
                        loc = doc.loc.child("steps", s)
                        self._add_step(Step(sid, str(step.get("kind", "")), (ui, k, s), u.id, lid, step, loc))
            if u.spec:
                for sid in unit_level_steps(u):
                    pos = self.step_pos(sid)
                    if pos is not None:
                        kind = ids.step_kind_of(sid) or ""
                        self._add_step(Step(sid, kind, pos, u.id))

    def step_pos(self, step_id: str) -> Pos | None:
        """The course position of a step ID; a step of a lesson that isn't written yet sits at that lesson's start."""
        if step_id in self.steps:
            return self.steps[step_id].pos
        m = UNIT_STEP.match(step_id)
        if m and m.group(1) in self.unit_index:
            ui, kind, n = self.unit_index[m.group(1)], m.group(2), int(m.group(3) or 0)
            ranks = {"opener": (OPENER, 0), "conversation": (TASK, n), "check": (CHECK, 0), "fluency": (FLUENCY, 0)}
            if kind in ranks:
                return (ui, *ranks[kind])
            if kind in TASK_RANKS:
                return (ui, TASK_RANKS[kind], 0)
            return None
        m = LESSON_STEP.match(step_id)
        if m and m.group(1) in self.unit_index:
            lesson = f"{m.group(1)}.l{m.group(2)}"
            if lesson in self.written_lessons():
                return None  # the lesson is written but has no such step
            return (self.unit_index[m.group(1)], int(m.group(2)), 0)
        return None

    def describe(self, pos: Pos | None) -> str:
        if pos is None:
            return "?"
        if pos in self.pos_step:
            return self.pos_step[pos]
        unit = self.unit_of_pos(pos)
        if pos[1] == PLACEMENT:
            return f"the {unit} placement block"
        if pos[1] == CHECK and unit == "u99":
            return "the final check"
        if 0 < pos[1] < TASK:
            return f"{unit}.l{pos[1]}"
        return unit

    # ------------------------------------------------------------ lock files

    def _load_strings(self) -> None:
        for rel, msg in self.course.load_errors:
            self.add("error", 0, "parse", Loc(rel), f"does not parse: {msg}")
        expected: set[str] = set()
        for doc, kind, unit_id in annotate.files_to_annotate(self.course):
            self.files[doc.rel] = (doc, kind, unit_id)
            col = annotate.collect(self.course, doc, kind, unit_id)
            lock_rel = annotate.lock_path(doc.rel)
            if not col.sources:
                continue
            expected.add(lock_rel)
            lock_file = self.root / lock_rel
            if not lock_file.is_file():
                self.add("error", 0, "annotations", Loc(doc.rel), f"{lock_rel} is missing: run `make annotate`")
                continue
            try:
                lock = json.loads(lock_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self.add(
                    "error", 0, "annotations", Loc(doc.rel), f"{lock_rel} doesn't parse ({exc}): run `make annotate`"
                )
                continue
            entries = _seq(_map(lock).get("strings"))
            stale = len(entries) != len(col.sources) or any(
                not isinstance(e, dict)
                or e.get("path") != annotate.fmt_path(src.path)
                or e.get("role") != src.role
                or e.get("text") != src.text
                for src, e in zip(col.sources, entries, strict=False)
            )
            if stale:
                self.add(
                    "error",
                    0,
                    "annotations",
                    Loc(doc.rel),
                    f"{lock_rel} is stale (its strings no longer match the file): run `make annotate`",
                )
                continue
            self.checked_files.add(doc.rel)
            owners = self._owners(doc, kind, unit_id)
            for src, e in zip(col.sources, entries, strict=True):
                self.strings.append(self._string(doc, kind, unit_id, src, e, owners))
        base = self.root / annotate.LOCK_DIR
        if base.is_dir():
            for p in sorted(base.rglob("*.json")):
                rel = p.relative_to(self.root).as_posix()
                if rel not in expected:
                    self.add("error", 0, "annotations", Loc(rel), f"{rel} is left over: run `make annotate`")

    def _owners(self, doc: Doc, kind: str, unit_id: str) -> list[ExerciseRef | TextRef | NoteRef]:
        if kind == "lesson":
            return [*walk_lesson(doc, unit_id), *walk_notes(doc, unit_id)]
        if kind == "task":
            return list(walk_task(doc, unit_id))
        if kind in ("check", "placement", "final"):
            return list(walk_check(doc, unit_id, kind))
        return []

    def _string(
        self,
        doc: Doc,
        kind: str,
        unit_id: str,
        src: annotate.Source,
        e: dict[str, Any],
        owners: list[ExerciseRef | TextRef | NoteRef],
    ) -> Str:
        toks = [_tok(i, t) for i, t in enumerate(_seq(e.get("tokens"))) if isinstance(t, dict)]
        dets = []
        for d in _seq(e.get("detections")):
            span = _seq(_map(d).get("tokens"))
            if len(span) == 2 and isinstance(d.get("point"), str):
                dets.append(Det(d["point"], int(span[0]), int(span[1])))
        gap = e.get("gap")
        s = Str(
            file=doc.rel,
            path=src.path,
            role=src.role,
            text=src.text,
            tokens=toks,
            detections=dets,
            container=kind,
            unit=unit_id,
            ref=e.get("ref"),
            model=e.get("model"),
            index=e.get("expansion"),
            gap=(int(gap[0]), int(gap[1])) if isinstance(gap, list) and len(gap) == 2 else None,
        )
        best: dict[type, tuple[int, Any]] = {}
        for o in owners:
            op = o.loc.path
            if src.path[: len(op)] == op and len(op) >= best.get(type(o), (-1, None))[0]:
                best[type(o)] = (len(op), o)
        s.text_ref = best.get(TextRef, (0, None))[1]
        s.exercise = best.get(ExerciseRef, (0, None))[1]
        s.note = best.get(NoteRef, (0, None))[1]
        if s.role == "line" and s.text_ref is not None and len(src.path) >= 2 and isinstance(src.path[-2], int):
            lines = _seq(s.text_ref.data.get("lines"))
            n = src.path[-2]
            s.line = lines[n] if 0 <= n < len(lines) and isinstance(lines[n], dict) else None
        pl = self.place(s.loc)
        if pl is not None:
            s.pos, s.step, s.lesson, s.unit = pl.pos, pl.step, pl.lesson, pl.unit
        return s

    def place(self, loc: Loc) -> Place | None:
        """Where a YAML location of a lesson, task, check or assessment file sits in the course."""
        info = self.files.get(loc.file)
        if info is None:
            return None
        doc, kind, unit_id = info
        ui = self.unit_index.get(unit_id, 0)
        p = loc.path
        if kind == "lesson":
            lid = str(_map(doc.data).get("id", ""))
            k = lesson_k(lid)
            steps = _seq(_map(doc.data).get("steps"))
            if len(p) >= 2 and p[0] == "steps" and isinstance(p[1], int) and p[1] < len(steps):
                sid = _map(steps[p[1]]).get("id")
                return Place((ui, k, p[1]), sid if isinstance(sid, str) else None, lid, unit_id)
            return Place((ui, k, 0), None, lid, unit_id)
        if kind == "task":
            if p and p[0] == "conversations" and len(p) > 1 and isinstance(p[1], int):
                n = p[1] + 1
                return Place((ui, TASK, n), f"{unit_id}.step-conversation-{n}", None, unit_id)
            if p and p[0] in TASK_RANKS:
                return Place((ui, TASK_RANKS[str(p[0])], 0), f"{unit_id}.step-{p[0]}", None, unit_id)
            return Place((ui, TASK, 0), None, None, unit_id)
        if kind == "check":
            return Place((ui, CHECK, 0), f"{unit_id}.step-check", None, unit_id)
        if kind == "final":
            return Place((ui, CHECK, 0), None, None, unit_id)
        if kind == "placement":
            blocks = _seq(_map(doc.data).get("blocks"))
            i = p[1] if len(p) > 1 and p[0] == "blocks" and isinstance(p[1], int) else -1
            bu = str(_map(blocks[i]).get("unit", unit_id)) if 0 <= i < len(blocks) else unit_id
            return Place((self.unit_index.get(bu, ui), PLACEMENT, 0), None, None, bu)
        if kind == "unit":
            return Place((ui, OPENER, 0), None, None, unit_id)
        return Place(None, None, None, unit_id)  # items (recall_answer): placed by eligibility, not here

    def strings_of(self, *, file: str | None = None) -> list[Str]:
        return [s for s in self.strings if file is None or s.file == file]

    # ------------------------------------------------------------ introductions

    def _build_introductions(self) -> None:
        lessons = self.written_lessons()
        text_strings: dict[str, list[Str]] = {}
        for s in self.strings:
            if s.text_ref is not None and s.step and s.container == "lesson":
                text_strings.setdefault(s.step, []).append(s)
        for step in sorted(self.steps.values(), key=lambda x: x.pos):
            if step.lesson is None:
                continue
            kind, data = step.kind, step.data
            if kind == "preview":
                for batch in _seq(data.get("batches")):
                    for iid in _seq(batch):
                        if isinstance(iid, str):
                            st = self.items.get(iid, {}).get("status")
                            self.intros.add(iid, Intro(step.pos, step.id, "preview", preview_skills(st)))
                            for pt in _seq(self.items.get(iid, {}).get("exemplifies")):
                                if (
                                    isinstance(pt, str)
                                    and self.point_status(pt) in ("R", "chunk")
                                    and self.point_unit(pt) == step.unit
                                ):
                                    self.intros.add(pt, Intro(step.pos, step.id, "preview", frozenset({"read"})))
            elif kind in TEXT_STEPS:
                for s in text_strings.get(step.id, []):
                    if s.text_ref is None or s.text_ref.owner != "step" or s.role == "title":
                        continue
                    for t in s.tokens:
                        if NEW in t.flags and t.ref:
                            self.intros.add(t.ref, Intro(step.pos, step.id, "story", frozenset({"read", "listen"})))
                    if kind in ("story", "listening"):
                        for d in s.detections:
                            if self.point_status(d.point) in ("R", "chunk") and self.point_unit(d.point) == step.unit:
                                self.intros.add(d.point, Intro(step.pos, step.id, "story", frozenset({"read"})))
            elif kind == "note":
                for pt in _seq(data.get("grammar")):
                    if isinstance(pt, str):
                        skills = {"read", "recall"} if self.point_status(pt) == "P" else {"read"}
                        self.intros.add(pt, Intro(step.pos, step.id, "note", frozenset(skills)))
            elif kind == "sounds":
                for ex in _seq(data.get("exercises")):
                    for t in _seq(_map(ex).get("targets")):
                        iid = _map(t).get("item")
                        if isinstance(iid, str) and iid.startswith("s:"):
                            self.intros.add(iid, Intro(step.pos, step.id, "sounds", frozenset({"listen"})))
        # the lesson's own target points count from its first text step (its story comes before its note)
        for lid, (_, doc) in lessons.items():
            first_text = None
            points: set[str] = set()
            for s, step in lesson_steps(doc):
                if step.get("kind") in TEXT_STEPS and first_text is None:
                    first_text = s
                if step.get("kind") == "note":
                    points.update(p for p in _seq(step.get("grammar")) if isinstance(p, str))
            if first_text is not None and points:
                self.lesson_targets[lid] = (first_text, frozenset(points))
        self._item_fallbacks(lessons)
        self._point_fallbacks()

    def _item_fallbacks(self, lessons: dict[str, tuple[UnitFiles, Doc]]) -> None:
        for iid, item in self.items.items():
            unit = self.item_unit[iid]
            ui = self.unit_index.get(unit, 0)
            lesson = item.get("lesson") if isinstance(item.get("lesson"), str) else None
            skills = preview_skills(item.get("status"))
            if iid.startswith("s:"):
                skills = frozenset(k for k, v in item_skills(item.get("status")).items() if v in ("P", "R"))
            if lesson is None or lesson not in lessons:
                self.intros.add(iid, Intro((ui, OPENER, 0), f"{unit}.step-opener", "unit-start", skills))
                continue
            from_lesson = [x for x in self.intros.written(iid) if self.steps[x.step].lesson == lesson]
            if not from_lesson:
                loc = self.item_loc.get(iid, Loc(""))
                self.add(
                    "error",
                    2,
                    "introduction",
                    loc.child("lesson"),
                    f"{iid} names lesson {lesson}, but {lesson} doesn't introduce it: put it in a preview batch, gloss "
                    "it as new in the story, or change `lesson`",
                )
                k = lesson_k(lesson)
                self.intros.add(iid, Intro((self.unit_index.get(unit, 0), k, 0), lesson, "lesson-start", skills))

    def _point_fallbacks(self) -> None:
        for pid in self.points:
            unit = self.point_unit(pid)
            if unit not in self.unit_index:
                continue
            status = self.point_status(pid)
            written = self.intros.written(pid)
            has_note = any(x.via == "note" for x in written)
            uf = self.unit(unit)
            complete = bool(uf and uf.complete)
            if status == "P" and not has_note:
                # complete units: check 4 reports the missing note; the fallback avoids a cascade of gate errors
                self.intros.add(
                    pid,
                    Intro(
                        (self.unit_index[unit], OPENER, 0),
                        f"{unit}.step-opener",
                        "unit-start",
                        frozenset({"read", "recall"}),
                    ),
                )
            elif status in ("R", "chunk") and not written and not complete:
                self.intros.add(
                    pid,
                    Intro((self.unit_index[unit], OPENER, 0), f"{unit}.step-opener", "unit-start", frozenset({"read"})),
                )

    def note_fallback(self, ref: str, intro: Intro, s: Str) -> None:
        """Record that written content relies on a start-of-unit fallback introduction."""
        if intro.via != "unit-start":
            return
        if ref.startswith("g:"):
            group = self.fallback_points.setdefault(self.point_unit(ref), FallbackUse())
        else:
            lesson = self.items.get(ref, {}).get("lesson")
            key = lesson if isinstance(lesson, str) else f"{self.item_unit.get(ref, '?')} (no lesson)"
            group = self.fallback_items.setdefault(key, FallbackUse())
        group.refs[ref] = group.refs.get(ref, 0) + 1
        if group.first is None:
            group.first = s.loc

    def report_fallbacks(self) -> None:
        for lesson, use in sorted(self.fallback_items.items()):
            refs = sorted(use.refs)
            first = refs[0]
            loc = self.item_loc.get(first, Loc(""))
            self.add(
                "warning",
                2,
                "partial",
                loc.child("lesson") if "(no lesson)" not in lesson else loc,
                f"{lesson} isn't written yet: written content uses {len(refs)} of its item(s) "
                f"({_short(refs)}), which count as introduced at the start of {self.item_unit.get(first, '?')}",
                unit=self.item_unit.get(first, ""),
            )
        for unit, use in sorted(self.fallback_points.items()):
            refs = sorted(use.refs)
            loc = self.point_loc.get(refs[0], Loc("content/grammar/points.yaml"))
            self.add(
                "warning",
                2,
                "partial",
                loc,
                f"written content relies on {len(refs)} {unit} grammar point(s) without a written note "
                f"({_short(refs)}); they count as introduced at the start of {unit}",
                unit=unit,
            )

    # ------------------------------------------------------------ helpers for the gates

    def targets_at(self, s: Str) -> frozenset[str]:
        """The current lesson's target points, if `s` is at or after the lesson's first text step."""
        if s.lesson is None or s.pos is None or s.lesson not in self.lesson_targets:
            return frozenset()
        first, points = self.lesson_targets[s.lesson]
        return points if s.pos[2] >= first else frozenset()


def _short(refs: list[str], n: int = 6) -> str:
    return ", ".join(refs[:n]) + (f", … (+{len(refs) - n})" if len(refs) > n else "")


def load_context(root: Path | None = None) -> CheckContext:
    root = (root or paths.ROOT).resolve()
    return CheckContext(root, load_course(root))


Gate = Callable[[CheckContext], None]
