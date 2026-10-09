"""Check 3 · Recycling and balance (docs/04): warnings unless stated.

What is measured (and always reported in check.md / `content report`):

- **Encounters** of each word or chunk item from its first introduction to course end: its tokens in every string the
  learner meets (text lines, layouts, prompts, `say`, options, match sides, notes, `help`, models and model answers;
  not titles, other expansions or near misses). A chunk counts once per occurrence; a lexical article doesn't count
  apart from its noun. P items need `encounters_p_min` (error below `encounters_p_error_below`), R items
  `encounters_r_min`. Judged only once every unit from the item's unit to the end is complete.
- **Retrievals in the introducing lesson** (the item's `lesson`, written): the preview counts 2; then each exercise
  of the lesson that targets the item, has it in the model answer of a production format (recall, sentence building,
  dictation, a cloze gap, a conversation turn's first accepted expansion) or pairs it in a `match`. Repeat-after-me
  and text the learner only reads don't count. P items need `retrievals_in_lesson_p_min` (error below
  `retrievals_in_lesson_p_error_below`). Judged as soon as the lesson exists.
- **Recycling:** the share of content-word tokens (nouns, verbs, adjectives and adverbs, and chunks) in a unit's texts
  whose item comes from an earlier unit, at least `earlier_unit_content_share_min` (not for the first unit).
- **Grammar spiral:** every point is detected or targeted in at least `grammar_spiral_later_units_min` later units
  (points of the last two teaching units: in the final review). Judged once every later unit is complete.
- **Strand balance:** estimated minutes per strand from `durations_seconds` and `strands.by_kind` (the check is
  assessment and isn't counted), each strand within its band in `strands.bands` (CL21). A band's bound is a share, or
  `{unit: share}` whose shares each hold from their unit on in course order (language focus: 60% in Units 0–2, 50%
  from Unit 3). A story or listening text counts its words read (`story_per_word`) and heard (`audio_per_word`); a
  listening text is heard twice (`LISTENING_PLAYS`).
- **Story length:** each story text's word count (non-punctuation tokens) within its unit spec's `texts.stories.words`.

Unit-level findings (recycling, strand balance) need a complete unit; an incomplete one gets one *pending* line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from itcontent.checks.alignment import pending_line
from itcontent.checks.context import LEXICAL_ARTICLE, CheckContext, Str
from itcontent.course import ExerciseRef, Loc, exercises, lesson_steps, walk_task

PLAIN_ROLES = frozenset(
    {
        "line",
        "layout",
        "prompt",
        "context",
        "say",
        "option",
        "pair",
        "label",
        "note",
        "cell",
        "example",
        "help",
        "model",
    }
)
CONTENT_POS = frozenset({"noun", "verb", "adj", "adv"})
STRANDS = ("input", "language-focus", "output", "fluency")
LISTENING_PLAYS = 2  # a listening text is heard twice (CL21); a story once
DEFAULT_BAND = (0.15, 0.35)


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def encounter_string(s: Str) -> bool:
    if s.pos is None or s.container in ("unit", "items"):
        return False
    if s.role in PLAIN_ROLES:
        return True
    return s.role in ("answer", "accept", "cloze") and bool(s.model)


def refs_in(s: Str, *, only: tuple[int, int] | None = None) -> list[str]:
    """The word and chunk items a string's tokens stand for (a chunk once per occurrence)."""
    out: list[str] = []
    prev_chunk = None
    for t in s.tokens:
        if only is not None and not (only[0] <= t.i <= only[1]):
            prev_chunk = t.chunk
            continue
        if t.chunk:
            if t.chunk != prev_chunk:
                out.append(t.chunk)
        elif t.ref and LEXICAL_ARTICLE not in t.flags:
            out.append(t.ref)
        prev_chunk = t.chunk
    return out


@dataclass
class ItemStats:
    id: str
    unit: str
    status: str  # P | R
    lesson: str | None
    encounters: int = 0
    retrievals: int | None = None  # None: its lesson isn't written
    judged: bool = False  # encounters judged (the course is complete from its unit on)


