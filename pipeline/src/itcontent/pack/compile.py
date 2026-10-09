"""The walk over the course that produces every row of the pack (docs/04 § Pack build, docs/06 § Unit-level steps).

Within a unit, steps run: the opener, the lessons' steps in file order, one conversation step per task conversation,
then talk, writing and relay (those the task has), the check, and fluency (the unit's story texts; only when it has
any). Positions: `units.ord` is the index in `course.yaml` (u00 = 0); `steps.ord`, `lessons.ord`, `can_dos.ord`,
`note_items.ord` and `text_lines.ord` start at 1 (a line's ord is its `#n`); `tokens.ord` is the 0-based index in its
line, as in a payload's token array.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from itcontent import ids
from itcontent.audio_assets import AudioPlan, Resolved
from itcontent.course import Course, Doc, ExerciseRef, TextRef, UnitFiles, walk_check, walk_lesson, walk_task
from itcontent.normalize import normalize
from itcontent.pack import display
from itcontent.pack.common import BuildError, Report, cjson, mapping, opt_str, seq
from itcontent.pack.locks import LockFile, Locks, LockString, tokenized
from itcontent.pack.payloads import ExerciseInput, exercise_payload, layout_payload, pattern
from itcontent.pack.requirements import (
    HEARD_TEXT,
    LISTEN,
    READ,
    Context,
    ItemInfo,
    Pair,
    StepInfo,
    exercise_string_pairs,
    scheduled_skill,
    sort_pairs,
    step_introduces,
    string_pairs,
)
from itcontent.patterns import PatternError, expand
from itcontent.resolve import DEFINITE, INDEFINITE, INDEFINITE_FORMS
from itcontent.tokenize import WORD, tokenize
from itcontent.tts_needs import ITEMS, LEARNER, NARRATOR, LineSpec, Voicing, item_speech_text

PathT = tuple[str | int, ...]
SKILLS = ("read", "listen", "recall", "speak")
STRANDS = {"opener": "input", "practice": "language-focus", "sounds": "language-focus", "check": "assessment"}
DURATIONS = {"opener": 30, "preview_item": 25, "story_per_word": 0.6, "comprehension": 15, "note": 180}
FORMAT_SECONDS = {"conversation_turn": 40}
GENERATED_CHOICE_QUESTION = "What does it mean?"
RESERVED = {
    "ch:narrator": ("Narrator", "tells the story between the characters' lines"),
    "ch:announcer": ("Announcer", "station, shop and radio announcements"),
}


@dataclass
class Scope:
    """What a build includes. `units` are the catalog (units, items, can-dos); content comes per unit."""

    mode: str  # dev | release | mini
    units: list[UnitFiles]
    lessons: dict[str, list[Doc]]
    tasks: dict[str, Doc]
    checks: dict[str, Doc]
    assessments: dict[str, Doc]
    approved: dict[str, bool]  # repo-relative file → approved
    step_units: frozenset[str] | None = None  # units whose steps the pack holds (None: every unit)

    def content_docs(self) -> list[tuple[Doc, str, str]]:
        """(doc, kind, unit id) of every included lesson, task, check and assessment file, in course order."""
        out: list[tuple[Doc, str, str]] = []
        for u in self.units:
            out += [(d, "lesson", u.id) for d in self.lessons.get(u.id, [])]
            if u.id in self.tasks:
                out.append((self.tasks[u.id], "task", u.id))
            if u.id in self.checks:
                out.append((self.checks[u.id], "check", u.id))
        if "placement" in self.assessments:
            out.append((self.assessments["placement"], "placement", "u00"))
        if "final" in self.assessments:
            out.append((self.assessments["final"], "final", "u99"))
        return out

    def draft(self, doc: Doc | None) -> int:
        return 0 if doc is None or self.approved.get(doc.rel, False) else 1


@dataclass
class TextEntry:
    """A text the pack holds: a step's text or an exercise's inline audio or source text."""

    id: str
    unit: str
    data: Mapping[str, Any]
    lock: LockFile
    path: PathT
    heard: bool  # audio-first: listening steps and audio texts
    targets: frozenset[str]  # the lesson's target grammar points (token flag 4)
    exclude: frozenset[str]  # target points not yet taught (steps before the note)

    def line_strings(self) -> list[tuple[int, Mapping[str, Any], LockString]]:
        out = []
        for i, line in enumerate(seq(self.data.get("lines"))):
            line = mapping(line)
            out.append((i + 1, line, self.lock.plain((*self.path, "lines", i, "it"), str(line.get("it", "")))))
        return out

    def layout_strings(self) -> list[LockString]:
        if not isinstance(self.data.get("layout"), dict):
            return []
        return [s for s in self.lock.under((*self.path, "layout")) if s.fragment is None]

    def strings(self) -> list[LockString]:
        return [s for _, _, s in self.line_strings()] + self.layout_strings()

    def words(self) -> int:
        return sum(1 for s in self.strings() for t in s.tokens if t.get("kind") != "punct")

    def pairs(self, ctx: Context, exclude: frozenset[str]) -> set[Pair]:
        """What the text requires in a context. `exclude`: the target points not yet taught where it is shown (its
        own step's exclusion for `text_requires`; the exercise's step when an exercise shows it as a source)."""
        out: set[Pair] = set()
        for s in self.strings():
            out |= string_pairs(s, ctx, exclude=exclude)
        return out


@dataclass(frozen=True)
class StepContext:
    """Where a lesson step's exercises sit."""

    doc: Doc
    unit: str
    step: str
    kind: str
    targets: frozenset[str]  # the lesson's target grammar points
    exclude: frozenset[str]  # targets whose note comes after this step


@dataclass
class PackData:
    tables: dict[str, list[tuple[Any, ...]]] = field(default_factory=dict)
    payloads: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {"exercises": {}, "steps": {}, "notes": {}, "assessments": {}, "layouts": {}}
    )
    audio: AudioPlan = field(default_factory=AudioPlan)  # every voiced thing and its audio (docs/04 § Audio)
    review_files: dict[str, dict[str, str]] = field(default_factory=dict)

    def add(self, table: str, row: tuple[Any, ...]) -> None:
        self.tables.setdefault(table, []).append(row)


def _int_seconds(x: float) -> int:
    return math.floor(x + 0.5)


