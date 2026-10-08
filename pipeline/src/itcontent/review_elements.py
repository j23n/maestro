"""What a review page shows (docs/04 § Content review loop › Review pages): every reviewable element of a scope.

An element is one thing the teacher can give a verdict on: a story line, an exercise, a conversation node, a note,
an item, a can-do, a register row… Each has a `target` (the ID or spec path a comment names), the `file` it lives
in, a `quote` (the text a comment quotes), a fingerprint of its data (`--since` compares it to mark changes) and an
HTML body that shows everything a learner would meet, plus what a learner never sees at once: every accepted answer
(expanded and grouped), the near-misses with their hints, conversation trees, glosses and notes. Fields without a
dedicated rendering are listed generically, so the page never hides what a file says.

Accepted answers are expanded with the grader's own expander (`itcontent.patterns.expand`, docs/03 § The
answer-pattern language) and shown as written (`Expansion.raw`: case and punctuation kept), focus parts marked; a
pattern that doesn't parse shows its `PatternError` instead. Personal slots stay placeholders (`{NAME}`).

Audio waits for M5.1: `Context.audio` maps a target to an audio URL (a `data:` URI keeps the page self-contained),
and the page then shows a player. It returns None until `content tts` exists.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from itcontent import ids, patterns
from itcontent.course import Course, Doc, UnitFiles, lesson_steps
from itcontent.course import texts as all_texts
from itcontent.index import Index, build_index
from itcontent.review import DECISIONS, fingerprint, questions, scope_files, scope_title, version_hash

Expander = Callable[[str], Any]


# ---------------------------------------------------------------- the model


@dataclass
class Element:
    key: str  # unique on the page: the target, or adj:<target>:<answer> for an answer to adjudicate
    target: str
    file: str
    kind: str
    label: str
    body: str  # HTML
    quote: str | None
    fp: str | None
    counted: bool = True  # counts toward "reviewed / total" (step and file headers don't)
    depth: int = 0
    meta: dict[str, Any] = field(default_factory=dict)  # extra data for the page script


@dataclass
class Heading:
    text: str
    level: int = 3


@dataclass
class Section:
    file: str
    title: str
    status: str | None
    entries: list[Element | Heading]
    group: str  # the table of contents groups sections by this

    @property
    def elements(self) -> list[Element]:
        return [e for e in self.entries if isinstance(e, Element)]


@dataclass
class PageModel:
    scope: str
    title: str
    sections: list[Section]
    files: dict[str, str]  # path → version hash of what the page shows

    def elements(self) -> list[Element]:
        return [e for s in self.sections for e in s.elements]


# ---------------------------------------------------------------- answer patterns


def expansion_html(x: Any) -> str:
    """One expansion as written, focus parts (graded strictly) marked."""
    if isinstance(x, str):
        return esc(x)
    raw = str(getattr(x, "raw", getattr(x, "text", x)))
    out, pos = [], 0
    for start, end in sorted(getattr(x, "raw_focus", ()) or ()):
        out.append(esc(raw[pos:start]) + f'<b class="focus">{esc(raw[start:end])}</b>')
        pos = end
    return "".join(out) + esc(raw[pos:])


def expansion_text(x: Any) -> str:
    return x if isinstance(x, str) else str(getattr(x, "raw", getattr(x, "text", x)))


# ---------------------------------------------------------------- HTML helpers


def esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def it(text: Any, cls: str = "it") -> str:
    """Italian text (font, and `lang` for screen readers)."""
    return f'<span lang="it" class="{cls}">{esc(text)}</span>'


def en(text: Any) -> str:
    return f'<span class="en">{esc(text)}</span>'


def tag(text: Any, cls: str = "tag") -> str:
    return f'<span class="{cls}">{esc(text)}</span>'


def row(name: str, value_html: str, cls: str = "field") -> str:
    """A labelled line: `<p class="field"><span class="tag">Hint</span> …</p>`."""
    return f'<p class="{cls}">{tag(name)} {value_html}</p>'


def _cls(condition: bool, name: str) -> str:
    return f' class="{name}"' if condition else ""


_MD = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`")


def md(text: Any) -> str:
    """Inline markup of notes and docs: `*…*` Italian (italic), `**…**` the highlighted form, `` `…` `` code."""
    s = str(text)
    out, pos = [], 0
    for m in _MD.finditer(s):
        out.append(esc(s[pos : m.start()]))
        if m.group(1) is not None:
            out.append(f'<strong class="hl">{md(m.group(1))}</strong>')
        elif m.group(2) is not None:
            out.append(f'<em lang="it">{esc(m.group(2))}</em>')
        else:
            out.append(f"<code>{esc(m.group(3))}</code>")
        pos = m.end()
    out.append(esc(s[pos:]))
    return "".join(out)


NONE = '<span class="none">none</span>'

LABELS = {
    "prompt_en": "Prompt",
    "prompt_it": "Italian shown",
    "question_en": "Question",
    "statement_en": "Statement",
    "context_it": "Context",
    "friend_en": "Friend asks",
    "answer_en": "Answer (English)",
    "hint": "Hint",
    "hint_en": "Hint",
    "rule": "Rule",
    "tip_en": "Tip",
    "audio_after": "Plays the model answer after",
    "title_en": "Title",
    "en": "English",
    "it": "Italian",
    "pos": "Part of speech",
    "alt_glosses": "Also accepted in English",
    "false_friend": "False friend",
    "recall_answer": "Recall answer",
    "audio_say": "TTS says",
    "case_sensitive": "Case-sensitive",
    "new_token_max": "New-token maximum",
    "est_hours": "Estimated hours",
    "recycle_from": "Recycles",
    "duration_s": "Duration (s)",
    "home_phrase": "abito …",
    "alt_home_phrases": "Also accepted",
    "first_unit": "First unit",
    "switch_at": "Switches at",
}


def label(key: Any) -> str:
    k = str(key)
    return LABELS.get(k, k.replace("_", " ").capitalize())


def value_html(v: Any) -> str:
    """Any YAML value, readably."""
    if v is None:
        return NONE
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return esc(v)
    if isinstance(v, str):
        return md(v)
    if isinstance(v, list):
        if not v:
            return NONE
        if all(isinstance(x, (str, int, float, bool)) for x in v):
            return ", ".join(value_html(x) for x in v)
        return '<ul class="vl">' + "".join(f"<li>{value_html(x)}</li>" for x in v) + "</ul>"
    if isinstance(v, dict):
        return dl([(label(k), value_html(x)) for k, x in v.items()])
    return esc(v)


def dl(rows: list[tuple[str, str]], cls: str = "kv") -> str:
    if not rows:
        return ""
    return f'<dl class="{cls}">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def rest(data: dict[str, Any], shown: set[str]) -> str:
    """Every field not rendered yet, so the page always shows everything the file says."""
    return dl([(label(k), value_html(v)) for k, v in data.items() if k not in shown | {"id", "review"}], "kv rest")


def chips(values: list[Any], cls: str = "chip") -> str:
    return " ".join(tag(v, cls) for v in values)


def _short(text: Any, limit: int = 300) -> str | None:
    if text is None:
        return None
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def anchor(key: str) -> str:
    """A readable, unique HTML id for an element key."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-")
    return f"e-{slug}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:6]}"


