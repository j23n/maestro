"""The course-wide ID index (docs/03 § IDs): every defined ID, where it is defined, and what it holds.

Authored IDs come from the content files; generated ones are added as the build will create them (unit-level steps,
preview exercises; `gen:<skill>:<item>` review cards and `<textId>#n` lines resolve on lookup). `problem()` says why a
reference doesn't resolve, which `references` turns into an error or a pending finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import ids
from itcontent.course import Course, Doc, ExerciseRef, Loc, TextRef, UnitFiles, lesson_steps, walk_course

MISSING = "missing"


@dataclass(frozen=True)
class Def:
    id: str
    kind: str  # unit lesson step text exercise note item grammar can_do syllabus character country task_file check …
    loc: Loc
    unit: str | None = None
    lines: int | None = None  # texts: number of lines (None for real-world layouts)
    nodes: frozenset[str] = frozenset()  # conversations: node IDs
    generated: bool = False


@dataclass
class Index:
    defs: dict[str, list[Def]] = field(default_factory=dict)
    topics: set[str] = field(default_factory=set)

    def add(self, d: Def) -> None:
        self.defs.setdefault(d.id, []).append(d)

    def get(self, identifier: str) -> Def | None:
        found = self.defs.get(identifier)
        return found[0] if found else None

    def problem(self, ref: str) -> str | None:
        """None if `ref` resolves; MISSING if nothing defines it; otherwise what is wrong with it."""
        if ref in ids.RESERVED_SPEAKERS or ref in ids.RESERVED_SPEAKERS.values():
            return None
        line = ids.split_line_ref(ref)
        if line:
            text, n = line
            d = self.get(text)
            if d is None:
                return MISSING
            if d.kind != "text":
                return f"'{text}' is a {ids.describe(d.kind)}, not a text"
            if d.lines is None:
                return f"text {text} is a real-world layout without numbered lines"
            if not 1 <= n <= d.lines:
                return f"text {text} has {d.lines} lines; there is no line {n}"
            return None
        if ids.is_valid(ref, "conversation_node_ref"):
            ex, node = ref.split("/", 1)
            d = self.get(ex)
            if d is None:
                return MISSING
            return None if node in d.nodes else f"conversation {ex} has no node '{node}'"
        if ref.startswith("gen:") and ids.is_valid(ref, "generated_exercise"):
            item = ref.split(":", 2)[2]
            return None if self.get(item) else MISSING
        if ids.is_valid(ref, "topic"):
            return None if ref in self.topics else MISSING
        if ids.is_valid(ref, "audio"):
            return None  # content-addressed; checked by the build
        return None if ref in self.defs else MISSING

    def exists(self, ref: str) -> bool:
        return self.problem(ref) is None


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def _sid(x: Any) -> str | None:
    return x if isinstance(x, str) else None


def unit_level_steps(u: UnitFiles) -> list[str]:
    """The generated unit-level step IDs of a unit (docs/06 § Unit-level steps), from its task file when written,
    else from the unit spec's `tasks`."""
    spec = _map(u.spec.data) if u.spec else {}
    tasks = _map(spec.get("tasks"))
    task = _map(u.task.data) if u.task else None
    out = [f"{u.id}.step-opener"]
    n_conv = len(_seq(task.get("conversations"))) if task is not None else len(_seq(tasks.get("conversation")))
    out += [f"{u.id}.step-conversation-{n}" for n in range(1, n_conv + 1)]
    for key in ("talk", "writing", "relay"):
        if (task is not None and task.get(key)) or (task is None and tasks.get(key)):
            out.append(f"{u.id}.step-{key}")
    if spec.get("check") is not None or u.check is not None:
        out.append(f"{u.id}.step-check")
    out.append(f"{u.id}.step-fluency")
    return out


def _add_lesson(ix: Index, doc: Doc, unit: str) -> None:
    data = _map(doc.data)
    if lid := _sid(data.get("id")):
        ix.add(Def(lid, "lesson", doc.loc.child("id"), unit))
    for i, step in lesson_steps(doc):
        sloc = doc.loc.child("steps", i)
        sid = _sid(step.get("id"))
        if sid:
            ix.add(Def(sid, "step", sloc.child("id"), unit))
        if nid := _sid(step.get("note_id")):
            ix.add(Def(nid, "note", sloc.child("note_id"), unit))
        if step.get("kind") == "preview" and sid:
            for k, batch in enumerate(_seq(step.get("batches")), start=1):
                bloc = sloc.child("batches", k - 1)
                ix.add(Def(f"{sid}.b{k}.match", "generated_exercise", bloc, unit, generated=True))
                for j, item in enumerate(_seq(batch)):
                    if isinstance(item, str):
                        gid = f"{sid}.b{k}.{ids.generated_item_suffix(item)}"
                        ix.add(Def(gid, "generated_exercise", bloc.child(j), unit, generated=True))


