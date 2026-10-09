"""`content annotate [--check]` (docs/04 § Commands, § Annotation; docs/03 § Annotation lock files).

Every Italian string of the course is tokenised, looked up in Morph-it!, matched against chunks, resolved to items and
scanned for grammar (`itcontent.resolve`). The result for `content/<path>.yaml` is written to
`content/.annotations/<path>.json`. `--check` regenerates every lock file in memory and fails, naming the files, when
one differs, is missing or is left over. Unknown and ambiguous tokens are errors that name the file, the line, the
YAML path, the string, the token and the candidates; nothing is written while there are errors.

Which strings are Italian (docs/06 per format; the rules this module settles are marked *):

- texts: `title.it`, every line's `it`, and every string of a real-world `layout` except `type`, `style`, `lemmas`
  and the values listed in `ignore`;
- unit specs, lessons and conversations: `title.it` (titles are exempt from the gates, never from annotation; a unit
  title whose unit has no items file yet is *pending*);
- exercises: `prompt_it`, `context_it`, cloze `text` (one string per gap expansion, the gap filled in), `say`,
  sentence-building `tiles`, `distractors` and `answer` orders, match left sides, conversation `say` and `help`,
  talk and writing `model`, writing `fields[].label_it`, and every expansion of `answer`, `accept` and `points[].accept`
  patterns; *`choice` options are Italian unless the exercise is in a story, listening or reading step or carries
  its own Italian stimulus (`prompt_it`, `audio_text`, `source`): then they are English;
- *sound pairs: `pair` and `word` are annotated as sound words: resolved like any word, flagged `sound`, glossed from
  `glosses`, and allowed to have no item when `glosses` explains them (`play` repeats a `pair` word);
- *notes: the `*…*` fragments of `p`, `tip` and `intro.text_en` (fragments that are endings such as `*-o*` are
  skipped), `table.rows` cells (`columns` are English headers), and `examples` that are inline strings rather than
  line IDs;
- items: `recall_answer` patterns;
- *near-miss `answer` patterns (exercise and conversation-node `near`) are annotated like an accepted pattern's other
  expansions, never as a model answer: they are often deliberately wrong (`una cornetto`), so an unknown token is
  fine there (a warning only without any Morph-it! analysis) and nothing about them is gated.

Disambiguation overrides (`lemmas: {form: item-id}`, docs/03): a text line's apply to that line, and a key it lacks is
an error; an exercise's apply to every Italian string of the exercise above (not its inline texts, whose lines have
their own) and a layout's to every string of the layout, and a key none of those strings contains is an error.

Model answers (first expansion of `answer`, a cloze gap, the first `accept` pattern of each intent; `help`; `model`;
the first sentence-building order) and every other string are strict; an accepted pattern's other expansions are
lenient: an unknown token keeps its Morph-it! lemma with no item (a warning only if it has no analysis either).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itcontent import paths, yamlio
from itcontent.course import (
    Course,
    Doc,
    ExerciseRef,
    NoteRef,
    PathT,
    TextRef,
    load_course,
    walk_check,
    walk_lesson,
    walk_notes,
    walk_task,
)
from itcontent.detection import DetectionRuleError
from itcontent.morphit import MorphIt
from itcontent.morphit import load as load_morphit
from itcontent.patterns import Expansion, PatternError, expand
from itcontent.resolve import Annotated, Ctx, Issue, Lexicon, Position, TokAnn, lesson_k
from itcontent.tokenize import fold

FORMAT = 1
LOCK_DIR = "content/.annotations"
TEXT_STEP_KINDS = frozenset({"story", "listening", "reading"})
LAYOUT_NON_TEXT = frozenset({"type", "style", "ignore", "lemmas"})
FRAGMENT = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
LINE_REF = re.compile(r"^u\d{2}\.(?:l\d+|task)\.[a-z0-9-]+#\d+$")


# ---------------------------------------------------------------- what gets annotated


@dataclass
class Source:
    """One Italian string to annotate, with where it sits and how strictly."""

    path: PathT
    role: str
    text: str
    ctx: Ctx
    ref: str | None = None
    pattern: str | None = None
    expansion: Expansion | None = None
    index: int | None = None  # expansion index
    of: int | None = None  # number of expansions
    model: bool | None = None
    gap: tuple[int, int] | None = None  # character span of the filled-in gap (cloze)
    fragment: tuple[int, int] | None = None  # character span of a note fragment in its YAML string
    lemmas_at: PathT | None = None  # the exercise's or layout's `lemmas:` this string shares (its YAML path)


@dataclass(frozen=True)
class Problem:
    """A pattern that does not parse, found while collecting strings."""

    path: PathT
    message: str


def fmt_path(path: PathT) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (("." if out else "") + str(p))
    return out


def _sort_key(path: PathT) -> tuple[tuple[int, Any], ...]:
    return tuple((0, p) if isinstance(p, int) else (1, p) for p in path)


class Collector:
    """Turns the YAML of one file into `Source`s."""

    def __init__(self, unit: int) -> None:
        self.unit = unit
        self.sources: list[Source] = []
        self.problems: list[Problem] = []
        # an exercise's or a layout's `lemmas:` (and its YAML path) while its strings are collected
        self.shared: tuple[dict[str, Any], PathT] | None = None
        self.shared_maps: dict[PathT, dict[str, Any]] = {}  # every such map of the file, by its YAML path

    def ctx(self, pos: Position, **kw: Any) -> Ctx:
        if self.shared is not None:
            kw = {"lemmas": self.shared[0], "shared_lemmas": True, **kw}
        return Ctx(unit=self.unit, pos=pos, **kw)

    def add(self, src: Source) -> None:
        if self.shared is not None:
            src.lemmas_at = self.shared[1]
        self.sources.append(src)

    def share(self, lemmas: Any, path: PathT) -> None:
        """Strings collected from now on share this `lemmas:` map (an exercise's or a layout's), until `unshare`."""
        self.shared = ({str(k): v for k, v in lemmas.items()}, path) if isinstance(lemmas, dict) and lemmas else None
        if self.shared is not None:
            self.shared_maps[path] = self.shared[0]

    def unshare(self) -> None:
        self.shared = None

    def plain(self, path: PathT, role: str, value: Any, pos: Position, ref: str | None = None, **kw: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float):
            value = str(value)
        if not isinstance(value, str) or not value.strip():
            return
        self.add(Source(path, role, value, self.ctx(pos, **kw), ref=ref))

    def pattern(
        self, path: PathT, role: str, pattern: Any, pos: Position, ref: str | None, *, model_first: bool
    ) -> None:
        if not isinstance(pattern, str):
            return
        try:
            exps = expand(pattern)
        except PatternError as exc:
            self.problems.append(Problem(path, f"pattern {pattern!r}: {exc}"))
            return
        for k, e in enumerate(exps):
            if not e.raw:
                continue  # an all-optional pattern's empty expansion
            model = model_first and k == 0
            self.add(
                Source(
                    path,
                    role,
                    e.raw,
                    self.ctx(pos, strict=model, protected=e.raw_slots),
                    ref=ref,
                    pattern=pattern,
                    expansion=e,
                    index=k,
                    of=len(exps),
                    model=model,
                )
            )

    def cloze(self, path: PathT, text: Any, pos: Position, ref: str | None) -> None:
        if not isinstance(text, str):
            return
        gaps = list(re.finditer(r"\[\[(.*?)\]\]", text))
        if not gaps:
            self.problems.append(Problem(path, "cloze text has no [[gap]]"))
            return
        expanded: list[list[Expansion]] = []
        for g in gaps:
            try:
                expanded.append(expand(g.group(1)))
            except PatternError as exc:
                self.problems.append(Problem(path, f"gap {g.group(1)!r}: {exc}"))
                return
        combos: list[tuple[int, int]] = [(-1, 0)]  # (gap varied, its expansion); -1 = all model answers
        combos += [(gi, k) for gi, exps in enumerate(expanded) for k in range(1, len(exps))]
        for gi, k in combos:
            out = ""
            last = 0
            gap_span = (0, 0)
            slots: list[tuple[int, int, str]] = []
            for j, g in enumerate(gaps):
                e = expanded[j][k if j == gi else 0]
                out += text[last : g.start()]
                start = len(out)
                slots += [(start + a, start + b, n) for a, b, n in e.raw_slots]
                out += e.raw
                if j == max(gi, 0):
                    gap_span = (start, len(out))
                last = g.end()
            out += text[last:]
            vary = max(gi, 0)
            self.add(
                Source(
                    path,
                    "cloze",
                    out,
                    self.ctx(pos, strict=gi < 0, protected=slots),
                    ref=ref,
                    pattern=gaps[vary].group(1),
                    expansion=expanded[vary][k if gi >= 0 else 0],
                    index=k if gi >= 0 else 0,
                    of=len(expanded[vary]),
                    model=gi < 0,
                    gap=gap_span,
                )
            )

    def fragments(self, path: PathT, value: Any, pos: Position, ref: str | None) -> None:
        if not isinstance(value, str):
            return
        for m in FRAGMENT.finditer(value):
            body = m.group(1) if m.group(1) is not None else m.group(2)
            start = m.start(1) if m.group(1) is not None else m.start(2)
            if not body.strip() or re.fullmatch(r"-\w+", body.strip()):
                continue  # an ending such as *-o*, not a word
            src = Source(path, "note", body, self.ctx(pos, markup="*"), ref=ref, fragment=(start, start + len(body)))
            self.add(src)

    # ------------------------------------------------------------ texts

    def text(self, t: Mapping[str, Any], base: PathT, pos: Position) -> None:
        tid = str(t.get("id", "")) or None
        title = t.get("title")
        if isinstance(title, dict):
            self.plain((*base, "title", "it"), "title", title.get("it"), pos, ref=tid)
        for i, line in enumerate(t.get("lines") or []):
            if not isinstance(line, dict):
                continue
            self.plain(
                (*base, "lines", i, "it"),
                "line",
                line.get("it"),
                pos,
                ref=f"{tid}#{i + 1}" if tid else None,
                foreign=[str(x) for x in line.get("foreign") or []],
                gloss={str(k): str(v) for k, v in (line.get("gloss") or {}).items()},
                lemmas=dict(line.get("lemmas") or {}),
                recognise=[str(x) for x in line.get("recognise") or []],
            )
        layout = t.get("layout")
        if isinstance(layout, dict):
            ignore = {str(x) for x in layout.get("ignore") or []}
            self.share(layout.get("lemmas"), (*base, "layout", "lemmas"))
            try:
                self._layout(layout, (*base, "layout"), pos, tid, ignore)
            finally:
                self.unshare()

    def _layout(self, node: Any, path: PathT, pos: Position, ref: str | None, ignore: set[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in LAYOUT_NON_TEXT:
                    self._layout(v, (*path, k), pos, ref, ignore)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._layout(v, (*path, i), pos, ref, ignore)
        elif node is not None and not isinstance(node, bool) and str(node) not in ignore:
            self.plain(path, "layout", node, pos, ref=ref)

    # ------------------------------------------------------------ exercises

    def exercise(self, ref: ExerciseRef, base: PathT, pos: Position) -> None:
        """The exercise's own Italian strings (its inline texts are walked as texts), sharing its `lemmas:`."""
        self.share(ref.data.get("lemmas"), (*base, "lemmas"))
        try:
            self._exercise_strings(ref, base, pos)
        finally:
            self.unshare()

    def _exercise_strings(self, ref: ExerciseRef, base: PathT, pos: Position) -> None:
        ex = ref.data
        eid = ref.id or None
        fmt = ref.format
        title = ex.get("title")
        if isinstance(title, dict):
            self.plain((*base, "title", "it"), "title", title.get("it"), pos, ref=eid)
        self.plain((*base, "prompt_it"), "prompt", ex.get("prompt_it"), pos, ref=eid)
        self.plain((*base, "context_it"), "context", ex.get("context_it"), pos, ref=eid)
        for j, near in enumerate(ex.get("near") or []):
            if isinstance(near, dict):
                self.pattern((*base, "near", j, "answer"), "near", near.get("answer"), pos, eid, model_first=False)
        if fmt == "cloze":
            self.cloze((*base, "text"), ex.get("text"), pos, eid)
        elif fmt == "recall":
            self.pattern((*base, "answer"), "answer", ex.get("answer"), pos, eid, model_first=True)
        elif fmt == "sentence-building":
            for key in ("tiles", "distractors"):
                for j, tile in enumerate(ex.get(key) or []):
                    self.plain((*base, key, j), "tile", tile, pos, ref=eid)
            for j, order in enumerate(ex.get("answer") or []):
                if isinstance(order, str):
                    self.add(Source((*base, "answer", j), "answer", order, self.ctx(pos), ref=eid, model=j == 0))
        elif fmt in ("dictation", "repeat"):
            self.plain((*base, "say"), "say", ex.get("say"), pos, ref=eid)
        elif fmt == "choice":
            if italian_options(ex, ref.step_kind):
                for j, opt in enumerate(ex.get("options") or []):
                    self.plain((*base, "options", j), "option", opt, pos, ref=eid)
        elif fmt == "match":
            for j, pair in enumerate(ex.get("pairs") or []):
                if isinstance(pair, list) and pair:
                    self.plain((*base, "pairs", j, 0), "pair", pair[0], pos, ref=eid)
        elif fmt == "sound-pair":
            glosses = {str(k): str(v) for k, v in (ex.get("glosses") or {}).items()}
            for j, word in enumerate(ex.get("pair") or []):
                self.plain((*base, "pair", j), "sound", word, pos, ref=eid, sound=True, sound_glosses=glosses)
            self.plain((*base, "word"), "sound", ex.get("word"), pos, ref=eid, sound=True, sound_glosses=glosses)
        elif fmt == "conversation":
            for nid, node in sorted((ex.get("nodes") or {}).items()):
                if not isinstance(node, dict):
                    continue
                npath = (*base, "nodes", nid)
                nref = f"{eid}/{nid}" if eid else None
                self.plain((*npath, "say"), "say", node.get("say"), pos, ref=nref)
                for j, h in enumerate(node.get("help") or []):
                    self.plain((*npath, "help", j), "help", h, pos, ref=nref)
                for j, intent in enumerate(node.get("expect") or []):
                    if not isinstance(intent, dict):
                        continue
                    for a, pat in enumerate(intent.get("accept") or []):
                        self.pattern((*npath, "expect", j, "accept", a), "accept", pat, pos, nref, model_first=a == 0)
                for j, near in enumerate(node.get("near") or []):
                    if isinstance(near, dict):
                        self.pattern(
                            (*npath, "near", j, "answer"), "near", near.get("answer"), pos, nref, model_first=False
                        )
        if fmt in ("talk", "writing"):
            self.plain((*base, "model"), "model", ex.get("model"), pos, ref=eid)
            for j, point in enumerate(ex.get("points") or []):
                if isinstance(point, dict):
                    for a, pat in enumerate(point.get("accept") or []):
                        self.pattern((*base, "points", j, "accept", a), "point", pat, pos, eid, model_first=False)
            for j, fld in enumerate(ex.get("fields") or []):
                if isinstance(fld, dict):
                    self.plain((*base, "fields", j, "label_it"), "label", fld.get("label_it"), pos, ref=eid)
                    for a, pat in enumerate(fld.get("accept") or []):
                        self.pattern((*base, "fields", j, "accept", a), "field", pat, pos, eid, model_first=False)

    # ------------------------------------------------------------ notes

    def note(self, ref: NoteRef, base: PathT, pos: Position) -> None:
        note = ref.data
        nid = ref.id or None
        intro = note.get("intro")
        if isinstance(intro, dict):
            self.fragments((*base, "intro", "text_en"), intro.get("text_en"), pos, nid)
        for b, block in enumerate(note.get("body") or []):
            if not isinstance(block, dict):
                continue
            bpath = (*base, "body", b)
            for key in ("p", "tip"):
                self.fragments((*bpath, key), block.get(key), pos, nid)
            table = block.get("table")
            if isinstance(table, dict):
                for r, row in enumerate(table.get("rows") or []):
                    for c, cell in enumerate(row or []):
                        self.plain((*bpath, "table", "rows", r, c), "cell", cell, pos, ref=nid, markup="*")
            for e, ex in enumerate(block.get("examples") or []):
                if isinstance(ex, str) and not LINE_REF.match(ex):
                    self.plain((*bpath, "examples", e), "example", ex, pos, ref=nid, markup="*")


