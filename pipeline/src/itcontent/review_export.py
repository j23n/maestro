"""`content review-export (--specs | --unit uNN | --assessments) [--since]` (docs/04 § Content review loop, M1.3).

Writes one self-contained HTML file (`build/review/<scope>/index.html`): styles and script inline, no network, so it
opens offline from an email attachment or a shared folder. The page lists every element of the scope
(`review_elements`), with a verdict, a category, a comment and a suggestion per element; it saves as the teacher types
(localStorage), downloads the review file (`schemas/review-file.schema.json`) and signs off with the hash of every
file. The page is deterministic: the same content gives the same bytes.

- `--since` adds what happened after earlier reviews: each earlier comment (from the ledgers) with its resolution,
  a "Reopen" button, and a mark on every element whose fingerprint differs from the one the teacher last saw (the
  `elements` map of the latest filed review of this scope that showed it) or that is new since then.
- Unit pages (and `--assessments`) start with "Answers to adjudicate" when the beta's rejected answers
  (`content beta-import` → `build/reports/beta/rejected.json`) have some nobody has judged yet (task M8.3).
- Sign-off is possible only when no comment on the page asks for a change and no ledger comment on these files is
  open (or waiting for the owner).
- Audio (M5.1, `review_audio`): every rendered text, line, item and voiced exercise string gets a play button; each
  file is embedded once (base64 in a JSON script element), so the page still opens offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths, schemas
from itcontent.adjudication import adjudication_section, rejected_answers
from itcontent.course import load_course
from itcontent.ledger import Entry, entries, ledger_rel
from itcontent.review import ADJUDICATIONS, CATEGORIES, VERDICTS, load_json, scope_title, target_problem
from itcontent.review_audio import ReviewAudio, page_audio
from itcontent.review_elements import (
    Context,
    Element,
    Expander,
    Heading,
    PageModel,
    Section,
    anchor,
    build_page,
    esc,
    md,
    tag,
)

TEMPLATES = Path(__file__).resolve().parent / "templates" / "review"
RESOLUTION_LABELS = {
    "open": "Open",
    "fixed": "Fixed",
    "answered": "Answered",
    "declined": "Declined",
    "owner": "Waiting for the owner",
    "noted": "Noted",
}


# ---------------------------------------------------------------- --since


@dataclass
class Since:
    by_target: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # earlier comments per target
    orphans: list[dict[str, Any]] = field(default_factory=list)  # earlier comments whose target isn't on the page
    marks: dict[str, str] = field(default_factory=dict)  # target → changed | new
    baseline: list[str] = field(default_factory=list)  # the filed reviews the marks compare with


def filed_reviews(root: Path, scope: str) -> list[tuple[str, dict[str, Any]]]:
    """Valid review files of `scope` in reviews/inbox/, oldest first."""
    out = []
    for p in sorted((root / "reviews" / "inbox").glob("*.json")):
        data, problem = load_json(p)
        if problem or not isinstance(data, dict) or data.get("scope") != scope:
            continue
        if schemas.validate("review-file", data):
            continue
        out.append((p.relative_to(root).as_posix(), data))
    return sorted(out, key=lambda r: (str(r[1].get("created")), r[0]))


def since_info(root: Path, model: PageModel, ledger_entries: list[Entry], exists: Callable[[str], bool]) -> Since:
    """Earlier comments per element (from every ledger), the comments of this scope's ledger whose target no
    longer exists, and the change marks."""
    info = Since()
    targets = {e.target for e in model.elements() if e.fp is not None}
    for e in ledger_entries:
        target = str(e.data.get("target", ""))
        if target in targets:
            info.by_target.setdefault(target, []).append(e.data)
        elif e.ledger == ledger_rel(model.scope) and not exists(target):
            info.orphans.append(e.data)
    seen: dict[str, str] = {}  # target → fingerprint the teacher last saw
    covered: set[str] = set()  # files a review with fingerprints showed
    for rel, data in filed_reviews(root, model.scope):
        elements = data.get("elements")
        if not isinstance(elements, dict):
            continue
        info.baseline.append(rel)
        seen.update(elements)
        covered.update(data.get("files", {}))
    for el in model.elements():
        if el.fp is None:
            continue
        if el.target in seen:
            if seen[el.target] != el.fp:
                info.marks[el.target] = "changed"
        elif el.file in covered:
            info.marks[el.target] = "new"
    return info


# ---------------------------------------------------------------- rendering


def _date(at: Any) -> str:
    return str(at or "")[:10]


def comment_html(d: dict[str, Any], key: str | None) -> str:
    """One earlier comment with its resolution (and a Reopen button once it is resolved)."""
    res = d.get("resolution") if isinstance(d.get("resolution"), dict) else {"status": "open"}
    status = str(res.get("status", "open"))
    who = f"{d.get('reviewer') or 'the teacher'}, {_date(d.get('at'))}"
    if status == "noted":
        return f'<p class="ec status-noted">Marked OK ({esc(who)})</p>'
    head = VERDICTS.get(str(d.get("verdict")), str(d.get("verdict")))
    if d.get("category"):
        head += f" · {CATEGORIES.get(str(d['category']), d['category'])}"
    adj = d.get("adjudication") if isinstance(d.get("adjudication"), dict) else None
    if adj:
        head = f"{ADJUDICATIONS.get(str(adj.get('decision')), adj.get('decision'))} (answer key)"
    stale = " · made on an older version" if d.get("stale") else ""
    parts = [f'<p>{tag(head)} <span class="small">{esc(who)}{stale}</span></p>']
    if d.get("response"):
        parts.append(f'<p>Answer: <span lang="it" class="it">{esc(d["response"])}</span></p>')
    if d.get("comment"):
        parts.append(f"<blockquote>{esc(d['comment'])}</blockquote>")
    if d.get("suggestion"):
        parts.append(f'<p>Suggested: <span lang="it" class="it">{esc(d["suggestion"])}</span></p>')
    if adj and adj.get("hint"):
        parts.append(f"<p>Hint: {esc(adj['hint'])}</p>")
    note = f" {md(res['note'])}" if res.get("note") else ""
    commit = f" <code>{esc(res['commit'])}</code>" if res.get("commit") else ""
    parts.append(f'<p class="resolution">{tag(RESOLUTION_LABELS.get(status, status))}{note}{commit}</p>')
    if key and status not in ("open", "owner"):
        reopens = esc(d.get("id", ""))
        parts.append(
            f'<button type="button" class="reopen" data-key="{esc(key)}" data-reopens="{reopens}">Reopen</button>'
        )
    return f'<div class="ec status-{esc(status)}" data-comment="{esc(d.get("id", ""))}">{"".join(parts)}</div>'


def element_html(e: Element, since: Since | None) -> str:
    mark = since.marks.get(e.target) if since and e.fp is not None else None
    classes = f"el depth-{min(e.depth, 3)} kind-{e.kind}" + (f" {mark}" if mark else "")
    mark_html = f' <span class="mark">{"changed" if mark == "changed" else "new"}</span>' if mark else ""
    earlier = ""
    if since and e.fp is not None and since.by_target.get(e.target):
        items = "".join(comment_html(d, e.key) for d in since.by_target[e.target])
        earlier = f'<div class="earlier"><h4>Earlier comments</h4>{items}</div>'
    return (
        f'<article class="{classes}" id="{anchor(e.key)}" data-key="{esc(e.key)}" data-counted="{int(e.counted)}">'
        f'<header class="el-head"><span class="el-label">{esc(e.label)}{mark_html}</span>'
        f'<code class="el-target">{esc(e.target)}</code></header>'
        f'<div class="el-body">{e.body}</div>{earlier}<div class="el-review" data-key="{esc(e.key)}"></div></article>'
    )


def _section_id(s: Section) -> str:
    return "s-" + hashlib.sha1((s.file or s.title).encode("utf-8")).hexdigest()[:8]


def section_html(s: Section, since: Since | None) -> str:
    sid = _section_id(s)
    meta = []
    if s.file:
        meta.append(f"<code>{esc(s.file)}</code>")
    if s.status:
        meta.append(esc(s.status))
    out = [f'<section class="file" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{esc(s.title)}</h2>']
    if meta:
        out.append(f'<p class="section-meta">{" · ".join(meta)}</p>')
    for entry in s.entries:
        if isinstance(entry, Heading):
            out.append(f"<h{entry.level}>{esc(entry.text)}</h{entry.level}>")
        else:
            out.append(element_html(entry, since))
    out.append("</section>")
    return "\n".join(out)


def toc_html(model: PageModel) -> str:
    out, group = [], None
    for s in model.sections:
        if s.group != group:
            if group is not None:
                out.append("</ul>")
            group = s.group
            out.append(f'<p class="group">{esc(group)}</p><ul>')
        n = sum(1 for e in s.elements if e.counted)
        out.append(f'<li><a href="#{_section_id(s)}">{esc(s.title)}</a> <span class="count">{n}</span></li>')
    if group is not None:
        out.append("</ul>")
    return "\n".join(out)


HOW_TO = (
    "<p>Give every element a verdict: <strong>✓ OK</strong>, <strong>✎ Change</strong> or "
    "<strong>? Question</strong>. For a change or a question, pick a category, write a comment and, if you like, "
    "the Italian you would use. Your comments are saved in this browser as you type. When you're done, or whenever "
    "you want to send what you have, press <strong>Download my review</strong> and send the file to the project "
    "owner. When nothing is open any more, <strong>Sign off</strong>.</p>"
)
PATTERNS_LEGEND = (
    "<p>Answer patterns: <code>{a|b}</code> means a or b, <code>(…)</code> is optional, <code>[…]</code> is checked "
    "strictly (no typos allowed; underlined in the answers), <code>{NAME}</code> is the learner's name. The first "
    "answer is the model answer learners are shown.</p>"
)


def intro_html(model: PageModel, since: Since | None, open_entries: list[Entry]) -> str:
    files = "".join(
        f"<li><code>{esc(f)}</code> <span class='small'>{esc(h[:12])}</span></li>" for f, h in model.files.items()
    )
    parts = ['<div class="intro-box">', HOW_TO, PATTERNS_LEGEND]
    if since is not None:
        n_changed = sum(1 for v in since.marks.values() if v == "changed")
        n_new = sum(1 for v in since.marks.values() if v == "new")
        n_earlier = sum(len(v) for v in since.by_target.values())
        base = ", ".join(since.baseline[-1:]) or "no earlier review with element fingerprints"
        parts.append(
            f"<p>Since your last review ({esc(base)}): {n_changed} changed and {n_new} new elements are marked; "
            f"{n_earlier} earlier comments are shown with what was done about them. Choose “changed” under Show to see "
            "only those. You can reopen any comment.</p>"
        )
    if open_entries:
        parts.append(
            f'<p class="banner warn">{len(open_entries)} earlier comment(s) on these files are still open in the '
            "project, so you can't sign off yet.</p>"
        )
    parts.append(
        f'<details><summary>Files on this page ({len(model.files)})</summary><ul class="files">{files}</ul></details>'
    )
    parts.append("</div>")
    return "".join(parts)


def orphans_html(since: Since | None) -> str:
    if not since or not since.orphans:
        return ""
    items = "".join(f"<p><code>{esc(d.get('target'))}</code></p>{comment_html(d, None)}" for d in since.orphans)
    return f'<section class="file"><h2>Earlier comments on elements that are gone</h2>{items}</section>'


def page_data(model: PageModel, open_entries: list[Entry], since: Since | None) -> dict[str, Any]:
    elements = []
    for e in model.elements():
        item: dict[str, Any] = {
            "key": e.key,
            "target": e.target,
            "file": e.file,
            "quote": e.quote,
            "fp": e.fp,
            "counted": e.counted,
        }
        if e.meta.get("adjudicate"):
            item["adj"] = {k: v for k, v in e.meta.items() if k != "adjudicate"}
        elements.append(item)
    page_id = hashlib.sha256(json.dumps([model.scope, model.files], sort_keys=True).encode()).hexdigest()[:12]
    return {
        "format": 1,
        "scope": model.scope,
        "pageId": page_id,
        "files": model.files,
        "categories": [[k, v] for k, v in CATEGORIES.items()],
        "elements": elements,
        "open": [{"id": e.id, "target": e.data.get("target"), "status": e.status} for e in open_entries],
        "since": since is not None,
    }


def _embed(data: dict[str, Any]) -> str:
    """JSON inside <script type="application/json">: `<` escaped so no text can end the element."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")