class Compiler:
    def __init__(
        self, course: Course, locks: Locks, scope: Scope, report: Report, audio: AudioPlan | None = None
    ) -> None:
        self.course = course
        self.locks = locks
        self.scope = scope
        self.report = report
        self.data = PackData(audio=audio or AudioPlan())
        self.audio = self.data.audio
        self.voicing = Voicing.from_course(course)
        self._item_audio: dict[str, str | None] = {}
        checker = mapping(course.singles["checker"].data) if "checker" in course.singles else {}
        strands = mapping(mapping(checker.get("strands")).get("by_kind"))
        self.strands = {**STRANDS, **{str(k): str(v) for k, v in strands.items()}}
        self.durations: dict[str, float] = {**DURATIONS, **FORMAT_SECONDS}
        for k, v in mapping(checker.get("durations_seconds")).items():
            if isinstance(v, int | float) and not isinstance(v, bool):
                self.durations[str(k)] = float(v)
        self.unit_ids = [u.id for u in scope.units]
        self.items: dict[str, dict[str, Any]] = {}  # word, chunk and sound items of the catalog
        self.item_info: dict[str, ItemInfo] = {}
        self.points: dict[str, dict[str, Any]] = {}
        self.texts: dict[str, TextEntry] = {}
        self.step_infos: list[StepInfo] = []
        self.step_ids: set[str] = set()
        self.exercise_ids: set[str] = set()
        self.note_lessons: dict[str, str] = {}  # grammar point → lesson of its first note
        self.exercise_est: dict[str, int] = {}

    # ------------------------------------------------------------ entry point

    def compile(self) -> PackData:
        self.catalog()
        self.register_texts()
        for u in self.scope.units:
            self.unit_content(u)
        self.assessments()
        for tid in sorted(self.texts):
            self.text_rows(self.texts[tid])
        self.finish_items()
        self.introductions()
        self.forms()
        return self.data

    # ------------------------------------------------------------ catalog: units, can-dos, items, …

    def catalog(self) -> None:
        order = self.course.unit_order()
        for u in self.scope.units:
            spec = mapping(u.spec.data) if u.spec else {}
            title = mapping(spec.get("title"))
            hours = spec.get("est_hours")
            minutes = _int_seconds(float(hours) * 60) if isinstance(hours, int | float) else 0
            self.data.add(
                "units",
                (
                    u.id,
                    order[u.id],
                    str(title.get("it", "")),
                    str(title.get("en", "")),
                    str(spec.get("episode", "")),
                    minutes,
                    "final" if u.is_final_review else "unit",
                ),
            )
            for i, cd in enumerate(map(mapping, seq(spec.get("can_do"))), start=1):
                self.data.add(
                    "can_dos",
                    (
                        str(cd.get("id")),
                        u.id,
                        i,
                        str(cd.get("text", "")),
                        opt_str(cd.get("scale")),
                        1 if cd.get("stretch") else 0,
                    ),
                )
        syllabus = self.course.singles.get("syllabus")
        for e in map(mapping, seq(mapping(syllabus.data if syllabus else None).get("items"))):
            self.data.add("syllabus_items", (str(e.get("id")), str(e.get("area")), str(e.get("label", ""))))
        bible = self.course.singles.get("story_bible")
        for ch in map(mapping, seq(mapping(bible.data if bible else None).get("characters"))):
            desc = next((str(ch[k]) for k in ("role", "character", "rule") if ch.get(k)), "")
            self.data.add("characters", (str(ch.get("id")), str(ch.get("name", "")), desc))
        for cid, (name, desc) in RESERVED.items():
            self.data.add("characters", (cid, name, desc))
        countries = self.course.singles.get("countries")
        for c in map(mapping, seq(mapping(countries.data if countries else None).get("countries"))):
            self.data.add(
                "countries",
                (
                    str(c.get("id")),
                    str(c.get("en", "")),
                    str(c.get("it", "")),
                    str(c.get("home_phrase", "")),
                    cjson([str(x) for x in seq(c.get("alt_home_phrases"))]),
                    str(c.get("m", "")),
                    str(c.get("f", "")),
                ),
            )
        units = set(self.unit_ids)
        for u in self.scope.units:
            if u.items is None:
                continue
            for item in map(mapping, seq(mapping(u.items.data).get("items"))):
                iid = str(item.get("id", ""))
                if iid:
                    self.items[iid] = {**item, "_unit": u.id}
        for p in self.course.grammar_points():
            if str(p.get("unit")) in units:
                self.points[str(p["id"])] = p
        for iid, item in self.items.items():
            kind = {"w": "word", "c": "chunk", "s": "sound"}[iid[0]]
            status = item.get("status")
            if isinstance(status, str):
                skills = {s: status for s in SKILLS} if kind != "sound" else {"listen": status}
            else:
                skills = {str(k): str(v) for k, v in mapping(status).items()}
            self.item_info[iid] = ItemInfo(
                iid, kind, item["_unit"], skills, exemplifies=tuple(str(x) for x in seq(item.get("exemplifies")))
            )
        for pid, p in self.points.items():
            status = str(p.get("status", "P"))
            skills = {"read": status, "recall": status} if status == "P" else {"read": status}
            self.item_info[pid] = ItemInfo(pid, "grammar", str(p.get("unit")), skills, grammar_status=status)

    def item_gloss(self, iid: str) -> str | None:
        item = self.items.get(iid)
        return str(item["gloss"]) if item and item.get("gloss") else None

    def finish_items(self) -> None:
        for iid, item in sorted(self.items.items()):
            info = self.item_info[iid]
            d, i = display.display_forms(item) if info.kind == "word" else (None, None)
            flags = (1 if item.get("cognate") else 0) | (2 if item.get("false_friend") else 0)
            audio_id = self.item_audio(iid) if info.kind in ("word", "chunk") else None
            self.data.add(
                "items",
                (
                    iid,
                    info.kind,
                    str(item.get("it", "")),
                    i,
                    d,
                    opt_str(item.get("recall_answer")),
                    str(item.get("gloss", "")),
                    cjson([str(x) for x in seq(item.get("alt_glosses"))]),
                    opt_str(item.get("note")),
                    opt_str(item.get("pos")),
                    opt_str(item.get("gender")),
                    opt_str(str(item["plural"]) if item.get("plural") is not None else None),
                    info.unit,
                    opt_str(item.get("lesson")),
                    cjson([str(x) for x in seq(item.get("topics"))]),
                    audio_id,
                    flags,
                    opt_str(item.get("letter")),
                ),
            )
            if info.kind == "sound":
                pairs = [
                    [{"it": str(w), "audioId": self.sound_word_audio(iid, j, k, str(w))} for k, w in enumerate(seq(p))]
                    for j, p in enumerate(seq(item.get("pairs")))
                ]
                self.data.add("sounds", (iid, cjson(pairs)))
        for pid, p in sorted(self.points.items()):
            title = str(p.get("title", pid))
            self.data.add(
                "items",
                (
                    pid,
                    "grammar",
                    title,
                    None,
                    None,
                    None,
                    title,
                    "[]",
                    opt_str(p.get("about")),
                    None,
                    None,
                    None,
                    str(p.get("unit")),
                    self.note_lessons.get(pid),
                    "[]",
                    None,
                    0,
                    None,
                ),
            )
            for req in seq(p.get("requires")):
                if str(req) in self.points:
                    self.data.add("item_requires", (pid, str(req)))
                else:
                    self.report.warn(f"item_requires: {pid} requires {req}, which this pack doesn't hold")
        for iid, info in sorted(self.item_info.items()):
            sched = scheduled_skill(info)
            for skill in SKILLS:
                if skill in info.skills:
                    self.data.add("item_skills", (iid, skill, info.skills[skill], 1 if skill == sched else 0))

    # ------------------------------------------------------------ texts

    def register_texts(self) -> None:
        """Every text of the included files, before any exercise refers to one (a check may use a task's text)."""
        for doc, kind, unit_id in self.scope.content_docs():
            lock = self.locks[doc.rel]
            targets, before_note = self.lesson_targets(doc) if kind == "lesson" else (frozenset(), {})
            step_kinds = {
                str(s.get("id")): str(s.get("kind")) for s in map(mapping, seq(mapping(doc.data).get("steps")))
            }
            for ref in self.walk(doc, kind, unit_id):
                if not isinstance(ref, TextRef) or not ref.id:
                    continue
                if ref.id in self.texts:
                    raise BuildError(f"{doc.rel} › {ref.loc}: text {ref.id} is defined twice")
                heard = (ref.owner == "step" and step_kinds.get(str(ref.step_id)) == "listening") or (
                    ref.loc.path[-1] == "audio_text"
                )
                exclude = before_note.get(str(ref.step_id), frozenset())
                unit = self.unit_of_ref(ref, kind)
                self.texts[ref.id] = TextEntry(ref.id, unit, ref.data, lock, ref.loc.path, heard, targets, exclude)

    def walk(self, doc: Doc, kind: str, unit_id: str) -> Iterable[ExerciseRef | TextRef]:
        if kind == "lesson":
            return walk_lesson(doc, unit_id)
        if kind == "task":
            return walk_task(doc, unit_id)
        return walk_check(doc, unit_id, kind)

    def unit_of_ref(self, ref: ExerciseRef | TextRef, kind: str) -> str:
        if kind == "placement" and isinstance(ref, ExerciseRef) and ref.section in self.unit_ids:
            return str(ref.section)
        if kind == "placement" and isinstance(ref, TextRef):
            block = ref.loc.path[1] if len(ref.loc.path) > 1 else None
            blocks = seq(mapping(self.scope.assessments["placement"].data).get("blocks"))
            if isinstance(block, int) and block < len(blocks):
                return str(mapping(blocks[block]).get("unit", ref.unit_id))
        return ref.unit_id

    def lesson_targets(self, doc: Doc) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
        """The lesson's target grammar points (its notes' `grammar`), and per step the targets whose note comes
        later in the lesson (excluded from that step's requirements: the story comes before the note)."""
        steps = [mapping(s) for s in seq(mapping(doc.data).get("steps"))]
        targets: set[str] = set()
        before: dict[str, frozenset[str]] = {}
        for i, step in enumerate(steps):
            later = {str(g) for s in steps[i + 1 :] if s.get("kind") == "note" for g in seq(s.get("grammar"))}
            before[str(step.get("id"))] = frozenset(later)
            if step.get("kind") == "note":
                targets.update(str(g) for g in seq(step.get("grammar")))
        return frozenset(targets), before

    def text_audio(self, t: TextEntry) -> Resolved | None:
        """A text's audio: its lines in one file, every word token timed (docs/04 § Audio steps 5–6)."""
        lines = t.line_strings()
        if not lines:
            return None  # a real-world layout: shown, never voiced
        specs = []
        for n, line, s in lines:
            say = {str(k): str(v) for k, v in mapping(line.get("say")).items()}
            pause = line.get("pause_ms")
            specs.append(
                LineSpec(
                    speaker=str(line.get("speaker", "")),
                    text=str(line.get("it", "")),
                    tokens=[(str(tok.get("kind")), str(tok.get("surface"))) for tok in s.tokens],
                    label=f"{t.id}#{n}",
                    say=say,
                    pause_ms=pause if isinstance(pause, int) and not isinstance(pause, bool) else 0,
                )
            )
        return self.audio.add(self.voicing.text_need(t.id, t.unit, t.lock.file, specs))

    def text_rows(self, t: TextEntry) -> None:
        title = mapping(t.data.get("title"))
        audio = self.text_audio(t)
        layout = t.data.get("layout")
        layout_json = None
        if isinstance(layout, dict):
            payload = layout_payload(layout, t.lock, (*t.path, "layout"), t.targets)
            self.data.payloads["layouts"][t.id] = payload
            layout_json = cjson(payload)
        self.data.add(
            "texts",
            (
                t.id,
                t.unit,
                str(t.data.get("kind", "")),
                opt_str(title.get("it")),
                opt_str(title.get("en")),
                layout_json,
                audio.audio_id if audio else None,
                audio.duration_ms if audio else None,
            ),
        )
        lines = t.line_strings()
        for n, line, s in lines:
            timed = audio.lines[n - 1] if audio else None
            speaker = str(line.get("speaker", ""))
            addressee = opt_str(line.get("to"))
            self.data.add(
                "text_lines",
                (
                    t.id,
                    n,
                    ids.RESERVED_SPEAKERS.get(speaker, speaker) or None,
                    ids.RESERVED_SPEAKERS.get(addressee, addressee) if addressee else None,
                    opt_str(line.get("register")),
                    str(line.get("it", "")),
                    str(line.get("en", "")),
                    timed.start_ms if timed else None,
                    timed.end_ms if timed else None,
                ),
            )
            for k, tok in enumerate(tokenized(s, t.targets)["tokens"], start=1):
                span = timed.tokens.get(k - 1) if timed else None
                self.data.add(
                    "tokens",
                    (
                        t.id,
                        n,
                        k,
                        tok["surface"],
                        tok["trailing"],
                        tok["kind"],
                        tok["itemId"],
                        tok["gloss"],
                        tok["flags"],
                        span[0] if span else None,
                        span[1] if span else None,
                    ),
                )
        for item, skill in sort_pairs(t.pairs(HEARD_TEXT if t.heard else READ, t.exclude)):
            self.data.add("text_requires", (t.id, item, skill))

    # ------------------------------------------------------------ units and their steps

    def unit_content(self, u: UnitFiles) -> None:
        if u.spec is None or (self.scope.step_units is not None and u.id not in self.scope.step_units):
            return
        steps: list[tuple[str, str, dict[str, Any], str | None, int, str | None, int]] = []

        def add(sid: str, kind: str, payload: dict[str, Any], lesson: str | None, est: int, title: str | None, d: int):
            if sid in self.step_ids:
                raise BuildError(f"step {sid} is defined twice")
            self.step_ids.add(sid)
            steps.append((sid, kind, {"kind": kind, **payload}, lesson, est, title, d))

        opener = int(self.durations["opener"])
        add(f"{u.id}.step-opener", "opener", {"unitId": u.id}, None, opener, None, self.scope.draft(u.spec))
        self.step_infos.append(StepInfo(f"{u.id}.step-opener", u.id, "opener"))
        story_ids: list[str] = []
        for doc in self.scope.lessons.get(u.id, []):
            self.lesson(u, doc, add, story_ids)
        task = self.scope.tasks.get(u.id)
        if task is not None:
            self.task(u, task, add)
        check = self.scope.checks.get(u.id)
        if check is not None:
            self.check(u, check, add)
        if story_ids:
            words = sum(self.texts[t].words() for t in story_ids)
            rate = self.durations.get("fluency_rate", 1.15)
            est = _int_seconds(words * self.durations["story_per_word"] / rate)
            drafts = [self.scope.draft(d) for d in self.scope.lessons.get(u.id, [])]
            add(f"{u.id}.step-fluency", "fluency", {"textIds": story_ids, "rate": rate}, None, est, None, max(drafts))
            self.step_infos.append(StepInfo(f"{u.id}.step-fluency", u.id, "fluency"))
        for ord_, (sid, kind, payload, lesson, est, title, draft) in enumerate(steps, start=1):
            strand = self.strands.get(kind)
            if strand is None:
                raise BuildError(f"step {sid}: no strand for kind {kind!r} (content/checker.yaml strands.by_kind)")
            self.data.payloads["steps"][sid] = payload
            self.data.add("steps", (sid, u.id, lesson, ord_, kind, title, cjson(payload), est, strand, draft))

    def lesson(self, u: UnitFiles, doc: Doc, add, story_ids: list[str]) -> None:
        data = mapping(doc.data)
        lesson_id = str(data.get("id"))
        targets, before_note = self.lesson_targets(doc)
        draft = self.scope.draft(doc)
        total = 0
        for i, step in enumerate(map(mapping, seq(data.get("steps")))):
            sid = str(step.get("id"))
            kind = str(step.get("kind"))
            path: PathT = ("steps", i)
            info = StepInfo(sid, u.id, kind)
            title: str | None = None
            ctx = StepContext(doc, u.id, sid, kind, targets, before_note.get(sid, frozenset()))
            if kind == "preview":
                payload, est = self.preview(u, step, sid, doc)
                info.preview_items = [str(x) for b in seq(step.get("batches")) for x in seq(b)]
            elif kind in ("story", "listening", "reading"):
                text = mapping(step.get("text"))
                tid = str(text.get("id"))
                t = self.texts[tid]
                key = "questions" if kind == "story" else "exercises"
                exercise_ids = []
                for j, e in enumerate(seq(step.get(key))):
                    learn = kind != "story" and bool(seq(mapping(e).get("targets")))
                    exercise_ids.append(
                        self.step_exercise(ctx, e, (*path, key, j), "learn" if learn else "comprehension")
                    )
                est = _int_seconds(t.words() * self.durations["story_per_word"]) + self.exercise_seconds(exercise_ids)
                if kind == "story":
                    payload = {"textId": tid, "questionIds": exercise_ids}
                    story_ids.append(tid)
                elif kind == "listening":
                    plays = step.get("plays")
                    payload = {
                        "textId": tid,
                        "plays": plays if isinstance(plays, int) and not isinstance(plays, bool) else None,
                        "exerciseIds": exercise_ids,
                    }
                else:
                    payload = {"textId": tid, "exerciseIds": exercise_ids}
                title = opt_str(mapping(text.get("title")).get("en"))
                info.new_text_items = self.new_items(t)
                info.detected_grammar = sorted({d.point for s in t.strings() for d in s.detections})
            elif kind == "note":
                payload = {"noteId": str(step.get("note_id"))}
                est = int(self.durations["note"])
                title = opt_str(step.get("title_en"))
                info.note_grammar = [str(g) for g in seq(step.get("grammar"))]
                self.note(u, doc, step, path, sid, targets)
            elif kind == "practice":
                block = [self.step_exercise(ctx, e, (*path, "block", j)) for j, e in enumerate(seq(step.get("block")))]
                mix = [self.step_exercise(ctx, e, (*path, "mix", j)) for j, e in enumerate(seq(step.get("mix")))]
                payload = {"block": block, "mix": mix}
                est = self.exercise_seconds(block + mix)
            elif kind == "sounds":
                exercises = seq(step.get("exercises"))
                exercise_ids = [self.step_exercise(ctx, e, (*path, "exercises", j)) for j, e in enumerate(exercises)]
                payload = {"exerciseIds": exercise_ids}
                est = self.exercise_seconds(exercise_ids)
                info.sound_items = sorted(
                    {
                        str(t.get("item"))
                        for e in exercises
                        for t in map(mapping, seq(mapping(e).get("targets")))
                        if str(t.get("item", "")).startswith("s:")
                    }
                )
            elif kind == "use":
                eid = self.step_exercise(ctx, step.get("exercise"), (*path, "exercise"))
                payload = {"exerciseId": eid}
                est = self.exercise_seconds([eid])
                title = opt_str(mapping(mapping(step.get("exercise")).get("title")).get("en"))
            else:
                raise BuildError(f"{doc.rel} › steps[{i}]: unknown step kind {kind!r}")
            add(sid, kind, payload, lesson_id, est, title, draft)
            self.step_infos.append(info)
            total += est
        title = mapping(data.get("title"))
        self.data.add(
            "lessons",
            (
                lesson_id,
                u.id,
                self.lesson_ord(lesson_id),
                str(title.get("it", "")),
                str(title.get("en", "")),
                math.ceil(total / 60),
            ),
        )

    def step_exercise(self, ctx: StepContext, data: Any, path: PathT, role: str = "learn") -> str:
        return self.exercise(
            mapping(data), path, ctx.doc, ctx.unit, ctx.step, ctx.kind, role, targets=ctx.targets, exclude=ctx.exclude
        )

    @staticmethod
    def lesson_ord(lesson_id: str) -> int:
        try:
            return int(lesson_id.rsplit(".l", 1)[1])
        except (IndexError, ValueError) as exc:
            raise BuildError(f"lesson id {lesson_id!r} has no number") from exc

    def new_items(self, t: TextEntry) -> list[str]:
        """Items of tokens flagged new in a text (introduced by its step, docs/05)."""
        out = []
        for s in t.strings():
            for tok in s.tokens:
                if "new" in (tok.get("flags") or ()):
                    item = tok.get("chunk") or tok.get("item")
                    if item and not str(item).startswith("g:") and item not in out:
                        out.append(str(item))
        return out

    def task(self, u: UnitFiles, doc: Doc, add) -> None:
        data = mapping(doc.data)
        draft = self.scope.draft(doc)
        for n, conv in enumerate(seq(data.get("conversations")), start=1):
            sid = f"{u.id}.step-conversation-{n}"
            eid = self.exercise(mapping(conv), ("conversations", n - 1), doc, u.id, sid, "conversation", "learn")
            title = opt_str(mapping(mapping(conv).get("title")).get("en"))
            add(sid, "conversation", {"exerciseId": eid}, None, self.exercise_seconds([eid]), title, draft)
            self.step_infos.append(StepInfo(sid, u.id, "conversation"))
        for key in ("talk", "writing", "relay"):
            if isinstance(data.get(key), dict):
                sid = f"{u.id}.step-{key}"
                eid = self.exercise(data[key], (key,), doc, u.id, sid, key, "learn")
                add(sid, key, {"exerciseId": eid}, None, self.exercise_seconds([eid]), None, draft)
                self.step_infos.append(StepInfo(sid, u.id, key))

    def check(self, u: UnitFiles, doc: Doc, add) -> None:
        data = mapping(doc.data)
        sid = f"{u.id}.step-check"
        sections = []
        for s, sec in enumerate(map(mapping, seq(data.get("sections")))):
            exercise_ids = [
                self.exercise(mapping(e), ("sections", s, "exercises", j), doc, u.id, sid, "check", "check")
                for j, e in enumerate(seq(sec.get("exercises")))
            ]
            sections.append(
                {"id": str(sec.get("id")), "titleEn": str(sec.get("title_en", "")), "exerciseIds": exercise_ids}
            )
        rule = mapping(data.get("pass"))
        payload = {
            "checkId": str(data.get("id")),
            "pass": {"overall": float(rule.get("overall", 0.7)), "sectionMin": float(rule.get("section_min", 0.5))},
            "sections": sections,
        }
        est = self.exercise_seconds([e for sec in sections for e in sec["exerciseIds"]])
        add(sid, "check", payload, None, est, None, self.scope.draft(doc))
        self.step_infos.append(StepInfo(sid, u.id, "check"))

    # ------------------------------------------------------------ assessments (placement, final check)

    def assessments(self) -> None:
        if "placement" in self.scope.assessments:
            doc = self.scope.assessments["placement"]
            data = mapping(doc.data)
            blocks = []
            for b, block in enumerate(map(mapping, seq(data.get("blocks")))):
                unit = str(block.get("unit"))
                if unit not in self.unit_ids:
                    continue  # a partial release: the block's unit isn't shipped
                exercise_ids = [
                    self.exercise(mapping(e), ("blocks", b, "exercises", j), doc, unit, None, None, "placement")
                    for j, e in enumerate(seq(block.get("exercises")))
                ]
                blocks.append({"unitId": unit, "exerciseIds": exercise_ids})
            payload = {"id": "placement", "advanceThreshold": int(data.get("advance_threshold", 4)), "blocks": blocks}
            self.data.payloads["assessments"]["placement"] = payload
            self.data.add("assessments", ("placement", cjson(payload)))
        if "final" in self.scope.assessments:
            doc = self.scope.assessments["final"]
            data = mapping(doc.data)
            unit = "u99" if "u99" in self.unit_ids else None
            sections = []
            for s, sec in enumerate(map(mapping, seq(data.get("sections")))):
                exercises = seq(sec.get("exercises"))
                if exercises and unit is None:
                    raise BuildError(f"{doc.rel}: final-check exercises need the final review unit u99 in the pack")
                exercise_ids = [
                    self.exercise(mapping(e), ("sections", s, "exercises", j), doc, str(unit), None, None, "final")
                    for j, e in enumerate(exercises)
                ]
                sections.append(
                    {
                        "id": str(sec.get("id")),
                        "titleEn": str(sec.get("title_en", "")),
                        "max": int(sec.get("max", 12)),
                        "exerciseIds": exercise_ids,
                    }
                )
            payload = {
                "id": "final",
                "indicativePassPerSection": int(data.get("indicative_pass_per_section", 7)),
                "sections": sections,
            }
            self.data.payloads["assessments"]["final"] = payload
            self.data.add("assessments", ("final", cjson(payload)))

    # ------------------------------------------------------------ exercises

    def exercise(
        self,
        data: Mapping[str, Any],
        path: PathT,
        doc: Doc,
        unit_id: str,
        step_id: str | None,
        step_kind: str | None,
        role: str,
        *,
        targets: frozenset[str] = frozenset(),
        exclude: frozenset[str] = frozenset(),
    ) -> str:
        eid = str(data.get("id", ""))
        fmt = str(data.get("format", ""))
        if not eid:
            raise BuildError(f"{doc.rel} › {path}: an exercise without an id")
        if eid in self.exercise_ids:
            raise BuildError(f"exercise {eid} is defined twice")
        self.exercise_ids.add(eid)
        lock = self.locks[doc.rel]
        source, source_ref, audio_text_id, text_pairs = self.sources(data, path, doc, exclude)
        x = ExerciseInput(
            data, path, lock, unit_id, step_id, step_kind, role, targets, source, audio_text_id, self.item_gloss
        )
        payload = exercise_payload(x)
        self.exercise_audio(payload, data, doc.rel, unit_id)
        skip = [f"{s}" for s in (_fmt((*path, "audio_text")), _fmt((*path, "source")))]
        pairs: set[Pair] = set(text_pairs)
        for s in lock.under(path):
            if any(s.path == p or s.path.startswith(p + ".") or s.path.startswith(p + "[") for p in skip):
                continue
            pairs |= exercise_string_pairs(fmt, s, exclude=exclude)
        primary = [(t["itemId"], t["skill"]) for t in payload["targets"]]
        pairs |= set(primary)
        est = self.format_seconds(data, fmt, role)
        self.data.add(
            "exercises",
            (eid, fmt, unit_id, step_id, role, cjson(payload), int(payload["score"]), est, source_ref),
        )
        for item, skill in sorted(set(primary)):
            self.data.add("exercise_targets", (eid, item, skill))
        for item, skill in sort_pairs(pairs):
            self.data.add("exercise_requires", (eid, item, skill))
        for tag in sorted(set(payload["tags"])):
            self.data.add("exercise_tags", (eid, tag))
        self.data.payloads["exercises"][eid] = payload
        self.exercise_est[eid] = est
        return eid

    def sources(
        self, data: Mapping[str, Any], path: PathT, doc: Doc, exclude: frozenset[str]
    ) -> tuple[dict[str, Any] | None, str | None, str | None, set[Pair]]:
        """(payload source, source_ref column, audio text ID, what the shown or heard texts require)."""
        pairs: set[Pair] = set()
        source = None
        source_ref = None
        audio_text_id = None
        where = f"{doc.rel} › {_fmt(path)}"

        def text(tid: str) -> TextEntry:
            if tid not in self.texts:
                raise BuildError(f"{where}: text {tid} is not in this pack")
            return self.texts[tid]

        at = data.get("audio_text")
        if isinstance(at, dict | str):
            tid = str(at.get("id")) if isinstance(at, dict) else at
            pairs |= text(tid).pairs(LISTEN, exclude)
            audio_text_id = tid
        src = data.get("source")
        if isinstance(src, str):
            line = ids.split_line_ref(src)
            if line:
                t = text(line[0])
                lines = t.line_strings()
                if not 1 <= line[1] <= len(lines):
                    raise BuildError(f"{where}: {src} is not a line of {line[0]}")
                pairs |= string_pairs(lines[line[1] - 1][2], READ, exclude=exclude)
                source = {"textId": line[0], "line": line[1]}
            else:
                pairs |= text(src).pairs(READ, exclude)
                source = {"textId": src, "line": None}
            source_ref = src
        elif isinstance(src, dict):
            if "text" in src:
                tid = str(src["text"].get("id")) if isinstance(src["text"], dict) else str(src["text"])
                pairs |= text(tid).pairs(READ, exclude)
                source = {"textId": tid, "line": None}
                source_ref = tid
            elif isinstance(src.get("audio_text"), dict):
                tid = str(src["audio_text"].get("id"))
                pairs |= text(tid).pairs(LISTEN, exclude)
                audio_text_id = tid
                source_ref = tid
        return source, source_ref, audio_text_id, pairs

    def format_seconds(self, data: Mapping[str, Any], fmt: str, role: str) -> int:
        if role == "comprehension":
            return int(self.durations["comprehension"])
        if fmt == "conversation":
            return int(self.durations["conversation_turn"] * max(1, conversation_turns(data)))
        if fmt not in self.durations:
            raise BuildError(f"content/checker.yaml has no durations_seconds.{fmt}")
        return int(self.durations[fmt])

    def exercise_seconds(self, exercise_ids: list[str]) -> int:
        return sum(self.exercise_est[e] for e in exercise_ids)

    # ------------------------------------------------------------ audio (docs/04 § Audio; voices: tts_needs)

    def item_audio(self, iid: str) -> str | None:
        """An item's audio (its display form, or `audio_say`), shared by its row and the generated preview."""
        if iid not in self._item_audio:
            item = self.items[iid]
            shown = None
            if self.item_info[iid].kind == "word":
                d, _ = display.display_forms(item)
                shown = display.strip_gender_mark(d) if d else None
            text, why = item_speech_text(item, shown)
            unit = str(item["_unit"])
            part = self.items_file(unit)
            need = self.voicing.single(f"item:{iid}", "item", iid, unit, part, text, ITEMS, why or iid)
            self._item_audio[iid] = self.audio.audio_id(need)
        return self._item_audio[iid]

    def items_file(self, unit_id: str) -> str:
        u = next((u for u in self.scope.units if u.id == unit_id), None)
        return u.items.rel if u is not None and u.items is not None else f"content/items/{unit_id}.yaml"

    def sound_word_audio(self, iid: str, pair: int, word: int, text: str) -> str | None:
        unit = str(self.items[iid]["_unit"])
        key = f"sound:{iid}:{pair}:{word}"
        need = self.voicing.single(key, "sound", iid, unit, self.items_file(unit), text, ITEMS, f"{iid} pair {pair}")
        return self.audio.audio_id(need)

    def exercise_audio(self, payload: dict[str, Any], data: Mapping[str, Any], part: str, unit_id: str) -> None:
        """Fill the audio IDs of an authored exercise's voiced strings (docs/04 § Audio step 1): dictation and repeat
        lines, sound-pair words, conversation lines, a voiced `prompt_it` (`audio`), talk models, and model answers
        with `audio_after`."""
        eid = str(payload["id"])
        fmt = payload["format"]

        def voiced(slot: str, text: str | None, speaker: str, why: str = "") -> str | None:
            label = why or f"{eid}:{slot}"
            need = self.voicing.single(f"exercise:{eid}:{slot}", "exercise", eid, unit_id, part, text, speaker, label)
            return self.audio.audio_id(need)

        after = bool(payload.get("audioAfter"))
        if fmt in ("dictation", "repeat"):
            payload["audioId"] = voiced("audioId", payload["say"]["text"], NARRATOR)
        elif fmt == "cloze" and after:
            text = str(data.get("text", ""))
            gap = text[text.find("[[") + 2 : text.find("]]")]
            model, why = model_answer(gap, f"{eid}:audioId")
            sentence = text[: text.find("[[")] + model + text[text.find("]]") + 2 :] if model is not None else None
            payload["audioId"] = voiced("audioId", sentence, LEARNER, why)
        elif fmt == "recall" and after:
            model, why = model_answer(str(data.get("answer", "")), f"{eid}:answerAudioId")
            payload["answerAudioId"] = voiced("answerAudioId", model, LEARNER, why)
        elif fmt == "sentence-building" and after:
            payload["answerAudioId"] = voiced("answerAudioId", (payload["answers"] or [""])[0], LEARNER)
        elif fmt == "choice" and payload["promptIt"] is not None and isinstance(data.get("audio"), dict):
            speaker = str(data["audio"].get("speaker", ""))
            payload["promptAudioId"] = voiced("promptAudioId", payload["promptIt"]["text"], speaker)
        elif fmt == "sound-pair":
            for j, w in enumerate(payload["pair"] or []):
                w["audioId"] = voiced(f"pair[{j}]", w["it"], ITEMS)
            if payload["word"]:
                payload["word"]["audioId"] = voiced("word", payload["word"]["it"], ITEMS)
        elif fmt == "conversation":
            with_ = str(data.get("with", ""))
            for node in payload["nodes"]:
                node["audioId"] = voiced(f"nodes.{node['id']}", node["say"]["text"], with_)
        elif fmt == "talk":
            payload["modelAudioId"] = voiced("modelAudioId", payload["model"]["text"], LEARNER)

    # ------------------------------------------------------------ preview (generated exercises, docs/06 § 1)

    def preview(self, u: UnitFiles, step: Mapping[str, Any], sid: str, doc: Doc) -> tuple[dict[str, Any], int]:
        batches = []
        est = 0
        unit_items = [iid for iid, it in self.items.items() if it["_unit"] == u.id]
        for k, batch in enumerate(seq(step.get("batches")), start=1):
            batch_ids = [str(x) for x in seq(batch)]
            for iid in batch_ids:
                if iid not in self.items:
                    raise BuildError(f"{doc.rel} › {sid}: preview item {iid} is not in this pack")
            exercise_ids: list[str] = []
            if len(batch_ids) >= 2:
                exercise_ids.append(self.preview_match(f"{sid}.b{k}.match", batch_ids, u.id, sid))
            for iid in batch_ids:
                gid = f"{sid}.b{k}.{ids.generated_item_suffix(iid)}"
                info = self.item_info[iid]
                if info.kind in ("word", "chunk") and info.skills.get("recall") == "P":
                    exercise_ids.append(self.preview_recall(gid, iid, u.id, sid))
                else:
                    exercise_ids.append(self.preview_choice(gid, iid, batch_ids, unit_items, u.id, sid))
            batches.append({"itemIds": batch_ids, "exerciseIds": exercise_ids})
            est += int(self.durations["preview_item"]) * len(batch_ids)
        return {"batches": batches}, est

    def display_text(self, iid: str) -> dict[str, Any]:
        """A TokenizedText of an item's display form: every word token belongs to the item."""
        item = self.items[iid]
        d, _ = display.display_forms(item) if self.item_info[iid].kind == "word" else (None, None)
        shown = d or str(item.get("it", ""))
        bare = display.strip_gender_mark(shown)
        mark = shown[len(bare) :]
        lead, toks = tokenize(bare)
        tokens = [
            {
                "surface": t.surface,
                "trailing": t.trailing,
                "kind": t.kind if t.kind != "name" else "word",
                "itemId": iid if t.kind == WORD else None,
                "gloss": None,
                "flags": 0,
            }
            for t in toks
        ]
        if tokens:
            tokens[-1]["trailing"] += mark
        return {"text": lead + "".join(t["surface"] + t["trailing"] for t in tokens), "lead": lead, "tokens": tokens}

    def generated(self, gid: str, fmt: str, unit_id: str, sid: str, targets: list[Pair], body: dict[str, Any]) -> str:
        if gid in self.exercise_ids:
            raise BuildError(f"generated exercise {gid} collides with another exercise")
        self.exercise_ids.add(gid)
        payload = {
            "id": gid,
            "format": fmt,
            "role": "learn",
            "unitId": unit_id,
            "stepId": sid,
            "score": 1,
            "targets": [{"itemId": i, "skill": s} for i, s in targets],
            "tags": [],
            "source": None,
            "hint": None,
            "rule": None,
            "near": body.pop("near", []),
            "audioAfter": False,
            **body,
        }
        est = int(self.durations[fmt])
        self.data.add("exercises", (gid, fmt, unit_id, sid, "learn", cjson(payload), 1, est, None))
        for item, skill in sort_pairs(targets):
            self.data.add("exercise_targets", (gid, item, skill))
            self.data.add("exercise_requires", (gid, item, skill))
        self.data.payloads["exercises"][gid] = payload
        self.exercise_est[gid] = est  # its Italian is the items' display forms, voiced with the items
        return gid

    def preview_match(self, gid: str, batch: list[str], unit_id: str, sid: str) -> str:
        pairs = [
            {
                "left": self.display_text(iid),
                "right": display.primary_gloss(str(self.items[iid].get("gloss", ""))),
                "leftAudioId": self.item_audio(iid),
            }
            for iid in batch
        ]
        return self.generated(gid, "match", unit_id, sid, [(i, "read") for i in batch], {"pairs": pairs})

    def preview_recall(self, gid: str, iid: str, unit_id: str, sid: str) -> str:
        item = self.items[iid]
        found = display.recall_answer(item, self.item_info[iid].kind)
        if found is None:
            raise BuildError(f"{iid}: no generated recall answer (a chunk with '/' needs recall_answer)")
        answer, near = found
        body = {
            "promptEn": display.primary_gloss(str(item.get("gloss", ""))),
            "contextIt": None,
            "answer": pattern(answer, f"{gid}.answer"),
            "answerAudioId": None,
            "near": [{"answer": pattern(n.answer, f"{gid}.near"), "outcome": n.outcome, "hint": n.hint} for n in near],
        }
        return self.generated(gid, "recall", unit_id, sid, [(iid, "recall")], body)

    def preview_choice(
        self, gid: str, iid: str, batch: list[str], unit_items: list[str], unit_id: str, sid: str
    ) -> str:
        """Italian → English: the gloss and two distractors, first from the same batch, then from the same unit,
        with the same part of speech where possible (docs/06 § 1)."""
        item = self.items[iid]
        right = display.primary_gloss(str(item.get("gloss", "")))
        taken = {right.lower(), *(str(g).lower() for g in seq(item.get("alt_glosses")))}
        pos = item.get("pos") or self.item_info[iid].kind

        def same_pos(x: str) -> bool:
            return (self.items[x].get("pos") or self.item_info[x].kind) == pos

        pool = [x for x in batch if x != iid]
        rest = [x for x in unit_items if x != iid and x not in batch]
        ordered = [x for x in pool if same_pos(x)] + [x for x in pool if not same_pos(x)]
        ordered += [x for x in rest if same_pos(x)] + [x for x in rest if not same_pos(x)]
        distractors: list[str] = []
        for x in ordered:
            g = display.primary_gloss(str(self.items[x].get("gloss", "")))
            if g and g.lower() not in taken and len(distractors) < 2:
                taken.add(g.lower())
                distractors.append(g)
        if not distractors:
            raise BuildError(f"{gid}: no distractor glosses for {iid}")
        body = {
            "promptIt": self.display_text(iid),
            "promptAudioId": self.item_audio(iid),
            "audioTextId": None,
            "plays": None,
            "questionEn": GENERATED_CHOICE_QUESTION,
            "options": [{"text": g, "it": None} for g in [right, *distractors]],
            "answer": 0,
        }
        return self.generated(gid, "choice", unit_id, sid, [(iid, "read")], body)

    # ------------------------------------------------------------ notes (docs/06 § 5)

    def note(
        self, u: UnitFiles, doc: Doc, step: Mapping[str, Any], path: PathT, sid: str, targets: frozenset[str]
    ) -> None:
        nid = str(step.get("note_id"))
        grammar = [str(g) for g in seq(step.get("grammar"))]
        intro = mapping(step.get("intro"))
        blocks: list[dict[str, Any]] = []
        for b, block in enumerate(map(mapping, seq(step.get("body")))):
            if "p" in block:
                blocks.append({"p": str(block["p"])})
            elif "tip" in block:
                blocks.append({"tip": str(block["tip"])})
            elif "table" in block:
                table = mapping(block["table"])
                blocks.append(
                    {
                        "table": {
                            "columns": [str(c) for c in seq(table.get("columns"))],
                            "rows": [[str(c) for c in seq(r)] for r in seq(table.get("rows"))],
                        }
                    }
                )
            elif "examples" in block:
                examples = []
                for ref in seq(block["examples"]):
                    line = ids.split_line_ref(str(ref))
                    if line is None or line[0] not in self.texts:
                        raise BuildError(f"{doc.rel} › {_fmt((*path, 'body', b))}: example {ref!r} is not a text line")
                    t = self.texts[line[0]]
                    lines = t.line_strings()
                    if not 1 <= line[1] <= len(lines):
                        raise BuildError(f"{doc.rel}: {ref} is not a line of {line[0]}")
                    _, raw, s = lines[line[1] - 1]
                    highlight = [
                        k
                        for k, tok in enumerate(s.tokens)
                        if set(tok.get("detections") or ()) & set(grammar) or tok.get("item") in grammar
                    ]
                    examples.append(
                        {
                            "ref": str(ref),
                            "textId": line[0],
                            "line": line[1],
                            "text": tokenized(s, t.targets),
                            "highlight": highlight,
                            "en": str(raw.get("en", "")),
                        }
                    )
                blocks.append({"examples": examples})
            else:
                raise BuildError(f"{doc.rel} › {_fmt((*path, 'body', b))}: unknown note block")
        body = {
            "noteId": nid,
            "titleEn": str(step.get("title_en", "")),
            "grammar": grammar,
            "intro": {"mascot": str(intro.get("mascot") or "think"), "textEn": str(intro.get("text_en", ""))}
            if intro
            else None,
            "blocks": blocks,
        }
        self.data.payloads["notes"][nid] = body
        self.data.add("grammar_notes", (nid, u.id, sid, body["titleEn"], cjson(body)))
        lesson = str(mapping(doc.data).get("id"))
        for k, g in enumerate(grammar, start=1):
            self.data.add("note_items", (nid, g, k))
            self.note_lessons.setdefault(g, lesson)

    # ------------------------------------------------------------ introductions, forms

    def introductions(self) -> None:
        for sid, rows in step_introduces(self.step_infos, self.item_info).items():
            for item, skill in rows:
                self.data.add("step_introduces", (sid, item, skill))

    def forms(self) -> None:
        """Surface forms that occur in course content, normalised, with the items they are forms of (docs/03):
        every word token of the included files (near-misses aside) plus the items' declared forms."""
        known = set(self.item_info)
        rows: set[tuple[str, str, str]] = set()
        docs = [d for d, _, _ in self.scope.content_docs()]
        docs += [u.spec for u in self.scope.units if u.spec] + [u.items for u in self.scope.units if u.items]
        for doc in docs:
            for s in self.locks[doc.rel].all():
                if s.role == "near":
                    continue
                for t in s.tokens:
                    if t.get("kind") != "word":
                        continue
                    form = normalize(str(t["surface"]))
                    item = t.get("chunk") or t.get("item")
                    if "lexical_article" in (t.get("flags") or ()):
                        item = INDEFINITE if form in INDEFINITE_FORMS else DEFINITE
                    if not item or item not in known or not form:
                        continue
                    for a in t.get("analyses") or [""]:
                        morph = a.split(" ", 1)[1] if " " in a else ""
                        rows.add((form, str(item), morph))
        for iid, item in self.items.items():
            if self.item_info[iid].kind != "word":
                continue
            forms = [item.get("it"), *seq(item.get("forms"))]
            if item.get("plural") and item.get("plural") != "invariable":
                forms.append(item["plural"])
            for f in forms:
                if isinstance(f, str) and (form := normalize(f)) and " " not in form:
                    rows.add((form, iid, ""))
        for row in sorted(rows):
            self.data.add("forms", row)


def model_answer(source: str, label: str) -> tuple[str | None, str]:
    """(the model answer as written, or None, and why not): the first expansion of a pattern (docs/03); one with a
    personal slot (`{NAME}`) can't be voiced for every learner."""
    try:
        first = next(iter(expand(source)), None)
    except PatternError as exc:
        return None, f"{label}: {exc}"
    if first is None:
        return None, f"{label}: the pattern has no expansion"
    if first.slots:
        return None, f"{label}: the model answer has a personal slot ({first.raw})"
    return first.raw, ""


def _fmt(path: PathT) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (("." if out else "") + str(p))
    return out


def conversation_turns(data: Mapping[str, Any]) -> int:
    """The learner's turns on the longest path through a conversation (nodes with `expect`)."""
    nodes = {str(k): mapping(v) for k, v in mapping(data.get("nodes")).items()}

    def longest(nid: str, seen: frozenset[str]) -> int:
        node = nodes.get(nid)
        if node is None or nid in seen or not seq(node.get("expect")):
            return 0
        nexts = {str(mapping(i).get("next")) for i in seq(node.get("expect"))}
        return 1 + max((longest(n, seen | {nid}) for n in nexts), default=0)

    return longest(str(data.get("start", "")), frozenset())