def italian_options(ex: Mapping[str, Any], step_kind: str | None) -> bool:
    """`choice` options are Italian unless the Italian is the stimulus: a story, listening or reading step, or the
    exercise's own `prompt_it`, `audio_text` or `source` (then the options give its meaning in English)."""
    if step_kind in TEXT_STEP_KINDS:
        return False
    return not any(ex.get(k) for k in ("prompt_it", "audio_text", "source"))


# ---------------------------------------------------------------- per file


def _pos_of(path: PathT, unit: int, container_rank: int) -> Position:
    if len(path) >= 2 and path[0] == "steps" and isinstance(path[1], int):
        return (unit, container_rank, path[1])
    return (unit, container_rank, 0)


def collect(course: Course, doc: Doc, kind: str, unit_id: str) -> Collector:
    order = course.unit_order()
    u = order.get(unit_id, 0)
    col = Collector(u)
    data = doc.data if isinstance(doc.data, dict) else {}

    if kind == "unit":
        title = data.get("title")
        uf = course.unit(unit_id)
        pending = uf is not None and uf.items is None
        if isinstance(title, dict):
            col.plain(("title", "it"), "title", title.get("it"), (u, -1, -1), ref=unit_id, pending=pending)
    elif kind == "items":
        for i, item in enumerate(data.get("items") or []):
            if isinstance(item, dict) and item.get("recall_answer") is not None:
                col.pattern(
                    ("items", i, "recall_answer"),
                    "recall_answer",
                    item.get("recall_answer"),
                    (u, -1, -1),
                    str(item.get("id")),
                    model_first=True,
                )
    elif kind in ("lesson", "task", "check", "placement", "final"):
        rank = {"lesson": lesson_k(str(data.get("id", ""))), "task": 900, "check": 950}.get(kind, 0)
        title = data.get("title")
        if isinstance(title, dict):
            col.plain(("title", "it"), "title", title.get("it"), (u, rank, -1), ref=str(data.get("id", "")))
        walker: Iterator[ExerciseRef | TextRef]
        if kind == "lesson":
            walker = walk_lesson(doc, unit_id)
        elif kind == "task":
            walker = walk_task(doc, unit_id)
        else:
            walker = walk_check(doc, unit_id, kind)
        for ref in walker:
            # a placement block's exercises sit at the unit the block tests
            col.unit = order.get(str(ref.section), u) if kind == "placement" else u
            pos = _pos_of(ref.loc.path, col.unit, rank)
            if isinstance(ref, TextRef):
                col.text(ref.data, ref.loc.path, pos)
            else:
                col.exercise(ref, ref.loc.path, pos)
        col.unit = u
        if kind == "lesson":
            for note in walk_notes(doc, unit_id):
                col.note(note, note.loc.path, _pos_of(note.loc.path, u, rank))
    col.sources.sort(key=lambda s: (_sort_key(s.path), s.fragment or (0, 0), s.index or 0))
    return col