@dataclass
class UnitStats:
    id: str
    complete: bool
    seconds: dict[str, float] = field(default_factory=lambda: dict.fromkeys(STRANDS, 0.0))
    bands: dict[str, tuple[float, float]] = field(default_factory=dict)  # strand → (min, max) share in this unit
    content_tokens: int = 0
    earlier_tokens: int = 0

    @property
    def total(self) -> float:
        return sum(self.seconds.values())

    def share(self, strand: str) -> float:
        return self.seconds[strand] / self.total if self.total else 0.0

    @property
    def recycled(self) -> float | None:
        return self.earlier_tokens / self.content_tokens if self.content_tokens else None


@dataclass
class StoryLength:
    text: str
    unit: str
    words: int
    low: int | None
    high: int | None
    loc: Loc


@dataclass
class RecyclingResult:
    items: list[ItemStats] = field(default_factory=list)
    units: list[UnitStats] = field(default_factory=list)
    stories: list[StoryLength] = field(default_factory=list)
    spiral: dict[str, list[str]] = field(default_factory=dict)  # point → later units where it returns


def is_p(status: Any) -> bool:
    return status == "P" or (isinstance(status, dict) and status.get("recall") == "P")


def _share(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def bound_for(value: Any, unit: str, order: dict[str, int], default: float) -> float:
    """One bound of a strand band for one unit: a share, or `{unit: share}` whose shares each hold from their unit on
    (course order). Keys outside the course are ignored here (`Recycling.bands` reports them)."""
    share = _share(value)
    if share is not None:
        return share
    steps: list[tuple[int, float]] = []
    for key, x in _map(value).items():
        v = _share(x)
        if key in order and v is not None:
            steps.append((order[key], v))
    if not steps:
        return default
    steps.sort()
    here = order.get(unit, len(order))
    out = steps[0][1]
    for start, v in steps:
        if start <= here:
            out = v
    return out


class Recycling:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx
        self.cfg = _map(ctx.checker.get("recycling"))
        self.result = RecyclingResult()
        self.complete_from: list[bool] = []  # index i: every unit from i to the end is complete
        tail = True
        for u in reversed(ctx.course.units):
            tail = tail and u.complete
            self.complete_from.append(tail)
        self.complete_from.reverse()

    def threshold(self, key: str, default: float) -> float:
        v = self.cfg.get(key, default)
        return float(v) if isinstance(v, int | float) else default

    def bands(self) -> dict[str, dict[str, Any]]:
        """`strands.bands`, after reporting the bounds a unit map can't place: a unit outside the course, or a first
        key that isn't the course's first unit (the shares would leave the units before it unbounded)."""
        ctx = self.ctx
        bands = _map(_map(ctx.checker.get("strands")).get("bands"))
        checker = ctx.course.singles.get("checker")
        loc = Loc(checker.rel if checker else "content/checker.yaml", ("strands", "bands"))
        first = ctx.unit_ids[0] if ctx.unit_ids else None
        for strand in STRANDS:
            for side in ("min", "max"):
                value = _map(bands.get(strand)).get(side)
                if not isinstance(value, dict) or not value:
                    continue
                where = loc.child(strand, side)
                unknown = sorted(str(k) for k in value if k not in ctx.unit_index)
                if unknown:
                    ctx.add("error", 3, "strands", where, f"{', '.join(unknown)}: not a unit of course.yaml")
                known = sorted((k for k in value if k in ctx.unit_index), key=ctx.unit_index.__getitem__)
                if known and known[0] != first:
                    ctx.add(
                        "error",
                        3,
                        "strands",
                        where,
                        f"the {strand} {side} share starts at {known[0]}; start it at the course's first unit, {first}",
                    )
        return {strand: _map(bands.get(strand)) for strand in STRANDS}

    # ------------------------------------------------------------ items

    def encounters(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.ctx.strings:
            if not encounter_string(s):
                continue
            assert s.pos is not None
            for ref in refs_in(s):
                first = self.ctx.intros.first(ref)
                if first is not None and first.pos <= s.pos:
                    counts[ref] = counts.get(ref, 0) + 1
        return counts

    def retrievals(self, lesson: str) -> dict[str, int]:
        """Retrievals per item in one written lesson (docs/04 § Check 3)."""
        out: dict[str, int] = {}

        def add(ref: str) -> None:
            out[ref] = out.get(ref, 0) + 1

        doc = self.ctx.written_lessons()[lesson][1]
        for _, step in lesson_steps(doc):
            if step.get("kind") == "preview":
                for batch in _seq(step.get("batches")):
                    for iid in _seq(batch):
                        if isinstance(iid, str):
                            out[iid] = out.get(iid, 0) + 2
        strings: dict[str, list[Str]] = {}
        for s in self.ctx.strings:
            if s.lesson == lesson and s.exercise is not None:
                strings.setdefault(s.exercise.id, []).append(s)
        for x in exercises(self.ctx.course):
            if x.container != "lesson" or not x.id.startswith(lesson + ".") or x.format == "repeat":
                continue
            refs: set[str] = {str(_map(t).get("item")) for t in _seq(x.data.get("targets")) if _map(t).get("item")}
            for s in strings.get(x.id, []):
                if x.format in ("recall", "sentence-building", "conversation") and s.role in ("answer", "accept"):
                    if s.model:
                        refs.update(refs_in(s))
                elif x.format == "dictation" and s.role == "say":
                    refs.update(refs_in(s))
                elif x.format == "cloze" and s.role == "cloze" and s.model and s.gap:
                    refs.update(refs_in(s, only=s.gap))
                elif x.format == "match" and s.role == "pair":
                    refs.update(refs_in(s))
            for ref in refs:
                add(ref)
        return out

    def items(self) -> None:
        ctx = self.ctx
        enc = self.encounters()
        lessons = ctx.written_lessons()
        per_lesson: dict[str, dict[str, int]] = {}
        for iid, item in sorted(ctx.items.items()):
            if not iid.startswith(("w:", "c:")) or not ctx.intros.written(iid):
                continue
            lesson = item.get("lesson") if isinstance(item.get("lesson"), str) else None
            st = ItemStats(iid, ctx.item_unit[iid], "P" if is_p(item.get("status")) else "R", lesson)
            st.encounters = enc.get(iid, 0)
            ui = ctx.unit_index.get(st.unit, 0)
            st.judged = self.complete_from[ui] if ui < len(self.complete_from) else False
            if lesson in lessons:
                if lesson not in per_lesson:
                    per_lesson[lesson] = self.retrievals(lesson)
                st.retrievals = per_lesson[lesson].get(iid, 0)
            self.result.items.append(st)
            loc = ctx.item_loc.get(iid, Loc(""))
            if st.status == "P" and st.retrievals is not None:
                need = self.threshold("retrievals_in_lesson_p_min", 4)
                floor = self.threshold("retrievals_in_lesson_p_error_below", 2)
                if st.retrievals < need:
                    ctx.add(
                        "error" if st.retrievals < floor else "warning",
                        3,
                        "retrievals",
                        loc,
                        f"{iid} has {st.retrievals} retrieval(s) in {lesson} (preview 2, then exercises that target "
                        f"it, produce it or match it); a P item needs {need:g}",
                    )
            if st.judged:
                if st.status == "P":
                    need, floor = self.threshold("encounters_p_min", 10), self.threshold("encounters_p_error_below", 6)
                else:
                    need, floor = self.threshold("encounters_r_min", 6), 0
                if st.encounters < need:
                    ctx.add(
                        "error" if st.encounters < floor else "warning",
                        3,
                        "encounters",
                        loc,
                        f"{iid} ({st.status}) is met {st.encounters} time(s) from its introduction to course end; it "
                        f"needs {need:g}: reuse it in later stories, practice and checks",
                    )

    # ------------------------------------------------------------ units

    def text_words(self, strings: list[Str]) -> int:
        return sum(1 for s in strings for t in s.tokens if t.kind != "punct")

    def unit_stats(self) -> None:
        ctx = self.ctx
        dur = _map(ctx.checker.get("durations_seconds"))
        strands = _map(ctx.checker.get("strands"))
        by_kind = {str(k): str(v) for k, v in _map(strands.get("by_kind")).items()}
        texts: dict[str, list[Str]] = {}
        for s in ctx.strings:
            if s.text_ref is not None and s.role in ("line", "layout"):
                texts.setdefault(s.text_ref.id, []).append(s)

        def secs(key: str, default: float = 0.0) -> float:
            v = dur.get(key, default)
            return float(v) if isinstance(v, int | float) else default

        bands = self.bands()
        for ui, u in enumerate(ctx.course.units):
            st = UnitStats(u.id, u.complete)
            for strand in STRANDS:
                band = bands[strand]
                st.bands[strand] = (
                    bound_for(band.get("min"), u.id, ctx.unit_index, DEFAULT_BAND[0]),
                    bound_for(band.get("max"), u.id, ctx.unit_index, DEFAULT_BAND[1]),
                )

            def put(kind: str, seconds: float, st: UnitStats = st) -> None:
                strand = by_kind.get(kind)
                if strand in st.seconds:
                    st.seconds[strand] += seconds

            story_words = 0
            for doc in u.lessons:
                for _, step in lesson_steps(doc):
                    kind = str(step.get("kind", ""))
                    if kind == "preview":
                        n = sum(len(_seq(b)) for b in _seq(step.get("batches")))
                        put("preview", n * secs("preview_item"))
                    elif kind in ("story", "listening", "reading"):
                        tid = _map(step.get("text")).get("id")
                        words = self.text_words(texts.get(str(tid), []))
                        if kind == "story":
                            story_words += words
                        put(kind, words * secs("story_per_word"))
                        if kind in ("story", "listening"):  # heard as well as read; a listening text twice
                            plays = LISTENING_PLAYS if kind == "listening" else 1
                            put(kind, plays * words * secs("audio_per_word"))
                        n = len(_seq(step.get("questions")) or _seq(step.get("exercises")))
                        put("comprehension", n * secs("comprehension"))
                    elif kind == "note":
                        put("note", secs("note"))
                    elif kind in ("practice", "sounds"):
                        for key in ("block", "mix", "exercises"):
                            for ex in _seq(step.get(key)):
                                fmt = str(_map(ex).get("format", ""))
                                put(fmt, secs(fmt))
                    elif kind == "use":
                        ex = _map(step.get("exercise"))
                        fmt = str(ex.get("format", ""))
                        put("use", turns(ex) * secs("conversation_turn") if fmt == "conversation" else secs(fmt))
            if u.task:
                for x in walk_task(u.task, u.id):
                    if isinstance(x, ExerciseRef):
                        if x.format == "conversation":
                            put("conversation", turns(x.data) * secs("conversation_turn"))
                        else:
                            put(x.format, secs(x.format))
            rate = secs("fluency_rate", 1.0) or 1.0
            put("fluency", story_words * secs("story_per_word") / rate)
            # recycling: content words in the unit's lesson and task texts
            for s in ctx.strings:
                if s.text_ref is None or s.role not in ("line", "layout") or s.unit != u.id:
                    continue
                if s.container not in ("lesson", "task"):
                    continue
                for ref in refs_in(s):
                    item = ctx.items.get(ref, {})
                    if ref.startswith("w:") and str(item.get("pos")) not in CONTENT_POS:
                        continue
                    st.content_tokens += 1
                    if ctx.unit_index.get(ctx.item_unit.get(ref, ""), ui) < ui:
                        st.earlier_tokens += 1
            self.result.units.append(st)
            if not u.spec:
                continue
            if not u.complete:
                pending_line(ctx, 3, u, "recycling, strand balance and the grammar spiral are checked")
                continue
            spec_loc = u.spec.loc
            share_min = self.threshold("earlier_unit_content_share_min", 0.30)
            if ui > 0 and st.recycled is not None and st.recycled < share_min:
                ctx.add(
                    "warning",
                    3,
                    "recycling",
                    spec_loc,
                    f"{u.id}: {st.recycled:.0%} of the content words in its texts come from earlier units "
                    f"({st.earlier_tokens} of {st.content_tokens}); aim for at least {share_min:.0%}",
                )
            for strand in STRANDS:
                share = st.share(strand)
                lo, hi = st.bands[strand]
                if st.total and not lo <= share <= hi:
                    ctx.add(
                        "warning",
                        3,
                        "strands",
                        spec_loc,
                        f"{u.id}: {strand} is {share:.0%} of the estimated {st.total / 60:.0f} minutes "
                        f"({st.seconds[strand] / 60:.0f} min); its band in {u.id} is {lo:.0%}–{hi:.0%} "
                        "(checker.yaml strands.bands)",
                    )

    def stories(self) -> None:
        ctx = self.ctx
        for u in ctx.course.units:
            spec = _map(u.spec.data) if u.spec else {}
            words = str(_map(_map(spec.get("texts")).get("stories")).get("words", ""))
            m = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", words)
            low, high = (int(m.group(1)), int(m.group(2))) if m else (None, None)
            for doc in u.lessons:
                for s, step in lesson_steps(doc):
                    text = _map(step.get("text"))
                    if step.get("kind") != "story" or not isinstance(text.get("id"), str):
                        continue
                    strings = [x for x in ctx.strings if x.text_ref is not None and x.text_ref.id == text["id"]]
                    n = self.text_words([x for x in strings if x.role == "line"])
                    loc = doc.loc.child("steps", s, "text")
                    self.result.stories.append(StoryLength(text["id"], u.id, n, low, high, loc))
                    if low is not None and high is not None and doc.rel in ctx.checked_files and not low <= n <= high:
                        ctx.add(
                            "warning",
                            3,
                            "story-length",
                            loc,
                            f"{text['id']} has {n} words; {u.id}'s stories should have {low}–{high}",
                        )

    def spiral(self) -> None:
        ctx = self.ctx
        seen: dict[str, set[str]] = {}
        for s in ctx.strings:
            if s.pos is None or s.container in ("unit", "items"):
                continue
            for d in s.detections:
                seen.setdefault(d.point, set()).add(s.unit)
        for x in exercises(ctx.course):
            for t in _seq(x.data.get("targets")):
                item = _map(t).get("item")
                if isinstance(item, str) and item.startswith("g:"):
                    seen.setdefault(item, set()).add(x.unit_id)
        need = int(self.threshold("grammar_spiral_later_units_min", 2))
        order = ctx.unit_index
        teaching = [u for u in ctx.unit_ids if u != "u99"]
        last_two = set(teaching[-2:])
        for pid in sorted(ctx.points):
            unit = ctx.point_unit(pid)
            if unit not in order:
                continue
            later = sorted((u for u in seen.get(pid, set()) if order.get(u, -1) > order[unit]), key=order.get)
            self.result.spiral[pid] = later
            if not self.complete_from[min(order[unit] + 1, len(self.complete_from) - 1)]:
                continue
            ok = ("u99" in later) if unit in last_two else len(later) >= need
            if not ok:
                want = "in the final review" if unit in last_two else f"in at least {need} later units"
                ctx.add(
                    "warning",
                    3,
                    "spiral",
                    ctx.point_loc.get(pid, Loc("content/grammar/points.yaml")),
                    f"{pid} ({unit}) returns in {', '.join(later) or 'no later unit'}; it should come back {want}",
                    unit=unit,
                )

    def run(self) -> RecyclingResult:
        self.items()
        self.unit_stats()
        self.stories()
        self.spiral()
        return self.result


def turns(ex: dict[str, Any]) -> int:
    """Learner turns on the conversation's main path (each node's first intent, from `start` to a final node)."""
    nodes = _map(ex.get("nodes"))
    nid, n, seen = ex.get("start"), 0, set()
    while isinstance(nid, str) and nid in nodes and nid not in seen:
        seen.add(nid)
        expect = _seq(_map(nodes[nid]).get("expect"))
        if not expect:
            break
        n += 1
        nid = _map(expect[0]).get("next")
    return n


def check_recycling(ctx: CheckContext) -> RecyclingResult:
    return Recycling(ctx).run()