def audio_data(audio: ReviewAudio | None) -> str:
    """The embedded audio files: `{audio ID: base64 of the .m4a}` (the page script plays them from `data:` URIs)."""
    files = audio.files if audio else {}
    return json.dumps({k: base64.b64encode(v).decode("ascii") for k, v in sorted(files.items())}, sort_keys=True)


def render_page(
    model: PageModel,
    *,
    since: Since | None = None,
    open_entries: list[Entry] | None = None,
    audio: ReviewAudio | None = None,
) -> str:
    open_entries = open_entries or []
    template = (TEMPLATES / "page.html").read_text(encoding="utf-8")
    total = sum(1 for e in model.elements() if e.counted)
    main = "\n".join(section_html(s, since) for s in model.sections) + orphans_html(since)
    changed_filter = '<label><input type="radio" name="filter" value="changed"> changed since my last review</label>'
    values = {
        "TITLE": esc(f"Review · {model.title}"),
        "HEADING": esc(model.title),
        "SCOPE": esc(f"{scope_title(model.scope)} · scope {model.scope}"),
        "TOTAL": str(total),
        "CHANGED_FILTER": changed_filter if since is not None else "",
        "TOC": toc_html(model),
        "INTRO": intro_html(model, since, open_entries),
        "MAIN": main,
        "SIGNOFF_FILES": "".join(f"<li><code>{esc(f)}</code></li>" for f in model.files),
        "DATA": _embed(page_data(model, open_entries, since)),
        "AUDIO": audio_data(audio),
        "CSS": (TEMPLATES / "page.css").read_text(encoding="utf-8").strip(),
        "JS": (TEMPLATES / "page.js").read_text(encoding="utf-8").strip(),
    }
    return re.sub(r"@@([A-Z_]+)@@", lambda m: values[m.group(1)], template)