def files_to_annotate(course: Course) -> list[tuple[Doc, str, str]]:
    """(doc, kind, unit id) for every file that can hold Italian, in course order."""
    out: list[tuple[Doc, str, str]] = []
    for u in course.units:
        if u.spec:
            out.append((u.spec, "unit", u.id))
        for d in u.lessons:
            out.append((d, "lesson", u.id))
        if u.task:
            out.append((u.task, "task", u.id))
        if u.check:
            out.append((u.check, "check", u.id))
        if u.items:
            out.append((u.items, "items", u.id))
    if "placement" in course.assessments:
        out.append((course.assessments["placement"], "placement", "u00"))
    if "final" in course.assessments:
        out.append((course.assessments["final"], "final", "u99"))
    return out


def lock_path(rel: str) -> str:
    """`content/units/02-al-bar/lesson-1.yaml` → `content/.annotations/units/02-al-bar/lesson-1.json`."""
    inner = rel.removeprefix("content/")
    return f"{LOCK_DIR}/{inner.rsplit('.', 1)[0]}.json"


# ---------------------------------------------------------------- lock-file encoding


def token_json(t: TokAnn) -> dict[str, Any]:
    out: dict[str, Any] = {"surface": t.surface, "span": [t.tok.start, t.tok.end], "kind": t.kind}
    if t.tok.trailing:
        out["trailing"] = t.tok.trailing
    if t.tok.slot:
        out["slot"] = t.tok.slot
    if t.analyses:
        out["analyses"] = [str(a) for a in t.analyses]
        if t.lemma is not None:
            out["lemma"] = t.lemma
    if t.item:
        out["item"] = t.item
    if t.chunk:
        out["chunk"] = t.chunk
    if t.head is not None:
        out["head"] = t.head
    if t.gloss is not None:
        out["gloss"] = t.gloss
    if t.detections:
        out["detections"] = sorted(t.detections)
    if t.candidates:
        out["candidates"] = list(t.candidates)
    if t.flags:
        out["flags"] = sorted(t.flags)
    return out


