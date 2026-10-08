"""Cross-file checks of `content lint` (docs/04 § Commands, docs/03 § IDs).

- **Structure:** course units have folders; lesson, unit, task and check IDs match their files; items files belong
  to course units.
- **IDs:** every ID fits where it is (a step ID names its own lesson and kind, exercise IDs are numbered the way their
  container numbers them, …); IDs are unique across the course; homograph items carry `~sense` suffixes.
- **References resolve.** A missing unit, lesson, step, item, sound or task exercise is *pending* (information) when
  the reference comes from a unit spec, the syllabus, the story bible's `switch_at`, `disambiguation.yaml`,
  `pronunciation.yaml` or an item's `lesson`; anything else that is missing is an error.
- **Exercise rules** the schemas can't express: match targets per pair, choice answer indexes, conversation graphs,
  sentence-building tiles, `pass` within the points, `recall_answer` for chunks written with `/`.
- **ids.lock** (released IDs still exist or are retired), **retired.yaml** (never reused) and **review ledgers**
  (every comment has a known target).

Schema problems are reported by `schemas`; these checks skip values that are malformed, so nothing is reported twice.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from itcontent import ids
from itcontent.course import Course, ExerciseRef, Loc, TextRef, UnitFiles, lesson_steps, walk_course
from itcontent.findings import Finding, format_path, make
from itcontent.index import MISSING, Index, read_lock, retired_ids

LineOf = Callable[[str, tuple[str | int, ...]], int | None]
ANY_KIND = "|".join(k for k in ids.PATTERNS if k not in ids.LOCAL_KINDS)

PENDABLE = ("unit", "lesson", "lesson_step", "unit_step", "word", "chunk", "sound", "exercise")
CONCRETE = (
    "unit",
    "lesson",
    "lesson_step",
    "unit_step",
    "word",
    "chunk",
    "sound",
    "grammar",
    "can_do",
    "syllabus",
    "character",
    "text_line",
    "text",
    "exercise",
    "note",
    "topic",
    "country",
    "generated_exercise",
    "conversation_node_ref",
)
WHAT = {
    "lesson_step": "step",
    "unit_step": "step",
    "word": "item",
    "chunk": "item",
    "text_line": "text",
    "generated_exercise": "item",
}


def concrete_kind(ref: str) -> str | None:
    for k in CONCRETE:
        if ids.is_valid(ref, k):
            return k
    return None


def what_is(ref: str) -> str:
    kind = concrete_kind(ref) or "id"
    return WHAT.get(kind, ids.KIND_NAMES.get(kind, kind))


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def _str(x: Any) -> str | None:
    return x if isinstance(x, str) else None


class Checker:
    def __init__(self, root: Path, course: Course, index: Index, docs: dict[str, Any], line_of: LineOf) -> None:
        self.root = root
        self.course = course
        self.ix = index
        self.docs = docs
        self.line_of = line_of
        self.out: list[Finding] = []
        self._pending: dict[tuple[str, str, str], list[Loc]] = {}
        self.lock: dict[str, int] = {}
        lock = root / "content" / "ids.lock"
        if lock.is_file():
            self.lock = {i: n for n, i in read_lock(lock)}
        self.retired = retired_ids(course)
        self.points = {p["id"]: p for p in course.grammar_points() if isinstance(p.get("id"), str)}

    # ------------------------------------------------------------ reporting

    def error(self, loc: Loc, message: str, related: tuple[str, ...] = ()) -> None:
        self.out.append(make("error", loc.file, loc.path, message, related=related))

    def warning(self, loc: Loc, message: str) -> None:
        self.out.append(make("warning", loc.file, loc.path, message))

    def where(self, loc: Loc) -> str:
        line = self.line_of(loc.file, loc.path)
        return f"{loc}{f' (line {line})' if line else ''}"

    def ref(self, target: Any, loc: Loc, kinds: str, *, pending: bool = False) -> None:
        """Check that `target` resolves. Malformed targets are the schemas' to report."""
        if not isinstance(target, str):
            return
        matched = next((k for k in kinds.split("|") if ids.is_valid(target, k)), None)
        if matched is None:
            return
        problem = self.ix.problem(target)
        if problem is None:
            return
        if problem != MISSING:
            self.error(loc, problem)
            return
        # The expected kind decides what the target is: u02.task.menu is a text and u02.task.conv1 an exercise,
        # though both fit both patterns.
        kind = matched if matched in CONCRETE else (concrete_kind(target) or matched)
        what = WHAT.get(kind, ids.KIND_NAMES.get(kind, kind))
        if pending and kind in PENDABLE:
            self._pending.setdefault((loc.file, target, what), []).append(loc)
        else:
            self.error(loc, f"unknown {what} '{target}'")

    def finish(self) -> list[Finding]:
        for (file, target, what), locs in self._pending.items():
            more = (
                f" ({len(locs) - 1} more reference{'s' if len(locs) > 2 else ''} in this file)" if len(locs) > 1 else ""
            )
            self.out.append(make("pending", file, locs[0].path, f"{what} '{target}' doesn't exist yet{more}"))
        return self.out

    # ------------------------------------------------------------ the checks

    def run(self) -> list[Finding]:
        self.check_structure()
        for u in self.course.units:
            self.check_unit(u)
        self.check_items()
        self.check_walk()
        self.check_points_and_detection()
        self.check_syllabus()
        self.check_story_bible()
        self.check_voices()
        self.check_disambiguation()
        self.check_assessments()
        self.check_uniqueness()
        self.check_slug_collisions()
        self.check_retired()
        self.check_lock()
        self.check_ledgers()
        return self.finish()

    def check_structure(self) -> None:
        c = self.course
        slugs = _seq(_map(c.course.data).get("units"))
        for i, slug in enumerate(slugs):
            if isinstance(slug, str) and not (self.root / "content" / "units" / slug / "unit.yaml").is_file():
                self.error(c.course.loc.child("units", i), f"unit folder content/units/{slug}/ has no unit.yaml")
        units_dir = self.root / "content" / "units"
        if units_dir.is_dir():
            for d in sorted(p for p in units_dir.iterdir() if p.is_dir() and p.name not in slugs):
                for f in sorted(d.glob("*.yaml")):
                    rel = f.relative_to(self.root).as_posix()
                    self.warning(
                        Loc(rel), f"unit folder {d.name} is not in content/course.yaml, so nothing in it is built"
                    )
        unit_ids = {u.id for u in c.units}
        for f in sorted((self.root / "content" / "items").glob("*.yaml")):
            if f.stem not in unit_ids:
                rel = f.relative_to(self.root).as_posix()
                self.error(Loc(rel), f"there is no unit {f.stem} in content/course.yaml for this items file")

    def check_unit(self, u: UnitFiles) -> None:
        if not u.spec:
            return
        spec = _map(u.spec.data)
        loc = u.spec.loc
        expected = ids.unit_from_folder(u.slug)
        uid = _str(spec.get("id"))
        if uid and ids.is_valid(uid, "unit") and uid != expected:
            self.error(loc.child("id"), f"unit ID {uid} doesn't match its folder {u.slug} (expected {expected})")
        for i, cd in enumerate(_seq(spec.get("can_do"))):
            for j, sy in enumerate(_seq(_map(cd).get("syllabus"))):
                self.ref(sy, loc.child("can_do", i, "syllabus", j), "syllabus")
        listed = set()
        for i, g in enumerate(_seq(spec.get("grammar"))):
            gid, status = _str(_map(g).get("id")), _map(g).get("status")
            if not gid:
                continue
            listed.add(gid)
            self.ref(gid, loc.child("grammar", i, "id"), "grammar")
            p = self.points.get(gid)
            if p is None:
                continue
            if p.get("unit") != u.id:
                self.error(
                    loc.child("grammar", i, "id"), f"{gid} belongs to {p.get('unit')} in points.yaml, not {u.id}"
                )
            elif status is not None and p.get("status") != status:
                self.error(
                    loc.child("grammar", i, "status"),
                    f"points.yaml gives {gid} status {p.get('status')}, this unit spec says {status}",
                )
        if "grammar" in spec:
            for gid, p in sorted(self.points.items()):
                if p.get("unit") == u.id and gid not in listed:
                    self.error(loc.child("grammar"), f"{gid} is a {u.id} point in points.yaml but isn't listed here")
        for i, s in enumerate(_seq(spec.get("sounds"))):
            self.ref(s, loc.child("sounds", i), "sound", pending=True)
        for i, r in enumerate(_seq(spec.get("recycle_from"))):
            self.ref(r, loc.child("recycle_from", i), "unit", pending=True)
        tasks = _map(spec.get("tasks"))
        task_data = _map(u.task.data) if u.task else {}
        task_convs = {_map(x).get("id") for x in _seq(task_data.get("conversations"))}
        for i, conv in enumerate(_seq(tasks.get("conversation"))):
            cid = _str(_map(conv).get("id"))
            cloc = loc.child("tasks", "conversation", i, "id")
            if not cid or not ids.is_valid(cid, "exercise"):
                continue
            if not cid.startswith(f"{u.id}.task."):
                self.error(cloc, f"a task conversation of {u.id} is named {u.id}.task.<name>, not {cid}")
            elif u.task is not None:
                if cid not in task_convs:
                    self.error(cloc, f"{u.task.rel} has no conversation {cid}", related=(u.task.rel,))
            else:
                self.ref(cid, cloc, "exercise", pending=True)
        fc = _str(tasks.get("final_check"))
        if fc and not (self.root / fc).is_file():
            self._pending.setdefault((loc.file, fc, "file"), []).append(loc.child("tasks", "final_check"))
        # lesson files: names, IDs and count
        for doc in u.lessons:
            m = re.fullmatch(r"lesson-(\d+)\.yaml", doc.path.name)
            if not m:
                self.error(Loc(doc.rel), "lesson files are named lesson-K.yaml (K = 1, 2, …)")
                continue
            k = int(m.group(1))
            lid = _str(_map(doc.data).get("id"))
            if lid and ids.is_valid(lid, "lesson") and lid != f"{u.id}.l{k}":
                self.error(doc.loc.child("id"), f"lesson ID {lid} doesn't match its file (expected {u.id}.l{k})")
            if k > u.lesson_count:
                self.error(doc.loc, f"{doc.path.name}, but {u.spec.rel} says the unit has {u.lesson_count} lessons")
        for doc, want in ((u.task, f"{u.id}.task"), (u.check, f"{u.id}.check")):
            did = _str(_map(doc.data).get("id")) if doc else None
            if doc and did and did != want and (ids.is_valid(did, "task_file") or ids.is_valid(did, "check_file")):
                self.error(doc.loc.child("id"), f"{did} doesn't match its unit (expected {want})")

    def check_items(self) -> None:
        unit_ids = {u.id: u for u in self.course.units}
        for u in self.course.units:
            if not u.items:
                continue
            data, loc = _map(u.items.data), u.items.loc
            if isinstance(data.get("unit"), str) and data["unit"] != u.id and ids.is_valid(data["unit"], "unit"):
                self.error(loc.child("unit"), f"this is the items file of {u.id}, not {data['unit']}")
            for i, item in enumerate(_seq(data.get("items"))):
                item = _map(item)
                iloc = loc.child("items", i)
                iid = _str(item.get("id"))
                if iid and ids.is_valid(iid, "lexical_item"):
                    want = {"chunk": "c:", "sound": "s:"}.get(_str(item.get("kind")) or "", "w:")
                    if not iid.startswith(want):
                        kind = item.get("kind") or "word"
                        self.error(iloc.child("id"), f"{iid}: a {kind} item's ID starts with {want}")
                lesson = _str(item.get("lesson"))
                if lesson and ids.is_valid(lesson, "lesson"):
                    owner = unit_ids.get(ids.unit_of(lesson) or "")
                    k = int(lesson.rsplit(".l", 1)[1])
                    if ids.unit_of(lesson) != u.id:
                        self.error(
                            iloc.child("lesson"), f"{iid} is a {u.id} item, so its lesson is in {u.id}, not {lesson}"
                        )
                    elif owner is not None and k > owner.lesson_count:
                        self.error(
                            iloc.child("lesson"), f"{u.id} has {owner.lesson_count} lessons; there is no {lesson}"
                        )
                    else:
                        self.ref(lesson, iloc.child("lesson"), "lesson", pending=True)
                for j, g in enumerate(_seq(item.get("exemplifies"))):
                    self.ref(g, iloc.child("exemplifies", j), "grammar")
                it = _str(item.get("it"))
                if item.get("kind") == "chunk" and it and "/" in it and not item.get("recall_answer"):
                    self.error(
                        iloc.child("it"),
                        f"{iid}: a chunk written with '/' ('{it}') needs a recall_answer "
                        "(docs/05 § Review session builder)",
                    )

    # ------------------------------------------------------------ lessons, tasks, checks, assessments

    def _containers(self) -> dict[str, tuple[str, str | None, str]]:
        """rel → (container, lesson ID or None, unit ID)."""
        out = {}
        for u in self.course.units:
            for doc in u.lessons:
                lid = _str(_map(doc.data).get("id"))
                out[doc.rel] = ("lesson", lid if lid and ids.is_valid(lid, "lesson") else None, u.id)
            if u.task:
                out[u.task.rel] = ("task", None, u.id)
            if u.check:
                out[u.check.rel] = ("check", None, u.id)
        for name, doc in self.course.assessments.items():
            out[doc.rel] = (name, None, "")
        return out

    def check_walk(self) -> None:
        containers = self._containers()
        for u in self.course.units:
            for doc in u.lessons:
                self.check_lesson_steps(doc, containers[doc.rel][1])
        for x in walk_course(self.course):
            container, lesson, unit = containers.get(x.loc.file, ("", None, ""))
            if isinstance(x, ExerciseRef):
                self.check_exercise(x, lesson)
            else:
                self.check_text(x, container, lesson, unit)

    def check_lesson_steps(self, doc, lesson: str | None) -> None:
        for i, step in lesson_steps(doc):
            sloc = doc.loc.child("steps", i)
            sid, kind = _str(step.get("id")), _str(step.get("kind"))
            if lesson and sid and kind in ids.LESSON_STEP_KINDS and ids.is_valid(sid, "lesson_step"):
                if ids.lesson_of(sid) != lesson:
                    self.error(sloc.child("id"), f"step ID {sid} belongs to {ids.lesson_of(sid)}, not {lesson}")
                elif ids.step_kind_of(sid) != kind:
                    self.error(
                        sloc.child("id"),
                        f"step ID {sid} doesn't match the step's kind {kind} (expected {lesson}.step-{kind}[-N])",
                    )
            if kind == "preview":
                seen: dict[str, Loc] = {}
                for k, batch in enumerate(_seq(step.get("batches"))):
                    for j, item in enumerate(_seq(batch)):
                        iloc = sloc.child("batches", k, j)
                        if isinstance(item, str) and item in seen:
                            self.error(iloc, f"{item} is already in this preview at {format_path(seen[item].path)}")
                        elif isinstance(item, str):
                            seen[item] = iloc
                        self.ref(item, iloc, "lexical_item")
            if kind == "note":
                nid = _str(step.get("note_id"))
                if lesson and nid and ids.is_valid(nid, "note") and ids.lesson_of(nid) != lesson:
                    self.error(sloc.child("note_id"), f"note ID {nid} belongs to {ids.lesson_of(nid)}, not {lesson}")
                for j, g in enumerate(_seq(step.get("grammar"))):
                    self.ref(g, sloc.child("grammar", j), "grammar")
                for b, block in enumerate(_seq(step.get("body"))):
                    for j, ex in enumerate(_seq(_map(block).get("examples"))):
                        self.ref(ex, sloc.child("body", b, "examples", j), "text_line")

    def check_exercise(self, x: ExerciseRef, lesson: str | None) -> None:
        d, loc = x.data, x.loc
        self.check_exercise_id(x, lesson)
        for i, t in enumerate(_seq(d.get("targets"))):
            self.ref(_map(t).get("item"), loc.child("targets", i, "item"), "item")
        for i, tag in enumerate(_seq(d.get("tags"))):
            self.ref(tag, loc.child("tags", i), "can_do|syllabus")
        src = d.get("source")
        if isinstance(src, str):
            self.ref(src, loc.child("source"), "text|text_line")
        elif isinstance(src, dict) and isinstance(src.get("text"), str):
            self.ref(src["text"], loc.child("source", "text"), "text")
        self.ref(d.get("with"), loc.child("with"), "character")
        self.ref(_map(d.get("audio")).get("speaker"), loc.child("audio", "speaker"), "speaker")
        fmt = x.format
        if fmt == "match":
            targets, pairs = d.get("targets"), d.get("pairs")
            if isinstance(targets, list) and isinstance(pairs, list) and len(targets) != len(pairs):
                self.error(
                    loc.child("targets"),
                    f"a match has one target per pair: {len(targets)} targets for {len(pairs)} pairs "
                    "(targets[i] belongs to pairs[i])",
                )
        elif fmt == "choice":
            ans, opts = d.get("answer"), d.get("options")
            if isinstance(ans, int) and not isinstance(ans, bool) and isinstance(opts, list) and ans >= len(opts):
                self.error(
                    loc.child("answer"),
                    f"answer {ans} is not an option index: there are {len(opts)} options (0–{len(opts) - 1})",
                )
        elif fmt == "sound-pair":
            pair = [p for p in _seq(d.get("pair")) if isinstance(p, str)]
            if pair and isinstance(d.get("play"), str) and d["play"] not in pair:
                self.error(loc.child("play"), f"play '{d['play']}' is not one of the pair ({', '.join(pair)})")
            for k in _map(d.get("glosses")):
                if pair and k not in pair:
                    self.error(
                        loc.child("glosses", k), f"a gloss for '{k}', which is not in the pair ({', '.join(pair)})"
                    )
        elif fmt == "sentence-building":
            self.check_tiles(d, loc)
        elif fmt == "conversation":
            self.check_conversation(d, loc)
        if fmt in ("talk", "writing"):
            self.check_points(d, loc)

    def check_exercise_id(self, x: ExerciseRef, lesson: str | None) -> None:
        eid = x.id
        if not ids.is_valid(eid, "exercise"):
            return
        if x.container == "lesson":
            if lesson is None:
                return
            if x.step_kind == "story":
                pattern, hint = rf"{re.escape(lesson)}\.q\d+", f"{lesson}.qN (story questions)"
            else:
                pattern, hint = rf"{re.escape(lesson)}\.ex\d{{2}}", f"{lesson}.exNN"
        elif x.container == "task":
            pattern, hint = rf"{x.unit_id}\.task\.{ids.SLUG}", f"{x.unit_id}.task.<name>"
        elif x.container == "check":
            pattern, hint = rf"{x.unit_id}\.check\.\d{{2}}", f"{x.unit_id}.check.NN"
        elif x.container == "placement":
            pattern, hint = r"pl\.\d{2}", "pl.NN"
        elif x.container == "final":
            pattern, hint = rf"fin\.{re.escape(x.section or '')}\.\d{{2}}", f"fin.{x.section}.NN"
        else:
            return
        if not re.fullmatch(pattern, eid):
            self.error(x.loc.child("id"), f"exercise ID {eid} doesn't fit here: expected {hint}")

    def check_tiles(self, d: dict[str, Any], loc: Loc) -> None:
        tiles = [t for t in _seq(d.get("tiles")) if isinstance(t, str)]
        if not tiles:
            return
        want = Counter(w for t in tiles for w in t.lower().split())
        for i, ans in enumerate(_seq(d.get("answer"))):
            if not isinstance(ans, str):
                continue
            got = Counter(ans.lower().split())
            extra, missing = sorted((got - want).elements()), sorted((want - got).elements())
            if extra or missing:
                parts = []
                if extra:
                    parts.append(f"uses {', '.join(repr(w) for w in extra)}, not among the tiles")
                if missing:
                    parts.append(
                        f"leaves out the tile{'s' if len(missing) > 1 else ''} {', '.join(repr(w) for w in missing)}"
                    )
                self.error(
                    loc.child("answer", i), f"answer '{ans}' {' and '.join(parts)} (an answer orders all the tiles)"
                )

    def check_points(self, d: dict[str, Any], loc: Loc) -> None:
        points = [p for p in _seq(d.get("points")) if isinstance(p, dict)]
        seen = set()
        for i, p in enumerate(points):
            pid = p.get("id")
            if isinstance(pid, str) and pid in seen:
                self.error(loc.child("points", i, "id"), f"point '{pid}' is listed twice")
            seen.add(pid)
        passing = d.get("pass")
        if points and isinstance(passing, int) and passing > len(points):
            self.error(loc.child("pass"), f"pass {passing} is more than the {len(points)} points, so nobody can pass")

    def check_conversation(self, d: dict[str, Any], loc: Loc) -> None:
        nodes = _map(d.get("nodes"))
        goals = [g.get("id") for g in _seq(d.get("goals")) if isinstance(g, dict)]
        for i, g in enumerate(goals):
            if g in goals[:i]:
                self.error(loc.child("goals", i, "id"), f"goal '{g}' is listed twice")
        start = d.get("start")
        if isinstance(start, str) and nodes and start not in nodes:
            self.error(loc.child("start"), f"start node '{start}' doesn't exist (nodes: {', '.join(nodes)})")
        reached = set()
        for name, node in nodes.items():
            for j, intent in enumerate(_seq(_map(node).get("expect"))):
                intent = _map(intent)
                iloc = loc.child("nodes", name, "expect", j)
                nxt, goal = intent.get("next"), intent.get("goal")
                if isinstance(nxt, str) and nxt not in nodes:
                    self.error(iloc.child("next"), f"next node '{nxt}' doesn't exist (nodes: {', '.join(nodes)})")
                if isinstance(goal, str):
                    reached.add(goal)
                    if goals and goal not in goals:
                        self.error(
                            iloc.child("goal"),
                            f"goal '{goal}' is not one of this conversation's goals ({', '.join(map(str, goals))})",
                        )
        if nodes and not any(_map(n).get("final") is True for n in nodes.values()):
            self.error(loc.child("nodes"), "no node is final: true, so the conversation never ends")
        for i, g in enumerate(goals):
            if isinstance(g, str) and g not in reached and nodes:
                self.warning(loc.child("goals", i, "id"), f"no intent completes goal '{g}'")

    def check_text(self, t: TextRef, container: str, lesson: str | None, unit: str) -> None:
        tid = t.id
        if ids.is_valid(tid, "text"):
            if t.loc.path and t.loc.path[-1] == "audio_text":
                if tid != f"{t.exercise_id}.audio":
                    self.error(
                        t.loc.child("id"), f"an audio text is named after its exercise: expected {t.exercise_id}.audio"
                    )
            elif container == "lesson" and lesson and not re.fullmatch(rf"{re.escape(lesson)}\.{ids.SLUG}", tid):
                self.error(t.loc.child("id"), f"text ID {tid} doesn't fit here: expected {lesson}.<name>")
            elif container == "task" and not re.fullmatch(rf"{unit}\.task\.{ids.SLUG}", tid):
                self.error(t.loc.child("id"), f"text ID {tid} doesn't fit here: expected {unit}.task.<name>")
        for i, line in enumerate(_seq(t.data.get("lines"))):
            line = _map(line)
            lloc = t.loc.child("lines", i)
            self.ref(line.get("speaker"), lloc.child("speaker"), "speaker")
            self.ref(line.get("to"), lloc.child("to"), "character")
            for form, item in _map(line.get("lemmas")).items():
                self.ref(item, lloc.child("lemmas", form), "lexical_item")

    def check_assessments(self) -> None:
        doc = self.course.assessments.get("placement")
        if doc:
            for i, block in enumerate(_seq(_map(doc.data).get("blocks"))):
                self.ref(_map(block).get("unit"), doc.loc.child("blocks", i, "unit"), "unit")

    # ------------------------------------------------------------ singles

    def check_points_and_detection(self) -> None:
        pdoc = self.course.singles.get("points")
        if pdoc:
            for i, p in enumerate(_seq(_map(pdoc.data).get("points"))):
                p, ploc = _map(p), pdoc.loc.child("points", i)
                self.ref(p.get("unit"), ploc.child("unit"), "unit")
                for key, kind in (("syllabus", "syllabus"), ("requires", "grammar"), ("confusable", "grammar")):
                    for j, r in enumerate(_seq(p.get(key))):
                        self.ref(r, ploc.child(key, j), kind)
        ddoc = self.course.singles.get("detection")
        if ddoc:
            seen: dict[str, Loc] = {}
            for i, r in enumerate(_seq(_map(ddoc.data).get("rules"))):
                rid = _str(_map(r).get("id"))
                rloc = ddoc.loc.child("rules", i, "id")
                if not rid:
                    continue
                if rid in seen:
                    self.error(rloc, f"a second rule for {rid} (the first is at {format_path(seen[rid].path)})")
                seen.setdefault(rid, rloc)
                self.ref(rid, rloc, "grammar")
            for pid in sorted(self.points):
                if seen and pid not in seen:
                    self.error(
                        ddoc.loc.child("rules"),
                        f"no detection rule for {pid}: every point has one (detect: none if undetectable)",
                    )

    def check_syllabus(self) -> None:
        doc = self.course.singles.get("syllabus")
        if not doc:
            return
        for i, e in enumerate(_seq(_map(doc.data).get("items"))):
            e, eloc = _map(e), doc.loc.child("items", i)
            eid, area = _str(e.get("id")), _str(e.get("area"))
            if eid and area and ids.is_valid(eid, "syllabus") and eid.split(":", 1)[1].split(".", 1)[0] != area:
                self.error(eloc.child("area"), f"{eid} is in area {eid.split(':', 1)[1].split('.', 1)[0]}, not {area}")
            for j, unit in enumerate(_seq(e.get("units"))):
                self.ref(unit, eloc.child("units", j), "unit", pending=True)
            for j, r in enumerate(_seq(e.get("covered_by"))):
                if isinstance(r, str) and r.split(":", 1)[0] in ("g", "s", "cd"):
                    self.ref(r, eloc.child("covered_by", j), "grammar|sound|can_do", pending=True)

    def check_story_bible(self) -> None:
        doc = self.course.singles.get("story_bible")
        if not doc:
            return
        data = _map(doc.data)
        for i, ch in enumerate(_seq(data.get("characters"))):
            self.ref(_map(ch).get("first_unit"), doc.loc.child("characters", i, "first_unit"), "unit")
        for i, row in enumerate(_seq(data.get("timeline"))):
            for j, unit in enumerate(_seq(_map(row).get("units"))):
                self.ref(unit, doc.loc.child("timeline", i, "units", j), "unit")
        for i, fact in enumerate(_seq(data.get("facts_to_check"))):
            self.ref(_map(fact).get("unit"), doc.loc.child("facts_to_check", i, "unit"), "unit")
        for i, row in enumerate(_seq(data.get("registers"))):
            row, rloc = _map(row), doc.loc.child("registers", i)
            for key in ("from", "to"):
                if row.get(key) != "*":
                    self.ref(row.get(key), rloc.child(key), "character")
            units = row.get("units")
            for j, unit in enumerate(_seq(units)):
                self.ref(unit, rloc.child("units", j), "unit")
            self.ref(row.get("switch_at"), rloc.child("switch_at"), "step", pending=True)

    def check_voices(self) -> None:
        doc = self.course.singles.get("voices")
        if doc:
            for key in _map(_map(doc.data).get("voices")):
                if isinstance(key, str) and key.startswith("ch:"):
                    self.ref(key, doc.loc.child("voices", key), "character")

    def check_disambiguation(self) -> None:
        doc = self.course.singles.get("disambiguation")
        if not doc:
            return
        data = _map(doc.data)
        for i, rule in enumerate(_seq(data.get("context_rules"))):
            for key in ("choose", "otherwise"):
                self.ref(_map(rule).get(key), doc.loc.child("context_rules", i, key), "lexical_item", pending=True)
        for form, item in _map(data.get("defaults")).items():
            self.ref(item, doc.loc.child("defaults", form), "lexical_item", pending=True)

    # ------------------------------------------------------------ IDs across the course

    def check_uniqueness(self) -> None:
        for identifier, defs in sorted(self.ix.defs.items()):
            authored = sorted((d for d in defs if not d.generated), key=lambda d: (d.loc.file, _path_key(d.loc.path)))
            for d in authored[1:]:
                first = authored[0]
                self.error(
                    d.loc,
                    f"duplicate ID '{identifier}': already defined at {self.where(first.loc)}",
                    related=(first.loc.file,),
                )

    def check_slug_collisions(self) -> None:
        """Items whose `it` gives the same slug under the same prefix (homographs, accent pairs such as sì/si) must be
        told apart by `~sense` suffixes (docs/03 § IDs). A released ID (in ids.lock) keeps its name."""
        groups: dict[tuple[str, str], list[tuple[str, Loc]]] = {}
        for u, i, item in self.course.items():
            iid, it = _str(item.get("id")), _str(item.get("it"))
            if iid and it and ids.is_valid(iid, "lexical_item") and u.items:
                groups.setdefault((iid[:2], ids.slugify(it)), []).append((iid, u.items.loc.child("items", i, "id")))
        for (_, slug), members in sorted(groups.items()):
            if len({iid for iid, _ in members}) < 2:
                continue  # one ID, or the same ID twice (a duplicate, reported by check_uniqueness)
            for iid, loc in members:
                if "~" in iid or iid in self.lock:
                    continue
                others = [f"{o} ({self.where(oloc)})" for o, oloc in members if o != iid]
                self.error(
                    loc,
                    f"{iid} collides with {', '.join(others)}: both slug to '{slug}', so each needs a ~sense suffix "
                    f"(e.g. {ids.base_of(iid)}~<sense>)",
                    related=tuple(oloc.file for _, oloc in members),
                )

    def check_retired(self) -> None:
        doc = self.course.singles.get("retired")
        if not doc:
            return
        for rid, rloc in sorted(self.retired.items()):
            for d in self.ix.defs.get(rid, []):
                self.error(
                    rloc,
                    f"retired ID '{rid}' is reused at {self.where(d.loc)}: retired IDs are never reused (ADR-14)",
                    related=(d.loc.file,),
                )
        for i, entry in enumerate(_seq(_map(doc.data).get("retired"))):
            self.ref(_map(entry).get("replaced_by"), doc.loc.child("retired", i, "replaced_by"), ANY_KIND)

    def check_lock(self) -> None:
        lock = self.root / "content" / "ids.lock"
        if not lock.is_file():
            return
        rel = "content/ids.lock"
        for n, identifier in read_lock(lock):
            if not ids.is_global(identifier) and identifier not in ids.RESERVED_SPEAKERS:
                self.out.append(make("error", rel, (), f"'{identifier}' is not an ID (docs/03 § IDs)", line=n))
            elif identifier in self.retired:
                continue
            elif not self.ix.exists(identifier):
                self.out.append(
                    make(
                        "error",
                        rel,
                        (),
                        f"released ID '{identifier}' no longer exists: restore it, "
                        "or retire it in content/retired.yaml (ADR-14)",
                        line=n,
                    )
                )

    # ------------------------------------------------------------ review ledgers

    def check_ledgers(self) -> None:
        for rel, data in sorted(self.docs.items()):
            if not (rel.startswith("reviews/") and rel.count("/") == 1 and rel.endswith(".yaml")):
                continue
            for i, c in enumerate(_seq(_map(data).get("comments"))):
                c = _map(c)
                cloc = Loc(rel, ("comments", i))
                target, status = c.get("target"), _map(c.get("resolution")).get("status")
                if isinstance(target, str) and not self.target_exists(target):
                    msg = f"comment {c.get('id')}: unknown target '{target}'"
                    if status in ("open", "owner"):
                        self.error(cloc.child("target"), msg)
                    else:
                        self.warning(cloc.child("target"), msg + f" (resolved as {status})")
                file = c.get("file")
                if isinstance(file, str) and not (self.root / file).is_file():
                    self.warning(cloc.child("file"), f"comment {c.get('id')}: {file} doesn't exist")

    def target_exists(self, target: str) -> bool:
        """docs/04 § The review file: any ID, a text line, a conversation node, a path into a spec file, or a
        content question (`itcontent.review.target_problem`)."""
        from itcontent.review import target_problem

        return target_problem(self.course, self.ix, target) is None


def _path_key(path: tuple[str | int, ...]) -> tuple[Any, ...]:
    return tuple((0, p, "") if isinstance(p, int) else (1, 0, str(p)) for p in path)


def check(root: Path, course: Course, index: Index, docs: dict[str, Any], line_of: LineOf) -> list[Finding]:
    return Checker(root, course, index, docs, line_of).run()