# ---------------------------------------------------------------- the command


@dataclass
class ExportResult:
    path: Path
    model: PageModel
    since: Since | None
    adjudications: int
    audio: ReviewAudio | None = None

    def summary(self, root: Path) -> str:
        els = self.model.elements()
        try:
            shown = self.path.relative_to(root).as_posix()
        except ValueError:
            shown = str(self.path)
        out = (
            f"wrote {shown}: {len(els)} elements ({sum(e.counted for e in els)} to review) "
            f"from {len(self.model.files)} file(s)"
        )
        if self.adjudications:
            out += f"; {self.adjudications} answer(s) to adjudicate"
        if self.audio is not None and self.audio.files:
            out += f"; {len(self.audio.files)} audio file(s) embedded"
        if self.audio is not None and self.audio.note:
            out += f"; {self.audio.note}"
        if self.since is not None:
            marks = list(self.since.marks.values())
            earlier = sum(len(v) for v in self.since.by_target.values())
            out += f"; since: {marks.count('changed')} changed, {marks.count('new')} new, {earlier} earlier comment(s)"
        return out


def export(
    scope: str,
    *,
    root: Path | None = None,
    since: bool = False,
    rejected: Path | None = None,
    out: Path | None = None,
    expander: Expander | None = None,
    audio: ReviewAudio | None = None,
) -> ExportResult:
    """Write the review page for `scope` and return what was written. `expander` defaults to the grader's
    (`itcontent.patterns.expand`); `audio` to what `content build` would bundle for the scope (`review_audio`); tests
    may pass others."""
    root = (root or paths.ROOT).resolve()
    course = load_course(root)
    if audio is None:
        audio = page_audio(root, course, scope)
    ctx = Context.build(course, expander=expander, audio=audio.ref)
    model = build_page(ctx, scope)
    ledger_entries = entries(root)
    adj = adjudication_section(ctx, rejected_answers(rejected, scope, [e.data for e in ledger_entries]))
    if adj is not None:
        model.sections.insert(0, adj)
    open_entries = [e for e in ledger_entries if e.unresolved and e.data.get("file") in model.files]

    def exists(target: str) -> bool:
        return target_problem(course, ctx.index, target) is None

    info = since_info(root, model, ledger_entries, exists) if since else None
    path = out or root / "build" / "review" / scope / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_page(model, since=info, open_entries=open_entries, audio=audio), encoding="utf-8")
    return ExportResult(path, model, info, len(adj.elements) if adj else 0, audio)
