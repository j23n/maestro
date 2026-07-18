"""The pack review tool (`maestro-pack review`) — plan §10, full build.

A local web app over the working tree: git is the database, item status
lives in the YAML. Workflows (plan §10, audit item B3):

1. Review queue over EVERY item family, rendered as the learner will
   see it, with media previews (audio players, images).
2. Context panel: the spec cell's own material (grammar examples and
   explanation, function patterns) plus live validator warnings sit
   beside the item.
3. Coverage matrix: grammar point × item family against targets, the
   per-cell ``generate`` invocation one copy away.
4. Release diff: working tree vs the last released bundle
   (added / changed / removed / tombstoned).
5. L1-reviewer mode (``/?mode=l1``): read-only pass over reviewed
   items; flagging with a comment flips them back into the queue.
6. Keyboard-first triage: a=accept e=edit r=reject d=defer.

Plain HTML forms with a sprinkle of inline JS for the shortcuts; the
tool only rewrites files it acts on.

Run: ``maestro-pack review`` (port 8321).
"""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from authoring.build_pack import validate_pack
from authoring.pack_schemas import (
    DrillItem,
    GrammarRefItem,
    ListeningItem,
    ReadingItem,
    SpeakingPromptItem,
    VocabCardItem,
    WritingPromptItem,
)
from authoring.spec_schemas import Spec
from authoring.validate_spec import load_spec

# id prefix -> (source subdir, model). The registry the whole tool runs on.
FAMILIES: dict[str, tuple[str, type]] = {
    "drill": ("drills", DrillItem),
    "reading": ("readings", ReadingItem),
    "listening": ("listenings", ListeningItem),
    "vocab": ("vocab", VocabCardItem),
    "speaking": ("speaking_prompts", SpeakingPromptItem),
    "writing": ("writing_prompts", WritingPromptItem),
    "grammar_ref": ("grammar_refs", GrammarRefItem),
}