# ---------------------------------------------------------------- context


@dataclass
class Context:
    course: Course
    index: Index
    expander: Expander = patterns.expand
    audio: Callable[[str], str | None] = lambda _target: None
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    points: dict[str, dict[str, Any]] = field(default_factory=dict)
    syllabus: dict[str, dict[str, Any]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    texts: dict[str, dict[str, Any]] = field(default_factory=dict)
    can_dos: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def build(
        cls, course: Course, *, expander: Expander | None = None, audio: Callable[[str], str | None] | None = None
    ) -> Context:
        ctx = cls(course, build_index(course), expander or patterns.expand)
        if audio is not None:
            ctx.audio = audio
        ctx.items = course.item_map()
        ctx.points = {str(p["id"]): p for p in course.grammar_points() if p.get("id")}
        syl = course.singles.get("syllabus")
        for e in _seq(_map(syl.data if syl else None).get("items")):
            if isinstance(e, dict) and e.get("id"):
                ctx.syllabus[str(e["id"])] = e
        bible = course.singles.get("story_bible")
        for ch in _seq(_map(bible.data if bible else None).get("characters")):
            if isinstance(ch, dict) and ch.get("id"):
                ctx.names[str(ch["id"])] = str(ch.get("name") or ch["id"])
        ctx.names.update({"narrator": "Narrator", "announcer": "Announcer"})
        for t in all_texts(course):
            ctx.texts.setdefault(t.id, t.data)
        for u in course.units:
            for cd in _seq(_map(u.spec.data if u.spec else None).get("can_do")):
                if isinstance(cd, dict) and cd.get("id"):
                    ctx.can_dos[str(cd["id"])] = cd
        return ctx

    # ------------------------------------------------------------ lookups for display

    def name(self, speaker: Any) -> str:
        return self.names.get(str(speaker), str(speaker))

    def ref_title(self, ref: Any) -> str:
        """A reference with what it names: `w:cornetto (cornetto: croissant)`."""
        r = str(ref)
        if r in self.items:
            return f"{r} ({self.items[r].get('it')}: {self.items[r].get('gloss')})"
        for table, key in ((self.points, "title"), (self.syllabus, "label"), (self.can_dos, "text")):
            if r in table:
                return f"{r} ({table[r].get(key)})"
        return f"{r} ({self.names[r]})" if r in self.names else r

    def refs(self, values: Any) -> str:
        vals = values if isinstance(values, list) else [] if values is None else [values]
        return "<br>".join(esc(self.ref_title(v)) for v in vals) or NONE

    def line(self, ref: str) -> dict[str, Any] | None:
        parsed = ids.split_line_ref(ref)
        if not parsed:
            return None
        lines = _seq(_map(self.texts.get(parsed[0])).get("lines"))
        n = parsed[1]
        return lines[n - 1] if 0 < n <= len(lines) and isinstance(lines[n - 1], dict) else None

    def audio_html(self, target: str) -> str:
        url = self.audio(target)
        return f'<audio class="audio" controls preload="none" src="{esc(url)}"></audio>' if url else ""

    # ------------------------------------------------------------ answer patterns

    def expand(self, source: str) -> tuple[list[Any] | None, str | None]:
        """(expansions, problem): the expander's expansions, or None and why the pattern doesn't expand."""
        try:
            return list(self.expander(source)), None
        except patterns.PatternError as exc:
            return None, f"Pattern error: {exc}"
        except Exception as exc:  # any other expander failure is shown, never hidden
            return None, f"{type(exc).__name__}: {exc}"

    def model(self, source: str) -> str:
        """The model answer (first expansion) as written; the pattern itself when it doesn't expand."""
        exp, _ = self.expand(source)
        return expansion_text(exp[0]) if exp else source

    def model_line(self, source: str, *, before: str = "", after: str = "") -> str:
        return row("Model answer", it(before + self.model(source) + after), "model-answer")

    def answers(self, sources: list[Any], *, title: str = "Accepted answers", model: bool = True) -> str:
        """Every accepted answer, expanded and grouped by pattern; the model answer marked."""
        groups = []
        for i, src in enumerate(str(s) for s in sources):
            exp, problem = self.expand(src)
            head = f'<code class="src">{esc(src)}</code>'
            if exp is None:
                groups.append(f'<div class="pat">{head}{tag(problem, "problem") if problem else ""}</div>')
                continue
            lis = "".join(
                f'<li lang="it"{_cls(model and i == 0 and j == 0, "model")}>{expansion_html(x)}</li>'
                for j, x in enumerate(exp)
            )
            count = tag(f"{len(exp)} answer{'s' if len(exp) != 1 else ''}", "count")
            groups.append(f'<div class="pat">{head} {count}<ol class="exp">{lis}</ol></div>')
        return f'<div class="answers"><h4>{esc(title)}</h4>{"".join(groups)}</div>' if groups else ""

    def nears(self, near: Any) -> str:
        lis = []
        for n in (_map(x) for x in _seq(near)):
            src = str(n.get("answer", ""))
            exp, problem = self.expand(src)
            shown = " · ".join(expansion_text(x) for x in exp) if exp else src
            outcome = tag("nearly right", "tag almost") if n.get("outcome") == "almost" else tag("wrong")
            lis.append(
                f"<li>{it(shown)} {outcome}{(' ' + tag(problem, 'problem')) if problem else ''}"
                f'<div class="near-hint">{md(n.get("hint") or "")}</div>{rest(n, {"answer", "outcome", "hint"})}</li>'
            )
        return f'<div class="nears"><h4>Near-misses</h4><ul>{"".join(lis)}</ul></div>' if lis else ""


# ---------------------------------------------------------------- texts and lines


REGISTER = {"tu": "tu", "lei": "Lei"}


def _register(value: Any) -> str:
    return REGISTER.get(str(value), str(value))


def line_body(ctx: Context, line: dict[str, Any], target: str) -> str:
    who = ctx.name(line.get("speaker", ""))
    if line.get("to"):
        who += f" → {ctx.name(line['to'])}"
    if line.get("register"):
        who += f" · {_register(line['register'])}"
    rows = []
    for key, name in LINE_MAPS.items():  # {Italian form: …}: the forms stay as written
        if isinstance(line.get(key), dict):
            rows.append((name, "<br>".join(f"{it(k)} → {esc(v)}" for k, v in line[key].items())))
    for key, name in (("foreign", "Foreign"), ("recognise", "Recognise only")):
        if isinstance(line.get(key), list):
            rows.append((name, chips(line[key], "chip it")))
    return (
        f'<p class="who">{esc(who)}</p><p class="it-line" lang="it">{esc(line.get("it", ""))}</p>'
        f'<p class="en-line">{esc(line.get("en", ""))}</p>{ctx.audio_html(target)}'
        + dl(rows)
        + rest(line, {"speaker", "to", "register", "it", "en", "foreign", "recognise", *LINE_MAPS})
    )


LINE_MAPS = {"gloss": "Glossed", "lemmas": "Read as", "say": "Pronounced (IPA)"}


def _table(rows: list[list[Any]], head: list[Any] | None = None, caption: str = "") -> str:
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    th = "<tr>" + "".join(f"<th>{esc(c)}</th>" for c in head) + "</tr>" if head else ""
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{cap}{th}{body}</table>"


def layout_html(layout: dict[str, Any]) -> str:
    """A real-world layout (docs/06 § 4), drawn from its data so every string can be checked."""
    kind = str(layout.get("type", ""))
    parts = [f'<div class="layout layout-{esc(kind)}" lang="it">{tag(kind, "layout-kind")}']
    shown = {"type", "ignore"}
    for key in ("title", "shop", "greeting", "from", "time"):
        if layout.get(key):
            parts.append(f'<p class="layout-{key}">{esc(layout[key])}</p>')
            shown.add(key)
    for sec in (_map(s) for s in _seq(layout.get("sections"))):
        rows = [
            [_map(r).get("name", ""), _map(r).get("price", ""), _map(r).get("note") or ""]
            for r in _seq(sec.get("rows"))
        ]
        parts.append(_table(rows, caption=str(sec.get("title", ""))))
        shown.add("sections")
    if kind == "timetable":
        parts.append(_table([_seq(r) for r in _seq(layout.get("rows"))], _seq(layout.get("columns"))))
        shown |= {"columns", "rows"}
    elif layout.get("rows"):
        parts.append(_table([list(_map(r).values()) for r in _seq(layout["rows"])]))
        shown.add("rows")
    if layout.get("fields"):
        parts.append(dl([(str(_map(f).get("label", "")), esc(_map(f).get("value", ""))) for f in layout["fields"]]))
        shown.add("fields")
    for key in ("lines", "body", "bubbles", "items", "address"):
        if layout.get(key):
            parts.append("".join(f'<p class="layout-{key}">{esc(x)}</p>' for x in _seq(layout[key])))
            shown.add(key)
    for key in ("closing", "signature", "total", "footer", "contact", "note", "style"):
        if layout.get(key):
            parts.append(f'<p class="layout-{key}">{esc(layout[key])}</p>')
            shown.add(key)
    parts.append("</div>")
    if layout.get("ignore"):
        parts.append(f'<p class="small">Decorative, not glossed: {esc(", ".join(map(str, layout["ignore"])))}</p>')
    return "".join(parts) + rest(layout, shown)


def text_elements(ctx: Context, text: dict[str, Any], file: str, depth: int, *, owner: str = "") -> list[Element]:
    """A text: one element for its header (title, kind, layout) and one per line."""
    tid = str(text.get("id", ""))
    title = _map(text.get("title"))
    layout = text.get("layout")
    head = [f'<p class="text-kind">{esc(text.get("kind", ""))}{(" · " + esc(owner)) if owner else ""}</p>']
    if title:
        head.append(f'<p class="text-title">{it(title.get("it", ""))} {en(title.get("en", ""))}</p>')
    if isinstance(layout, dict):
        head.append(layout_html(layout))
    head.append(ctx.audio_html(tid))
    head.append(rest(text, {"kind", "title", "layout", "lines"}))
    counted = bool(title) or isinstance(layout, dict)
    quote = title.get("it") if title else _map(layout).get("title")
    data = {k: v for k, v in text.items() if k != "lines"}
    out = [
        Element(tid, tid, file, "text", f"Text {tid}", "".join(head), _short(quote), fingerprint(data), counted, depth)
    ]
    for n, line in enumerate(_seq(text.get("lines")), start=1):
        if isinstance(line, dict):
            target = f"{tid}#{n}"
            body = line_body(ctx, line, target)
            out.append(
                Element(
                    target,
                    target,
                    file,
                    "line",
                    f"Line {n}",
                    body,
                    _short(line.get("it")),
                    fingerprint(line),
                    True,
                    depth + 1,
                )
            )
    return out


# ---------------------------------------------------------------- exercises


def _targets(ctx: Context, ex: dict[str, Any]) -> str:
    return "<br>".join(
        f"{esc(ctx.ref_title(_map(t).get('item', '')))} · {esc(_map(t).get('skill', ''))}"
        for t in _seq(ex.get("targets"))
    )


def _source(ctx: Context, src: Any, file: str, depth: int) -> tuple[str, list[Element]]:
    """An exercise's `source`: a line it reuses, a text shown elsewhere, or inline texts (elements of their own)."""
    if isinstance(src, str):
        line = ctx.line(src)
        if line:
            return row(f"From {src}", f"{it(line.get('it', ''))} {en(line.get('en', ''))}", "source"), []
        return row("Source", esc(src), "source"), []
    src = _map(src)
    if isinstance(src.get("text"), str):
        return row("Source", f"text {esc(src['text'])}, shown with that text", "source"), []
    nested: list[Element] = []
    for key in ("text", "audio_text"):
        if isinstance(src.get(key), dict):
            nested += text_elements(ctx, src[key], file, depth + 1, owner="source")
    return "", nested


PROMPTS_IT = ("context_it", "prompt_it")
PROMPTS_EN = ("prompt_en", "question_en", "statement_en", "friend_en")


def _format_parts(ctx: Context, ex: dict[str, Any], parts: list[str], shown: set[str]) -> str | None:
    """The format-specific part of an exercise. Returns the model answer (or the main text) as the quote."""
    fmt = str(ex.get("format", ""))
    eid = str(ex.get("id", ""))
    quote: str | None = None
    if fmt == "cloze" and isinstance(ex.get("text"), str):
        shown.add("text")
        m = re.search(r"\[\[(.+?)\]\]", ex["text"])
        if not m:
            parts.append(f'<p class="cloze" lang="it">{esc(ex["text"])}</p>')
            return ex["text"]
        before, gap, after = ex["text"][: m.start()], m.group(1), ex["text"][m.end() :]
        model = ctx.model(gap)
        parts.append(f'<p class="cloze" lang="it">{esc(before)}<mark class="gap">{esc(model)}</mark>{esc(after)}</p>')
        parts.append(ctx.model_line(gap, before=before, after=after))
        parts.append(ctx.answers([gap], title="Accepted in the gap"))
        quote = before + model + after
    elif fmt == "recall" and ex.get("answer") is not None:
        shown.add("answer")
        parts.append(ctx.model_line(str(ex["answer"])))
        parts.append(ctx.answers([ex["answer"]]))
        parts.append(ctx.audio_html(eid) if ex.get("audio_after") else "")
        quote = ctx.model(str(ex["answer"]))
    elif fmt == "sentence-building":
        shown |= {"tiles", "distractors", "answer"}
        parts.append(row("Tiles", chips(_seq(ex.get("tiles")), "chip it")))
        if ex.get("distractors"):
            parts.append(row("Distractors", chips(_seq(ex["distractors"]), "chip it")))
        orders = [str(a) for a in _seq(ex.get("answer"))]
        lis = "".join(f'<li lang="it"{_cls(i == 0, "model")}>{esc(a)}</li>' for i, a in enumerate(orders))
        parts.append(f'<div class="answers"><h4>Accepted orders</h4><ol class="exp">{lis}</ol></div>')
        quote = orders[0] if orders else None
    elif fmt in ("dictation", "repeat") and ex.get("say") is not None:
        shown.add("say")
        parts.append(row("Says", it(ex["say"], "it prompt")) + ctx.audio_html(eid))
        quote = ex["say"]
    elif fmt == "choice":
        shown |= {"options", "answer"}
        right = ex.get("answer")
        lis = "".join(
            f"<li{_cls(i == right, 'correct')}>{md(o)}{(' ' + tag('answer', 'tag ok')) if i == right else ''}</li>"
            for i, o in enumerate(_seq(ex.get("options")))
        )
        parts.append(f'<ol class="options">{lis}</ol>')
    elif fmt == "true-false" and "answer" in ex:
        shown.add("answer")
        parts.append(row("Answer", "true" if ex["answer"] else "false"))
    elif fmt == "match":
        shown.add("pairs")
        trs = "".join(
            f"<tr><td lang='it' class='it'>{esc(p[0])}</td><td>{esc(p[1])}</td></tr>"
            for p in (_seq(x) for x in _seq(ex.get("pairs")))
            if len(p) == 2
        )
        parts.append(f'<table class="pairs"><tr><th>Italian</th><th>English</th></tr>{trs}</table>')
    elif fmt == "sound-pair":
        shown |= {"pair", "glosses", "play", "word", "answer"}
        pair = [str(x) for x in _seq(ex.get("pair"))]
        glosses = _map(ex.get("glosses"))
        if pair:
            parts.append(row("Pair", " · ".join(f"{it(w)} ({esc(glosses.get(w, ''))})" for w in pair)))
        if ex.get("play"):
            parts.append(row("Plays", it(ex["play"])))
        if ex.get("word"):
            parts.append(row("Word", f"{it(ex['word'])} → {esc(ex.get('answer', ''))}"))
        quote = " / ".join(pair) or ex.get("word")
    elif fmt == "conversation":
        shown |= {"with", "register", "title", "goals", "start", "nodes"}
        goals = "".join(
            f"<li><strong>{esc(_map(g).get('id', ''))}</strong> {esc(_map(g).get('en', ''))}</li>"
            for g in _seq(ex.get("goals"))
        )
        who = f"{esc(ctx.name(ex.get('with', '')))} · {esc(_register(ex.get('register')))}"
        parts.append(row("Title", esc(_map(ex.get("title")).get("en", ""))))
        parts.append(row("With", f"{who}; starts at {esc(ex.get('start', ''))}"))
        parts.append(f'<div class="goals"><h4>Goals</h4><ul>{goals}</ul></div>')
        quote = _map(ex.get("title")).get("en")
    elif fmt == "relay" and ex.get("answer_en") is not None:
        shown.add("answer_en")
        parts.append(row("Answer", value_html(ex["answer_en"])))
    if fmt in ("talk", "writing") and ex.get("points"):
        shown.add("points")
        parts.append(_points(ctx, ex))
    if fmt == "writing" and ex.get("fields"):
        shown.add("fields")
        lis = []
        for f in (_map(x) for x in _seq(ex["fields"])):
            acc = ctx.answers(_seq(f.get("accept")), title="Accepted") if f.get("accept") else ""
            lis.append(
                f"<li>{it(f.get('label_it', ''))} {en(f'({f.get("label_en", "")}, {f.get("type", "")})')}{acc}</li>"
            )
        parts.append(f'<div class="fields"><h4>Form fields</h4><ul>{"".join(lis)}</ul></div>')
    if fmt in ("talk", "writing") and ex.get("model"):
        shown.add("model")
        parts.append(row("Model answer", it(ex["model"]), "model-answer"))
        quote = quote or ex["model"]
    return quote


def _points(ctx: Context, ex: dict[str, Any]) -> str:
    lis = "".join(
        f"<li><strong>{esc(p.get('id', ''))}</strong> {esc(p.get('en', ''))}"
        f"{ctx.answers(_seq(p.get('accept')), title='Counts when the answer contains', model=False)}</li>"
        for p in (_map(x) for x in _seq(ex.get("points")))
    )
    note = f'<p class="small">Passes with {esc(ex["pass"])} of the points.</p>' if ex.get("pass") else ""
    return f'<div class="points"><h4>Content points</h4><ul>{lis}</ul>{note}</div>'


def exercise_elements(ctx: Context, ex: dict[str, Any], file: str, depth: int, where: str = "") -> list[Element]:
    """An exercise, then its inline texts and (for a conversation) one element per node."""
    eid = str(ex.get("id", ""))
    fmt = str(ex.get("format", ""))
    parts: list[str] = []
    nested: list[Element] = []
    shown = {"format", "targets", "tags", "source", "audio_text", "score", "near", "hint", "rule", "tip_en"}
    if ex.get("source") is not None:
        source_html, nested = _source(ctx, ex["source"], file, depth)
        parts.append(source_html)
    if isinstance(ex.get("audio_text"), dict):
        parts.append(
            row("Plays", f"text {esc(ex['audio_text'].get('id', ''))} (below), hidden until answered", "source")
        )
        nested += text_elements(ctx, ex["audio_text"], file, depth + 1, owner="audio")
    prompt = None
    for key in (*PROMPTS_IT, *PROMPTS_EN):
        if ex.get(key) is not None:
            shown.add(key)
            value = it(ex[key], "it prompt") if key in PROMPTS_IT else f'<span class="prompt">{md(ex[key])}</span>'
            parts.append(row(label(key), value))
            prompt = prompt or ex[key]
    quote = _format_parts(ctx, ex, parts, shown) or prompt
    parts.append(ctx.nears(ex.get("near")))
    for key in ("hint", "rule", "tip_en"):
        if ex.get(key):
            parts.append(row(label(key), md(ex[key])))
    meta = []
    if ex.get("targets"):
        meta.append(("Trains", _targets(ctx, ex)))
    if ex.get("tags"):
        meta.append(("Tags", ctx.refs(ex["tags"])))
    if ex.get("score") is not None:
        meta.append(("Score", esc(ex["score"])))
    parts.append(dl(meta, "kv meta"))
    parts.append(rest(ex, shown))
    # The fingerprint covers what this element shows; nodes and inline texts are elements of their own.
    data = {k: v for k, v in ex.items() if k not in ("nodes", "audio_text")}
    if isinstance(data.get("source"), dict) and not isinstance(data["source"].get("text"), str):
        data.pop("source")
    head = f"{where} · {fmt}" if where else fmt
    out = [
        Element(
            eid, eid, file, "exercise", f"{head} {eid}", "".join(parts), _short(quote), fingerprint(data), True, depth
        )
    ]
    out += nested
    if fmt == "conversation":
        out += node_elements(ctx, ex, file, depth + 1)
    return out


def node_elements(ctx: Context, ex: dict[str, Any], file: str, depth: int) -> list[Element]:
    """A conversation as a tree of turns: one element per node, in authored order, linked by `next`."""
    eid = str(ex.get("id", ""))
    goals = {str(_map(g).get("id")): str(_map(g).get("en", "")) for g in _seq(ex.get("goals"))}
    out = []
    for nid, node in _map(ex.get("nodes")).items():
        node = _map(node)
        target = f"{eid}/{nid}"
        parts = [
            line_body(ctx, {"speaker": ex.get("with", ""), "it": node.get("say", ""), "en": node.get("en", "")}, target)
        ]
        if node.get("register"):
            parts.append(row("Register from here", esc(_register(node["register"]))))
        for k, intent in enumerate(_map(x) for x in _seq(node.get("expect"))):
            accept = _seq(intent.get("accept"))
            goal, nxt = str(intent.get("goal", "")), str(intent.get("next", ""))
            goal_text = f" ({esc(goals[goal])})" if goal in goals else ""
            link = f'<a href="#{anchor(f"{eid}/{nxt}")}">{esc(nxt)}</a>'
            parts.append(
                '<div class="intent">'
                + row("You", f"<strong>{esc(intent.get('intent', ''))}</strong> · goal {esc(goal)}{goal_text} → {link}")
                + (ctx.model_line(str(accept[0])) if k == 0 and accept else "")
                + ctx.answers(accept, model=k == 0)
                + rest(intent, {"intent", "goal", "next", "accept"})
                + "</div>"
            )
        parts.append(ctx.nears(node.get("near")))
        if node.get("help") is not None:
            parts.append(row("Help chips", chips(_seq(node["help"]), "chip it") or NONE))
        if node.get("hint_en"):
            parts.append(row("Hint", md(node["hint_en"])))
        if node.get("final"):
            parts.append(row("End", ""))
        parts.append(rest(node, {"say", "en", "expect", "near", "help", "hint_en", "final", "register"}))
        name = f"Node {nid}" + (" (start)" if nid == ex.get("start") else "")
        quote = _short(node.get("say"))
        out.append(Element(target, target, file, "node", name, "".join(parts), quote, fingerprint(node), True, depth))
    return out


# ---------------------------------------------------------------- lessons, notes, steps


def note_element(ctx: Context, step: dict[str, Any], file: str, depth: int) -> Element:
    nid = str(step.get("note_id") or step.get("id"))
    parts = [
        f'<h4 class="note-title">{md(step.get("title_en", ""))}</h4>',
        row("Introduces", ctx.refs(step.get("grammar"))),
    ]
    intro = _map(step.get("intro"))
    if intro:
        parts.append(row(f"Moka ({intro.get('mascot', '')})", md(intro.get("text_en", "")), "intro"))
    for block in (_map(b) for b in _seq(step.get("body"))):
        if "p" in block:
            parts.append(f"<p>{md(block['p'])}</p>")
        elif "table" in block:
            t = _map(block["table"])
            head = "".join(f"<th>{md(c)}</th>" for c in _seq(t.get("columns")))
            trs = "".join(
                "<tr>" + "".join(f"<td lang='it'>{md(c)}</td>" for c in _seq(r)) + "</tr>" for r in _seq(t.get("rows"))
            )
            parts.append(f'<table class="note-table"><tr>{head}</tr>{trs}</table>')
        elif "examples" in block:
            lis = []
            for ref in (str(r) for r in _seq(block["examples"])):
                line = ctx.line(ref) or {}
                lis.append(f"<li>{it(line.get('it', ref))} {en(line.get('en', ''))} <code>{esc(ref)}</code></li>")
            parts.append(f'<ul class="examples">{"".join(lis)}</ul>')
        elif "tip" in block:
            parts.append(row("Tip", md(block["tip"]), "tip"))
        else:
            parts.append(value_html(block))
    parts.append(rest(step, {"kind", "note_id", "grammar", "title_en", "intro", "body"}))
    data = {k: v for k, v in step.items() if k != "id"}
    quote = _short(step.get("title_en"))
    return Element(nid, nid, file, "note", f"Grammar note {nid}", "".join(parts), quote, fingerprint(data), True, depth)


STEP_TITLES = {
    "preview": "Preview words",
    "story": "Story",
    "listening": "Listening",
    "reading": "Real-world reading",
    "note": "Grammar note",
    "practice": "Practice",
    "sounds": "Sounds",
    "use": "Use",
}


def step_entries(ctx: Context, step: dict[str, Any], file: str) -> list[Element | Heading]:
    kind = str(step.get("kind", ""))
    sid = str(step.get("id", ""))
    parts = []
    shown = {"kind", "text", "questions", "exercises", "block", "mix", "exercise"}
    if kind == "preview":
        shown.add("batches")
        for k, batch in enumerate(_seq(step.get("batches")), start=1):
            lis = "".join(
                f"<li>{it(_map(ctx.items.get(str(i))).get('it', i))} {en(_map(ctx.items.get(str(i))).get('gloss', ''))}"
                f" <code>{esc(i)}</code></li>"
                for i in _seq(batch)
            )
            parts.append(f'<div class="batch"><h4>Batch {k}</h4><ul>{lis}</ul></div>')
    if kind == "note":
        shown |= {"note_id", "grammar", "title_en", "intro", "body"}
    parts.append(rest(step, shown))
    data = {k: v for k, v in step.items() if k in ("kind", "id", "batches", "plays")}
    title = f"{STEP_TITLES.get(kind, kind)} · {sid}"
    out: list[Element | Heading] = [
        Element(sid, sid, file, "step", title, "".join(parts), None, fingerprint(data), False)
    ]
    if kind in ("story", "listening", "reading") and isinstance(step.get("text"), dict):
        out += text_elements(ctx, step["text"], file, 1)
    if kind == "note":
        out.append(note_element(ctx, step, file, 1))
    groups: list[tuple[str, str]] = []
    if kind == "story":
        groups = [("questions", "question")]
    elif kind in ("listening", "reading", "sounds"):
        groups = [("exercises", "")]
    elif kind == "practice":
        groups = [("block", "block"), ("mix", "mix")]
    for key, where in groups:
        exs = [ex for ex in _seq(step.get(key)) if isinstance(ex, dict)]
        if kind == "practice" and exs:
            out.append(Heading("Block: the new structure" if key == "block" else "Mix: with earlier units", 4))
        for ex in exs:
            out += exercise_elements(ctx, ex, file, 1, where)
    if kind == "use" and isinstance(step.get("exercise"), dict):
        out += exercise_elements(ctx, step["exercise"], file, 1)
    return out


def _status(doc: Doc | None) -> str | None:
    review = _map(_map(doc.data if doc else None).get("review"))
    return str(review["status"]) if review.get("status") else None


def lesson_section(ctx: Context, doc: Doc, unit: UnitFiles) -> Section:
    data = _map(doc.data)
    lid = str(data.get("id", ""))
    title = _map(data.get("title"))
    head = f'<p class="text-title">{it(title.get("it", ""))} {en(title.get("en", ""))}</p>'
    if data.get("scene"):
        head += row("Scene", md(data["scene"]))
    head += rest(data, {"title", "scene", "steps"})
    header = {k: v for k, v in data.items() if k not in ("steps", "review")}
    entries: list[Element | Heading] = [
        Element(lid, lid, doc.rel, "lesson", f"Lesson {lid}", head, _short(title.get("it")), fingerprint(header))
    ]
    for _, step in lesson_steps(doc):
        entries += step_entries(ctx, step, doc.rel)
    k = lid.rsplit(".l", 1)[-1]
    return Section(doc.rel, f"Lesson {k} · {title.get('it', '')}", _status(doc), entries, scope_title(unit.id))


ITEM_FIELDS = ("pos", "gender", "plural", "alt_glosses", "status", "lesson", "topics", "forms", "match", "pairs")


def items_section(ctx: Context, doc: Doc, unit: UnitFiles) -> Section:
    entries: list[Element | Heading] = []
    for item in _seq(_map(doc.data).get("items")):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        iid = str(item["id"])
        kind = {"chunk": "Chunk", "sound": "Sound"}.get(str(item.get("kind")), "Word")
        rows = [(label(k), value_html(item[k])) for k in ITEM_FIELDS if k in item]
        if item.get("exemplifies"):
            rows.append(("Previews the rule", ctx.refs(item["exemplifies"])))
        parts = [
            f'<p class="item-head">{it(item.get("it", ""), "it big")} {en(item.get("gloss", ""))}</p>',
            ctx.audio_html(iid),
            dl(rows),
            row("Note", md(item["note"])) if item.get("note") else "",
            ctx.answers([item["recall_answer"]], title="Accepted on recall cards") if item.get("recall_answer") else "",
            rest(item, {"it", "gloss", "kind", "note", "recall_answer", "exemplifies", *ITEM_FIELDS}),
        ]
        quote = _short(item.get("it"))
        entries.append(Element(iid, iid, doc.rel, "item", f"{kind} {iid}", "".join(parts), quote, fingerprint(item)))
    return Section(doc.rel, "Words, chunks and sounds", _status(doc), entries, scope_title(unit.id))


def task_section(ctx: Context, doc: Doc, unit: UnitFiles) -> Section:
    data = _map(doc.data)
    entries: list[Element | Heading] = []
    convs = [c for c in _seq(data.get("conversations")) if isinstance(c, dict)]
    if convs:
        entries.append(Heading("Conversations"))
    for c in convs:
        entries += exercise_elements(ctx, c, doc.rel, 0)
    for key, title in (("talk", "Talk about it"), ("writing", "Guided writing"), ("relay", "Relay to a friend")):
        if isinstance(data.get(key), dict):
            entries.append(Heading(title))
            entries += exercise_elements(ctx, data[key], doc.rel, 0)
    return Section(doc.rel, "Unit task", _status(doc), entries, scope_title(unit.id))


def check_section(ctx: Context, doc: Doc, title: str, group: str) -> Section:
    """A unit check, the placement test or the final check: sections (or blocks) of exercises."""
    data = _map(doc.data)
    did = str(data.get("id", ""))
    entries: list[Element | Heading] = []
    head = rest(data, {"sections", "blocks"})
    if head:
        settings = {k: v for k, v in data.items() if k not in ("sections", "blocks", "review")}
        entries.append(Element(did, did, doc.rel, "check", f"{title} {did}", head, None, fingerprint(settings), False))
    groups = data.get("sections") if data.get("sections") is not None else data.get("blocks")
    for g in (_map(x) for x in _seq(groups)):
        name = str(g.get("title_en") or g.get("id") or g.get("unit") or "")
        extra = ", ".join(f"{k}: {v}" for k, v in g.items() if k not in ("exercises", "title_en", "id"))
        entries.append(Heading(f"{name} · {extra}" if extra else name))
        for ex in _seq(g.get("exercises")):
            if isinstance(ex, dict):
                entries += exercise_elements(ctx, ex, doc.rel, 0)
    return Section(doc.rel, title, _status(doc), entries, group)


# ---------------------------------------------------------------- the sign-off files (specs)


def _spec(
    target: str, file: str, kind: str, name: str, body: str, quote: Any, data: Any, counted: bool = True
) -> Element:
    return Element(target, target, file, kind, name, body, _short(quote), fingerprint(data), counted)


AREAS = {
    "gr": "Grammar",
    "fn": "Functions",
    "tp": "Topics",
    "ss": "Sounds, spelling and register",
    "cefr": "CEFR scales",
    "ex": "Exam task types",
}


def syllabus_section(ctx: Context, doc: Doc) -> Section:
    data = _map(doc.data)
    entries: list[Element | Heading] = []
    if data.get("sources"):
        entries.append(
            _spec(
                "syllabus.sources",
                doc.rel,
                "spec",
                "Sources",
                value_html(data["sources"]),
                None,
                data["sources"],
                False,
            )
        )
    area = None
    for e in _seq(data.get("items")):
        if not isinstance(e, dict) or not e.get("id"):
            continue
        if e.get("area") != area:
            area = e.get("area")
            entries.append(Heading(AREAS.get(str(area), str(area))))
        rows = [
            ("Course decision", md(e.get("course", ""))),
            ("Sources", value_html(e.get("sources"))),
            ("Units", value_html(e.get("units"))),
            ("Covered by", ctx.refs(e.get("covered_by"))),
        ]
        body = f'<p class="spec-label">{md(e.get("label", ""))}</p>' + dl(rows)
        body += rest(e, {"area", "label", "course", "sources", "units", "covered_by"})
        entries.append(_spec(str(e["id"]), doc.rel, "syllabus", f"Syllabus {e['id']}", body, e.get("label"), e))
    return Section(doc.rel, "A1 syllabus", _status(doc), entries, "Syllabus and grammar")


def points_section(ctx: Context, doc: Doc) -> Section:
    entries: list[Element | Heading] = []
    unit = None
    for p in _seq(_map(doc.data).get("points")):
        if not isinstance(p, dict) or not p.get("id"):
            continue
        if p.get("unit") != unit:
            unit = p.get("unit")
            entries.append(Heading(scope_title(str(unit)) if re.fullmatch(r"u\d{2}", str(unit)) else str(unit)))
        rows = [("Status", value_html(p.get("status"))), ("Unit", value_html(p.get("unit")))]
        rows += [(label(k), ctx.refs(p[k])) for k in ("syllabus", "requires", "confusable") if p.get(k)]
        body = f'<p class="spec-label">{md(p.get("title", ""))}</p>' + dl(rows)
        body += row("About", md(p["about"])) if p.get("about") else ""
        body += rest(p, {"title", "unit", "status", "syllabus", "requires", "confusable", "about"})
        entries.append(_spec(str(p["id"]), doc.rel, "grammar", f"Grammar point {p['id']}", body, p.get("title"), p))
    return Section(doc.rel, "Grammar points", _status(doc), entries, "Syllabus and grammar")


def unit_spec_section(ctx: Context, unit: UnitFiles) -> Section:
    assert unit.spec is not None
    doc = unit.spec
    data = _map(doc.data)
    uid = unit.id
    title = _map(data.get("title"))
    entries: list[Element | Heading] = []
    head_keys = ("title", "episode", "arc", "est_hours", "lessons", "recycle_from", "notes")
    head = {k: data[k] for k in head_keys if k in data}
    body = f'<p class="text-title">{it(title.get("it", ""))} {en(title.get("en", ""))}</p>'
    body += dl([(label(k), value_html(v)) for k, v in head.items() if k != "title"])
    entries.append(_spec(uid, doc.rel, "unit", f"Unit {uid}", body, title.get("it"), head))
    can_dos = [c for c in _seq(data.get("can_do")) if isinstance(c, dict) and c.get("id")]
    if can_dos:
        entries.append(Heading("Can-dos", 4))
    for cd in can_dos:
        body = f'<p class="spec-label">{md(cd.get("text", ""))}</p>'
        body += dl([("Scale", value_html(cd.get("scale"))), ("Syllabus", ctx.refs(cd.get("syllabus")))])
        body += rest(cd, {"text", "scale", "syllabus"})
        entries.append(_spec(str(cd["id"]), doc.rel, "can-do", f"Can-do {cd['id']}", body, cd.get("text"), cd))
    if "grammar" in data:
        lis = "".join(
            f"<li><code>{esc(g.get('id', ''))}</code> {tag(g.get('status', ''))} "
            f"{md(_map(ctx.points.get(str(g.get('id')))).get('title', ''))}</li>"
            for g in (_map(x) for x in _seq(data["grammar"]))
        )
        entries.append(
            _spec(
                f"{uid}.grammar", doc.rel, "spec", "Grammar", f"<ul>{lis}</ul>" if lis else NONE, None, data["grammar"]
            )
        )
    for key, name in (
        ("chunks", "Chunks"),
        ("items", "Words"),
        ("sounds", "Sounds"),
        ("texts", "Texts"),
        ("tasks", "Tasks"),
    ):
        if data.get(key) not in (None, [], ""):
            body = ctx.refs(data[key]) if key == "sounds" else value_html(data[key])
            quote = data[key] if isinstance(data[key], str) else None
            entries.append(_spec(f"{uid}.{key}", doc.rel, "spec", name, body, quote, data[key]))
    if isinstance(data.get("check"), dict):
        # `uNN.check` is the check file's ID, so the spec's check plan is named by its first key.
        entries.append(
            _spec(f"{uid}.check.items", doc.rel, "spec", "Unit check", value_html(data["check"]), None, data["check"])
        )
    known = {"id", "review", *head_keys, "can_do", "grammar", "chunks", "items", "sounds", "texts", "tasks", "check"}
    for key, v in data.items():
        if key not in known and re.fullmatch(r"[a-z_]+", str(key)):
            entries.append(_spec(f"{uid}.{key}", doc.rel, "spec", label(key), value_html(v), None, v))
    return Section(doc.rel, f"{scope_title(uid)} · {title.get('it', '')}", _status(doc), entries, "Unit specs")


def story_bible_section(ctx: Context, doc: Doc) -> Section:
    f = doc.rel
    entries: list[Element | Heading] = []
    for key, v in _map(doc.data).items():
        if key == "review":
            continue
        if key == "characters":
            entries.append(Heading("Characters"))
            for ch in (c for c in _seq(v) if isinstance(c, dict) and c.get("id")):
                body = f'<p class="spec-label">{esc(ch.get("name", ""))}</p>' + rest(ch, {"name"})
                entries.append(_spec(str(ch["id"]), f, "character", f"Character {ch['id']}", body, ch.get("name"), ch))
        elif key == "places":
            entries.append(Heading("Places"))
            for i, p in enumerate(_map(x) for x in _seq(v)):
                body = f'<p class="spec-label">{esc(p.get("name", ""))} {tag(p.get("kind", ""))}</p>'
                body += rest(p, {"name", "kind"})
                entries.append(_spec(f"story-bible.places[{i}]", f, "place", "Place", body, p.get("name"), p))
        elif key == "facts_to_check":
            entries.append(Heading("Facts to check"))
            for i, fact in enumerate(_map(x) for x in _seq(v)):
                body = f'<p class="spec-label">{md(fact.get("fact", ""))}</p>' + rest(fact, {"fact"})
                entries.append(
                    _spec(f"story-bible.facts_to_check[{i}]", f, "fact", "Fact", body, fact.get("fact"), fact)
                )
        elif key == "registers":
            entries.append(Heading("Who says tu or Lei to whom"))
            for i, r in enumerate(_map(x) for x in _seq(v)):
                frm = "anyone" if r.get("from") == "*" else ctx.name(r.get("from", ""))
                to = "anyone" if r.get("to") == "*" else ctx.name(r.get("to", ""))
                text = f"{frm} → {to}: {_register(r.get('register'))}"
                if r.get("then"):
                    text += f", then {_register(r['then'])} from {r.get('switch_at')}"
                body = f'<p class="spec-label">{esc(text)}</p>' + rest(
                    r, {"from", "to", "register", "then", "switch_at"}
                )
                entries.append(_spec(f"story-bible.registers[{i}]", f, "register", "Register", body, text, r))
        else:
            entries.append(_spec(f"story-bible.{key}", f, "spec", label(key), value_html(v), None, v))
    return Section(f, "Story bible", _status(doc), entries, "Story")


def countries_section(ctx: Context, doc: Doc) -> Section:
    data = _map(doc.data)
    entries: list[Element | Heading] = []
    for c in (c for c in _seq(data.get("countries")) if isinstance(c, dict) and c.get("id")):
        rows = [
            ("abito …", it(c.get("home_phrase", ""))),
            ("sono … (m / f)", it(f"{c.get('m', '')} / {c.get('f', '')}")),
        ]
        body = f'<p class="spec-label">{esc(c.get("en", ""))} · {it(c.get("it", ""))}</p>' + dl(rows)
        body += rest(c, {"en", "it", "home_phrase", "m", "f"})
        entries.append(_spec(str(c["id"]), doc.rel, "country", f"Country {c['id']}", body, c.get("home_phrase"), c))
    if isinstance(data.get("other"), dict):
        entries.append(
            _spec(
                "countries.other", doc.rel, "country", "Another country", value_html(data["other"]), None, data["other"]
            )
        )
    return Section(doc.rel, "Countries", _status(doc), entries, "Story")


def questions_section(ctx: Context) -> Section:
    entries: list[Element | Heading] = []
    for q in questions(ctx.course.root):
        body = f'<p class="spec-label">{md(q.question)}</p>' + row("Default in the drafts", md(q.default))
        data = {"question": q.question, "default": q.default}
        entries.append(_spec(q.id, DECISIONS, "question", f"Question {q.id}", body, q.question, data))
    return Section(DECISIONS, "Content questions (docs/13)", None, entries, "Questions")


# ---------------------------------------------------------------- scopes


def build_page(ctx: Context, scope: str) -> PageModel:
    """Every section and element of the review page for `scope` (`specs`, `assessments` or `uNN`)."""
    course = ctx.course
    sections: list[Section] = []
    if scope == "specs":
        s = course.singles
        if "syllabus" in s:
            sections.append(syllabus_section(ctx, s["syllabus"]))
        if "points" in s:
            sections.append(points_section(ctx, s["points"]))
        sections += [unit_spec_section(ctx, u) for u in course.units if u.spec is not None]
        if "story_bible" in s:
            sections.append(story_bible_section(ctx, s["story_bible"]))
        if "countries" in s:
            sections.append(countries_section(ctx, s["countries"]))
        if DECISIONS in scope_files(course, scope):
            sections.append(questions_section(ctx))
        title = "Sign-off: syllabus, unit specs, grammar points, story bible, countries, content questions"
    elif scope == "assessments":
        for key, name in (("placement", "Placement"), ("final", "Final A1 check")):
            if key in course.assessments:
                sections.append(check_section(ctx, course.assessments[key], name, "Assessments"))
        title = "Placement and the final A1 check"
    else:
        unit = course.unit(scope)
        if unit is None:
            raise ValueError(f"no unit {scope} in content/course.yaml")
        if unit.items:
            sections.append(items_section(ctx, unit.items, unit))
        sections += [lesson_section(ctx, doc, unit) for doc in unit.lessons]
        if unit.task:
            sections.append(task_section(ctx, unit.task, unit))
        if unit.check:
            sections.append(check_section(ctx, unit.check, "Unit check", scope_title(unit.id)))
        spec_title = _map(_map(unit.spec.data if unit.spec else None).get("title"))
        title = f"{scope_title(scope)} · {spec_title.get('it', '')} ({spec_title.get('en', '')})"
    files = {rel: h for rel in scope_files(course, scope) if (h := version_hash(course.root, rel)) is not None}
    return PageModel(scope, title, sections, files)