def string_json(src: Source, ann: Annotated) -> dict[str, Any]:
    out: dict[str, Any] = {"path": fmt_path(src.path), "role": src.role, "text": src.text}
    if src.ref:
        out["ref"] = src.ref
    if ann.lead:
        out["lead"] = ann.lead
    if src.fragment:
        out["fragment"] = list(src.fragment)
    if src.pattern is not None:
        out["pattern"] = src.pattern
    if src.expansion is not None:
        e = src.expansion
        out["expansion"] = src.index
        out["of"] = src.of
        out["norm"] = e.text
        if e.focus:
            out["focus"] = list(e.focus)
        if e.gender:
            out["gender"] = e.gender
        if e.slots:
            out["slots"] = [[i, n] for i, n in e.slots]
    if src.model is not None:
        out["model"] = src.model
    if src.gap is not None:
        idx = [k for k, t in enumerate(ann.tokens) if t.tok.start < src.gap[1] and t.tok.end > src.gap[0]]
        out["gap"] = [idx[0], idx[-1]] if idx else []
    if src.ctx.pending:
        out["pending"] = True
    out["tokens"] = [token_json(t) for t in ann.tokens]
    if ann.detections:
        out["detections"] = [{"point": d.point, "tokens": [d.start, d.end]} for d in ann.detections]
    return out