COVERAGE_TARGETS = {"drill": 30, "vocab_card": 5, "grammar_ref": 1}

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>maestro-pack review</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 72rem;
        margin: 2rem auto; padding: 0 1rem; }}
 .cols {{ display: flex; gap: 1.5rem; align-items: flex-start; }}
 .cols > div {{ flex: 1; min-width: 0; }}
 .item {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem;
         margin: 1rem 0; }}
 .draft {{ border-left: 4px solid #e6a700; }}
 .flagged {{ border-left: 4px solid #d33; }}
 .context {{ background: #f7f5f0; border-radius: 8px; padding: 1rem;
            font-size: 14px; }}
 .warn {{ background: #fff3cd; padding: .3rem .6rem; border-radius: 6px;
         margin: .2rem 0; font-size: 14px; }}
 textarea {{ width: 100%; min-height: 16rem; font: 13px/1.4 monospace; }}
 .answer {{ color: #0a7a0a; }} .feedback {{ color: #666; }}
 table {{ border-collapse: collapse; }} td, th {{ padding: 2px 10px;
         text-align: left; }}
 .thin {{ background: #fee; }}
 .error {{ background: #fee; padding: .5rem 1rem; border-radius: 6px; }}
 img.preview {{ max-width: 16rem; border-radius: 8px; display: block; }}
 nav a {{ margin-right: 1rem; }}
 code {{ background: #eee; padding: 0 4px; border-radius: 4px; }}
 kbd {{ background:#333;color:#fff;border-radius:3px;padding:0 5px; }}
</style></head><body>
<nav><a href="/">queue</a><a href="/coverage">coverage</a>
<a href="/release-diff">release diff</a><a href="/?mode=l1">L1 mode</a></nav>
{body}
<script>
document.addEventListener('keydown', (e) => {{
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  const act = {{a: 'accept', r: 'reject'}}[e.key];
  if (act) {{
    const b = document.querySelector(`button[value=${{act}}]`);
    if (b) b.click();
  }}
  if (e.key === 'e') {{
    const t = document.querySelector('textarea'); if (t) t.focus(), e.preventDefault();
  }}
  if (e.key === 'd') {{
    const n = document.getElementById('defer'); if (n) n.click();
  }}
}});
</script></body></html>"""


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _media_tag(pack_dir: Path, ref: str | None, kind: str) -> str:
    if not ref or not (pack_dir / ref).is_file():
        return ""
    if kind == "audio":
        return f'<audio controls preload="none" src="/media/{_esc(ref)}"></audio>'
    return f'<img class="preview" src="/media/{_esc(ref)}">'


def _render_preview(entry: dict, pack_dir: Path) -> str:
    """Learner-eye rendering, per item family."""
    prefix = entry.get("id", "").split(".", 1)[0]
    out: list[str] = []

    def answers_list(answers):
        return "".join(
            f"<li class=answer>{_esc(a['text'])}"
            f"{' (canonical)' if a.get('canonical') else ''}</li>"
            for a in answers or []
        )

    if prefix == "drill":
        if entry.get("choices"):
            out.append("<p>choices: " + ", ".join(map(_esc, entry["choices"])) + "</p>")
        out.append(f"<p><b>{_esc(entry.get('prompt'))}</b></p>")
        out.append(f"<ul>{answers_list(entry.get('answers'))}</ul>")
        out.append(
            "<ul>"
            + "".join(
                f"<li class=feedback>«{_esc(k)}» → {_esc(v)}</li>"
                for k, v in (entry.get("distractor_feedback") or {}).items()
            )
            + "</ul>"
        )
    elif prefix == "reading":
        out.append(f"<p><b>{_esc(entry.get('title'))}</b></p>")
        out.append(_media_tag(pack_dir, entry.get("image"), "image"))
        out.append(f"<p>{_esc(entry.get('text'))}</p>")
        for w, g in (entry.get("glossary") or {}).items():
            out.append(f"<p class=feedback>{_esc(w)} = {_esc(g)}</p>")
    elif prefix == "listening":
        out.append(f"<p><b>{_esc(entry.get('title'))}</b></p>")
        for t in entry.get("turns", []):
            out.append(
                f"<p>{_esc(t.get('speaker'))}: {_esc(t.get('text'))} "
                + _media_tag(pack_dir, t.get("audio"), "audio")
                + "</p>"
            )
    elif prefix == "vocab":
        out.append(_media_tag(pack_dir, entry.get("image"), "image"))
        out.append(
            f"<p><b>{_esc(entry.get('front'))}</b> "
            + _media_tag(pack_dir, entry.get("audio"), "audio")
            + f" — {_esc(entry.get('back'))}</p>"
        )
        if entry.get("example"):
            out.append(
                f"<p class=feedback>{_esc(entry['example'])} — "
                f"{_esc(entry.get('example_gloss'))}</p>"
            )
    elif prefix == "speaking":
        out.append(f"<p><b>{_esc(entry.get('prompt'))}</b></p>")
        out.append(
            f"<p class=answer>target: {_esc(entry.get('target_text'))} "
            + _media_tag(pack_dir, entry.get("audio"), "audio")
            + "</p>"
        )
        for v in entry.get("variants", []):
            out.append(f"<p class=answer>variant: {_esc(v)}</p>")
    elif prefix == "writing":
        out.append(f"<p><b>{_esc(entry.get('prompt'))}</b></p>")
        out.append(
            f"<p class=feedback>rubric: ≥{_esc(entry.get('min_words'))} words; "
            f"grammar {_esc(', '.join(entry.get('required_grammar') or []))}; "
            f"vocab {_esc(', '.join(entry.get('required_vocab') or []))}</p>"
        )
        if entry.get("model_answer"):
            out.append(f"<p class=feedback>model: {_esc(entry['model_answer'])}</p>")
    elif prefix == "grammar_ref":
        out.append(f"<p><b>{_esc(entry.get('title'))}</b></p>")
        out.append(
            f"<pre style='white-space:pre-wrap'>{_esc(entry.get('body_md'))}</pre>"
        )
        for e in entry.get("examples", []):
            out.append(f"<p class=answer>{_esc(e)}</p>")

    # Common tail: passage questions + explanation.
    for n, q in enumerate(entry.get("questions") or [], 1):
        out.append(
            f"<p>q{n}: {_esc(q.get('prompt'))}</p><ul>{answers_list(q.get('answers'))}</ul>"
        )
    if entry.get("explanation"):
        out.append(f"<p class=feedback>{_esc(entry['explanation'])}</p>")
    if entry.get("review_note"):
        out.append(f"<p class=warn>reviewer note: {_esc(entry['review_note'])}</p>")
    return "".join(out)


def _render_context(entry: dict, spec: Spec) -> str:
    """The spec cell's own material beside the item (plan §10.2)."""
    import re as _re

    parts: list[str] = ["<h3>Spec context</h3>"]
    gp_by_id = {g.id: g for g in spec.grammar_points}
    cf_by_id = {c.id: c for c in spec.communicative_functions}
    vocab_by_id = {v.id: v for v in spec.vocab}
    for ev in entry.get("evidence", []):
        eid = ev.get("id")
        if ev.get("axis") == "grammar" and eid in gp_by_id:
            g = gp_by_id[eid]
            parts.append(
                f"<p><b>{_esc(g.id)}</b> ({_esc(g.cefr_level)}) — {_esc(g.label)}</p>"
            )
            if g.description:
                parts.append(f"<p>{_esc(g.description)}</p>")
            for ex in g.examples[:4]:
                parts.append(f"<p class=answer>{_esc(_re.sub(r'<[^>]+>', '', ex))}</p>")
            en = g.explanations.get("en")
            if en and en.title:
                parts.append(f"<p class=feedback>ref page: {_esc(en.title)}</p>")
        elif ev.get("axis") == "function" and eid in cf_by_id:
            c = cf_by_id[eid]
            parts.append(
                f"<p><b>{_esc(c.id)}</b> ({_esc(c.cefr_level)}) — {_esc(c.label)}</p>"
            )
            for p in c.patterns[:4]:
                parts.append(f"<p class=answer>{_esc(p)}</p>")
            for ex in c.examples[:3]:
                parts.append(f"<p class=feedback>{_esc(ex)}</p>")
        elif ev.get("axis") == "vocab" and eid in vocab_by_id:
            v = vocab_by_id[eid]
            parts.append(
                f"<p><b>{_esc(v.id)}</b> ({_esc(v.cefr_level)}, {_esc(v.pos)}) = {_esc(v.gloss)}</p>"
            )
    return (
        "".join(parts)
        if len(parts) > 1
        else parts[0] + "<p>(no resolvable evidence)</p>"
    )


def create_app(
    pack_dir: Path | str = Path("packs/it"),
    spec_dir: Path | str | None = None,
) -> FastAPI:
    pack_dir = Path(pack_dir)
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    spec_dir = Path(spec_dir) if spec_dir else Path("spec") / lang
    app = FastAPI(title="maestro-pack review")

    state: dict = {}

    def spec() -> Spec:
        if "spec" not in state:
            state["spec"] = load_spec(spec_dir)
        return state["spec"]

    def load_all() -> list[tuple[Path, list[dict]]]:
        out = []
        for subdir, _model in FAMILIES.values():
            for f in sorted((pack_dir / subdir).glob("*.yaml")):
                out.append((f, yaml.safe_load(f.read_text()) or []))
        return out

    def find_item(item_id: str) -> tuple[Path, list[dict], dict] | None:
        for f, entries in load_all():
            for e in entries:
                if e.get("id") == item_id:
                    return f, entries, e
        return None

    def model_for(item_id: str) -> type:
        return FAMILIES[item_id.split(".", 1)[0]][1]

    def save_file(path: Path, entries: list[dict]) -> None:
        if entries:
            path.write_text(
                yaml.dump(entries, allow_unicode=True, sort_keys=False, width=88),
                encoding="utf-8",
            )
        else:
            path.unlink()

    def quality_warnings(entry: dict) -> list[str]:
        try:
            from authoring.quality import Lemmatizer, validate_quality

            if "lemmatizer" not in state:
                state["lemmatizer"] = Lemmatizer()
            item = model_for(entry["id"])(**entry)
            per_item = validate_quality([item], spec(), state["lemmatizer"])
            return per_item.get(entry["id"], [])
        except Exception as exc:  # never block review on a checker crash
            return [f"(quality checks unavailable: {exc})"]

    def queue_ids(mode: str) -> list[str]:
        wanted = ("reviewed",) if mode == "l1" else ("draft", "flagged")
        ids = []
        for _f, entries in load_all():
            ids += [e["id"] for e in entries if e.get("status", "reviewed") in wanted]
        return ids

    @app.get("/", response_class=HTMLResponse)
    def queue(mode: str = "") -> str:
        counts: dict[str, int] = {}
        rows = []
        for _f, entries in load_all():
            for e in entries:
                status = e.get("status", "reviewed")
                counts[status] = counts.get(status, 0) + 1
                show = (
                    status == "reviewed"
                    if mode == "l1"
                    else status in ("draft", "flagged")
                )
                if show:
                    href = f"/item/{e['id']}" + ("?mode=l1" if mode == "l1" else "")
                    rows.append(
                        f'<div class="item {status}"><a href="{href}">'
                        f"{e['id']}</a> [{status}]{_render_preview(e, pack_dir)}</div>"
                    )
        summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "empty"
        title = "L1 review (read-only + flag)" if mode == "l1" else "Review queue"
        empty = (
            "<p>Queue empty 🎉</p>" if mode != "l1" else "<p>Nothing reviewed yet.</p>"
        )
        return _PAGE.format(
            body=f"<h1>{title}</h1><p>{summary}</p>"
            f"<p>keys: <kbd>a</kbd> accept · <kbd>e</kbd> edit · "
            f"<kbd>r</kbd> reject · <kbd>d</kbd> defer</p>"
            f"{''.join(rows) or empty}"
        )

    @app.get("/coverage", response_class=HTMLResponse)
    def coverage() -> str:
        from authoring.build_pack import coverage_report, load_pack_sources

        sources = load_pack_sources(pack_dir)
        report = coverage_report(sources.all_items(), spec())
        kinds = [
            "drill",
            "reading",
            "listening",
            "vocab_card",
            "speaking_prompt",
            "writing_prompt",
            "grammar_ref",
        ]
        head = "".join(f"<th>{k}</th>" for k in kinds)
        rows = []
        for gp_id, data in sorted(
            report["grammar_points"].items(),
            key=lambda kv: (kv[1]["cefr_level"], kv[0]),
        ):
            if data["cefr_level"] not in ("A0", "A1", "A2"):
                continue
            cells = []
            thin = False
            for k in kinds:
                n = data["counts"].get(k, 0)
                target = COVERAGE_TARGETS.get(k)
                is_thin = target is not None and n < target
                thin = thin or is_thin
                cells.append(f"<td class={'thin' if is_thin else 'ok'}>{n}</td>")
            gen = _esc(
                f"uv run python -m authoring.cli generate --gp {gp_id} --count 10"
            )
            rows.append(
                f"<tr><td>{gp_id}</td><td>{data['cefr_level']}</td>"
                + "".join(cells)
                + (f"<td><code>{gen}</code></td>" if thin else "<td></td>")
                + "</tr>"
            )
        return _PAGE.format(
            body="<h1>Coverage (A0–A2 grammar × item family)</h1>"
            f"<p>targets: drill ≥{COVERAGE_TARGETS['drill']}, vocab_card "
            f"≥{COVERAGE_TARGETS['vocab_card']}, grammar_ref ≥1; thin cells "
            "carry their generate command.</p>"
            f"<table><tr><th>grammar</th><th>lvl</th>{head}<th></th></tr>"
            + "".join(rows)
            + "</table>"
        )

    @app.get("/release-diff", response_class=HTMLResponse)
    def release_diff_view() -> str:
        from authoring.release import latest_release, release_diff

        released = latest_release(Path("build/release"), lang)
        if released is None:
            return _PAGE.format(
                body="<h1>Release diff</h1><p>No release found under "
                "<code>build/release/</code> — run "
                "<code>maestro-pack release</code> first.</p>"
            )
        diff = release_diff(pack_dir, spec_dir, released)
        body = [f"<h1>Release diff vs {_esc(released.name)}</h1>"]
        for section in ("added", "changed", "removed", "tombstoned"):
            ids = diff[section]
            body.append(f"<h2>{section} ({len(ids)})</h2>")
            body.append("".join(f"<p><code>{_esc(i)}</code></p>" for i in ids))
        if diff["removed"]:
            body.append(
                "<p class=warn>removed ids MUST be tombstoned before release "
                "(packs/&lt;lang&gt;/tombstones.yaml).</p>"
            )
        return _PAGE.format(body="".join(body))

    @app.get("/media/{path:path}")
    def media(path: str):
        target = (pack_dir / path).resolve()
        if not str(target).startswith(str(pack_dir.resolve())) or not target.is_file():
            return HTMLResponse("not found", status_code=404)
        return FileResponse(target)

    @app.get("/item/{item_id}", response_class=HTMLResponse)
    def edit(item_id: str, error: str = "", mode: str = "") -> str:
        found = find_item(item_id)
        if not found:
            return _PAGE.format(
                body=f"<p class=error>no such item: {_esc(item_id)}</p>"
            )
        _f, _entries, entry = found
        warns = "".join(f"<p class=warn>{_esc(w)}</p>" for w in quality_warnings(entry))
        err_html = f'<p class="error">{_esc(error)}</p>' if error else ""
        ids = queue_ids(mode)
        nxt = (
            ids[(ids.index(item_id) + 1) % len(ids)]
            if item_id in ids and len(ids) > 1
            else None
        )
        defer = (
            f'<a id=defer href="/item/{nxt}{"?mode=l1" if mode == "l1" else ""}">defer →</a>'
            if nxt
            else ""
        )

        if mode == "l1":
            form = (
                f'<form method=post action="/flag/{item_id}">'
                "<p><input name=note placeholder='what is wrong?' size=60> "
                "<button>⚑ flag for maintainer</button></p></form>"
            )
        else:
            raw = yaml.dump([entry], allow_unicode=True, sort_keys=False, width=88)
            form = (
                f'<h2>Source</h2><form method=post action="/item/{item_id}">'
                f"<textarea name=source>{_esc(raw)}</textarea><p>"
                f"<button name=action value=accept>✓ accept</button> "
                f"<button name=action value=save>save draft</button> "
                f"<button name=action value=reject>✗ reject</button> "
                f"{defer}</p></form>"
            )
        return _PAGE.format(
            body=f"<h1>{item_id}</h1>{err_html}"
            f"<div class=cols><div><h2>As the learner sees it</h2>"
            f"{_render_preview(entry, pack_dir)}{warns}{form}</div>"
            f"<div class=context>{_render_context(entry, spec())}</div></div>"
        )

    @app.post("/flag/{item_id}")
    def flag(item_id: str, note: str = Form("")):
        found = find_item(item_id)
        if found:
            path, entries, entry = found
            entry["status"] = "flagged"
            entry["review_note"] = note or "flagged by L1 reviewer"
            save_file(path, entries)
        return RedirectResponse("/?mode=l1", status_code=303)

    @app.post("/item/{item_id}")
    def act(item_id: str, action: str = Form(...), source: str = Form("")):
        found = find_item(item_id)
        if not found:
            return RedirectResponse("/", status_code=303)
        path, entries, entry = found
        idx = entries.index(entry)
        if action == "reject":
            entries.pop(idx)
            save_file(path, entries)
            return RedirectResponse("/", status_code=303)
        try:
            parsed = yaml.safe_load(source)
            if not isinstance(parsed, list) or len(parsed) != 1:
                raise ValueError("source must be a single-item YAML list")
            updated = parsed[0]
            updated["status"] = "reviewed" if action == "accept" else "draft"
            if action == "accept":
                updated.pop("review_note", None)
            item = model_for(item_id)(**updated)
            errors = validate_pack([item], spec())
            # Duplicate-id errors against self don't apply here; check refs only.
            errors = [e for e in errors if "duplicate" not in e]
            if errors:
                raise ValueError("; ".join(errors))
        except Exception as exc:  # surface anything to the reviewer
            return RedirectResponse(
                f"/item/{item_id}?error={quote(str(exc))}", status_code=303
            )
        entries[idx] = {
            k: v
            for k, v in yaml.safe_load(item.model_dump_json()).items()
            if v not in (None, [], {})
        }
        save_file(path, entries)
        return RedirectResponse("/", status_code=303)

    return app