def build_index(course: Course) -> Index:
    ix = Index()
    for u in course.units:
        spec = _map(u.spec.data) if u.spec else {}
        if u.spec and (uid := _sid(spec.get("id"))):
            ix.add(Def(uid, "unit", u.spec.loc.child("id"), uid))
        if u.spec:
            for i, cd in enumerate(_seq(spec.get("can_do"))):
                if cid := _sid(_map(cd).get("id")):
                    ix.add(Def(cid, "can_do", u.spec.loc.child("can_do", i, "id"), u.id))
            ix.topics.update(t for t in _seq(_map(spec.get("items")).get("topics")) if isinstance(t, str))
            for sid in unit_level_steps(u):
                ix.add(Def(sid, "step", u.spec.loc, u.id, generated=True))
        for doc in u.lessons:
            _add_lesson(ix, doc, u.id)
        for doc, kind in ((u.task, "task_file"), (u.check, "check_file")):
            if doc and (did := _sid(_map(doc.data).get("id"))):
                ix.add(Def(did, kind, doc.loc.child("id"), u.id))
        if u.items:
            for i, item in enumerate(_seq(_map(u.items.data).get("items"))):
                item = _map(item)
                if iid := _sid(item.get("id")):
                    ix.add(Def(iid, "item", u.items.loc.child("items", i, "id"), u.id))
                ix.topics.update(t for t in _seq(item.get("topics")) if isinstance(t, str))
    for doc in course.assessments.values():
        if did := _sid(_map(doc.data).get("id")):
            ix.add(Def(did, "check_file", doc.loc.child("id")))
    for x in walk_course(course):
        did = _sid(x.data.get("id"))
        if not did:
            continue
        if isinstance(x, ExerciseRef):
            nodes = frozenset(k for k in _map(x.data.get("nodes")) if isinstance(k, str))
            ix.add(Def(did, "exercise", x.loc.child("id"), x.unit_id, nodes=nodes))
        elif isinstance(x, TextRef):
            lines = x.data.get("lines")
            n = len(lines) if isinstance(lines, list) else None
            ix.add(Def(did, "text", x.loc.child("id"), x.unit_id, lines=n))
    singles = course.singles
    if "points" in singles:
        for i, p in enumerate(_seq(_map(singles["points"].data).get("points"))):
            if pid := _sid(_map(p).get("id")):
                ix.add(Def(pid, "grammar", singles["points"].loc.child("points", i, "id")))
    if "syllabus" in singles:
        for i, e in enumerate(_seq(_map(singles["syllabus"].data).get("items"))):
            e = _map(e)
            if eid := _sid(e.get("id")):
                ix.add(Def(eid, "syllabus", singles["syllabus"].loc.child("items", i, "id")))
            ix.topics.update(r for r in _seq(e.get("covered_by")) if isinstance(r, str) and r.startswith("topic:"))
    if "story_bible" in singles:
        for i, ch in enumerate(_seq(_map(singles["story_bible"].data).get("characters"))):
            if cid := _sid(_map(ch).get("id")):
                ix.add(Def(cid, "character", singles["story_bible"].loc.child("characters", i, "id")))
    if "countries" in singles:
        for i, c in enumerate(_seq(_map(singles["countries"].data).get("countries"))):
            if cid := _sid(_map(c).get("id")):
                ix.add(Def(cid, "country", singles["countries"].loc.child("countries", i, "id")))
    return ix


# ---------------------------------------------------------------- ids.lock and retired.yaml


def read_lock(path: Path) -> list[tuple[int, str]]:
    """`content/ids.lock` (docs/03 § IDs): one released ID per line, sorted; a line starting with `#` is a comment;
    anything after the ID (whitespace-separated, e.g. the pack version that first released it) is ignored."""
    out = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if text and not text.startswith("#"):
            out.append((n, text.split()[0]))
    return out


def retired_ids(course: Course) -> dict[str, Loc]:
    doc = course.singles.get("retired")
    if not doc:
        return {}
    out = {}
    for i, entry in enumerate(_seq(_map(doc.data).get("retired"))):
        if rid := _sid(_map(entry).get("id")):
            out.setdefault(rid, doc.loc.child("retired", i, "id"))
    return out