def dumps(obj: Any, depth: int = 0, compact_at: int = 4) -> str:
    """Deterministic JSON: sorted keys, objects nested deeper than `compact_at` on one line (one token per line)."""
    if depth >= compact_at or not isinstance(obj, dict | list) or not obj:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
    pad = " " * (depth + 1)
    end = " " * depth
    if isinstance(obj, dict):
        body = ",\n".join(f"{pad}{json.dumps(k, ensure_ascii=False)}: {dumps(obj[k], depth + 1)}" for k in sorted(obj))
        return "{\n" + body + "\n" + end + "}"
    if all(not isinstance(x, dict | list) for x in obj):
        return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
    body = ",\n".join(pad + dumps(x, depth + 1) for x in obj)
    return "[\n" + body + "\n" + end + "]"


# ---------------------------------------------------------------- running


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning | pending
    file: str
    line: int | None
    path: str
    text: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        where += f" › {self.path}" if self.path else ""
        quoted = f" ({self.text!r})" if self.text else ""
        return f"{self.level}: {where}{quoted}: {self.message}"


@dataclass
class Result:
    locks: dict[str, str]  # repo-relative lock path → content
    findings: list[Finding]
    strings: int = 0
    tokens: int = 0
    word_tokens: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


def _issue_message(ann: Annotated, issue: Issue) -> str:
    if issue.token is None:
        return issue.message
    return f"token {issue.token} '{ann.tokens[issue.token].surface}': {issue.message}"


