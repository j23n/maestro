"""The pack review tool (`maestro-pack review`) — plan §10, Phase 2 slice.

A local web app over the working tree: git is the database, item status
lives in the YAML. This slice implements the review queue (learner-eye
rendering + raw YAML editing, accept / save / reject), status counts,
and the coverage view. Plain HTML forms — no JS required; htmx sugar can
come later. Only files under ``packs/<lang>/drills/`` are rewritten, and
only when an action is taken on an item in them.

Run: ``uvicorn 'authoring.review:create_app' --factory`` or
``maestro-pack review``.
"""

from __future__ import annotations

import html
from pathlib import Path

import yaml
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from authoring.build_pack import validate_pack
from authoring.pack_schemas import DrillItem
from authoring.spec_schemas import Spec
from authoring.validate_spec import load_spec

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>maestro-pack review</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 60rem;
        margin: 2rem auto; padding: 0 1rem; }}
 .item {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem;
         margin: 1rem 0; }}
 .draft {{ border-left: 4px solid #e6a700; }}
 .flagged {{ border-left: 4px solid #d33; }}
 textarea {{ width: 100%; min-height: 16rem; font: 13px/1.4 monospace; }}
 .answer {{ color: #0a7a0a; }} .feedback {{ color: #666; }}
 table {{ border-collapse: collapse; }} td, th {{ padding: 2px 10px;
         text-align: left; }}
 .error {{ background: #fee; padding: .5rem 1rem; border-radius: 6px; }}
</style></head><body><a href="/">← queue</a>{body}</body></html>"""


def _load_files(drills_dir: Path) -> dict[Path, list[dict]]:
    return {
        f: yaml.safe_load(f.read_text()) or []
        for f in sorted(drills_dir.glob("*.yaml"))
    }


def _render_preview(entry: dict) -> str:
    answers = "".join(
        f"<li class=answer>{html.escape(a['text'])}"
        f"{' (canonical)' if a.get('canonical') else ''}</li>"
        for a in entry.get("answers", [])
    )
    feedback = "".join(
        f"<li class=feedback>«{html.escape(k)}» → {html.escape(v)}</li>"
        for k, v in (entry.get("distractor_feedback") or {}).items()
    )
    choices = ""
    if entry.get("choices"):
        choices = (
            "<p>choices: " + ", ".join(map(html.escape, entry["choices"])) + "</p>"
        )
    return (
        f"<p><b>{html.escape(entry.get('prompt', ''))}</b></p>{choices}"
        f"<ul>{answers}</ul><ul>{feedback}</ul>"
        f"<p class=feedback>{html.escape(entry.get('explanation') or '')}</p>"
    )


def create_app(
    pack_dir: Path | str = Path("packs/it"),
    spec_dir: Path | str | None = None,
) -> FastAPI:
    pack_dir = Path(pack_dir)
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    spec_dir = Path(spec_dir) if spec_dir else Path("spec") / lang
    drills_dir = pack_dir / "drills"
    app = FastAPI(title="maestro-pack review")

    def spec() -> Spec:
        return load_spec(spec_dir)

    def find_item(item_id: str) -> tuple[Path, list[dict], dict] | None:
        for f, entries in _load_files(drills_dir).items():
            for e in entries:
                if e.get("id") == item_id:
                    return f, entries, e
        return None

    def save_file(path: Path, entries: list[dict]) -> None:
        if entries:
            path.write_text(
                yaml.dump(entries, allow_unicode=True, sort_keys=False, width=88),
                encoding="utf-8",
            )
        else:
            path.unlink()

    @app.get("/", response_class=HTMLResponse)
    def queue() -> str:
        counts: dict[str, int] = {}
        rows = []
        coverage: dict[str, int] = {}
        for _f, entries in _load_files(drills_dir).items():
            for e in entries:
                status = e.get("status", "reviewed")
                counts[status] = counts.get(status, 0) + 1
                if status in ("draft", "flagged"):
                    rows.append(
                        f'<div class="item {status}"><a href="/item/{e["id"]}">'
                        f"{e['id']}</a> [{status}]{_render_preview(e)}</div>"
                    )
                else:
                    for ev in e.get("evidence", []):
                        if ev.get("axis") == "grammar":
                            coverage[ev["id"]] = coverage.get(ev["id"], 0) + 1
        cov_rows = "".join(
            f"<tr><td>{gp}</td><td>{n}</td><td>{'▮' * min(n, 30)}</td></tr>"
            for gp, n in sorted(coverage.items())
        )
        summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "empty"
        return _PAGE.format(
            body=f"<h1>Review queue</h1><p>{summary}</p>{''.join(rows) or '<p>Queue empty 🎉</p>'}"
            f"<h2>Coverage (reviewed drills per grammar point, target 30)</h2>"
            f"<table><tr><th>grammar</th><th>items</th><th></th></tr>{cov_rows}</table>"
        )

    @app.get("/item/{item_id}", response_class=HTMLResponse)
    def edit(item_id: str, error: str = "") -> str:
        found = find_item(item_id)
        if not found:
            return _PAGE.format(
                body=f"<p class=error>no such item: {html.escape(item_id)}</p>"
            )
        _f, _entries, entry = found
        raw = yaml.dump([entry], allow_unicode=True, sort_keys=False, width=88)
        err_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        return _PAGE.format(
            body=f"<h1>{item_id}</h1>{err_html}"
            f"<h2>As the learner sees it</h2>{_render_preview(entry)}"
            f'<h2>Source</h2><form method=post action="/item/{item_id}">'
            f"<textarea name=source>{html.escape(raw)}</textarea><p>"
            f"<button name=action value=accept>✓ accept</button> "
            f"<button name=action value=save>save draft</button> "
            f"<button name=action value=reject>✗ reject</button></p></form>"
        )

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
            item = DrillItem(**updated)
            errors = validate_pack([item], spec())
            # Duplicate-id errors against self don't apply here; check refs only.
            errors = [e for e in errors if "duplicate" not in e]
            if errors:
                raise ValueError("; ".join(errors))
        except Exception as exc:  # surface anything to the reviewer
            from urllib.parse import quote

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