def annotate_course(course: Course, morph: MorphIt) -> Result:
    locks: dict[str, str] = {}
    findings: list[Finding] = []
    try:
        lex = Lexicon.from_course(course, morph)
    except DetectionRuleError as exc:
        return Result({}, [Finding("error", "content/grammar/detection.yaml", None, "", "", str(exc))])
    n_strings = n_tokens = n_words = 0
    rt_cache: dict[str, Any] = {}

    def line_of(doc: Doc, path: PathT) -> int | None:
        if doc.rel not in rt_cache:
            try:
                rt_cache[doc.rel] = yamlio.load_roundtrip(doc.path)
            except Exception:  # pragma: no cover - the safe load already succeeded
                rt_cache[doc.rel] = None
        rt = rt_cache[doc.rel]
        return yamlio.locate(rt, list(path)) if rt is not None else None

    for rel, msg in course.load_errors:
        findings.append(Finding("error", rel, None, "", "", msg))
    for doc, kind, unit_id in files_to_annotate(course):
        col = collect(course, doc, kind, unit_id)
        for p in col.problems:
            findings.append(Finding("error", doc.rel, line_of(doc, p.path), fmt_path(p.path), "", p.message))
        entries = []
        used: dict[PathT, set[str]] = {p: set() for p in col.shared_maps}
        for src in col.sources:
            ann = lex.annotate(src.text, src.ctx)
            if src.lemmas_at is not None:
                used[src.lemmas_at] |= ann.used_lemmas
            n_strings += 1
            n_tokens += len(ann.tokens)
            n_words += sum(1 for t in ann.tokens if t.kind != "punct")
            for issue in ann.issues:
                findings.append(
                    Finding(
                        issue.level,
                        doc.rel,
                        line_of(doc, src.path),
                        fmt_path(src.path),
                        src.text,
                        _issue_message(ann, issue),
                    )
                )
            entries.append(string_json(src, ann))
        for path, keys in sorted(col.shared_maps.items(), key=lambda kv: _sort_key(kv[0])):
            owner = "layout" if path[-2:-1] == ("layout",) else "exercise"
            for key in sorted(k for k in keys if fold(k) not in used[path]):
                findings.append(
                    Finding(
                        "error",
                        doc.rel,
                        line_of(doc, path),
                        fmt_path(path),
                        "",
                        f"lemmas key '{key}' is in none of the {owner}'s Italian strings",
                    )
                )
        if not entries:
            continue
        lock = {"format": FORMAT, "source": doc.rel, "unit": unit_id, "strings": entries}
        locks[lock_path(doc.rel)] = dumps(lock) + "\n"
    return Result(locks, findings, n_strings, n_tokens, n_words)


def existing_locks(root: Path) -> dict[str, Path]:
    base = root / LOCK_DIR
    if not base.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): p for p in sorted(base.rglob("*.json"))}


def run_annotate(root: Path | None = None, *, check: bool = False, echo: Callable[[str], None] = print) -> int:
    root = (root or paths.ROOT).resolve()
    mpath = root / "pipeline" / "data" / "morph-it" / "morph-it.txt"
    if not mpath.is_file():
        echo(f"error: {mpath.relative_to(root)} is missing: run `make data`")
        return 2
    course = load_course(root)
    result = annotate_course(course, load_morphit(mpath.resolve()))
    order = {"error": 0, "warning": 1, "pending": 2}
    for f in sorted(result.findings, key=lambda f: (order.get(f.level, 3), f.file, f.line or 0, f.path, f.message)):
        echo(str(f))
    errors = len(result.errors)
    warnings = sum(1 for f in result.findings if f.level == "warning")
    pending = sum(1 for f in result.findings if f.level == "pending")
    summary = (
        f"annotate: {len(result.locks)} file(s), {result.strings} string(s), {result.tokens} token(s) "
        f"({result.word_tokens} non-punctuation); {errors} error(s), {warnings} warning(s), {pending} pending"
    )
    have = existing_locks(root)
    if check:
        stale = sorted(
            {p for p, text in result.locks.items() if p not in have or have[p].read_text(encoding="utf-8") != text}
            | (set(have) - set(result.locks))
        )
        for p in stale:
            why = "missing" if p not in have else ("left over" if p not in result.locks else "stale")
            echo(f"error: {p} is {why}: run `make annotate`")
        echo(summary + (f"; {len(stale)} stale lock file(s)" if stale else "; lock files up to date"))
        return 1 if errors or stale else 0
    if errors:
        echo(summary + "; nothing written")
        return 1
    written = 0
    for p, text in result.locks.items():
        target = root / p
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written += 1
    removed = 0
    for p, path in have.items():
        if p not in result.locks:
            path.unlink()
            removed += 1
    echo(summary + f"; {written} lock file(s) written, {removed} removed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_annotate())
