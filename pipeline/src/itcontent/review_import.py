"""`content review-import <review.json>` (docs/04 § Content review loop › Back into the project, task M1.13).

1. Read the review file (from a review page or the app) and validate it (`schemas/review-file.schema.json`).
2. Check every comment's target resolves (and that its file exists); any unknown target stops the import, because
   the teacher's comment would otherwise be filed against nothing. Don't guess targets: tell the owner.
3. File the review unchanged in `reviews/inbox/` (the teacher's words; agents never edit them).
4. Append its comments to the ledger `reviews/<scope>.yaml`: every field as filed, plus `review` (the inbox copy),
   `reviewer`, `hash` (the version the teacher saw), `stale` (that version isn't the current one) and
   `resolution: {status: open}`. An OK verdict with nothing to act on is filed as `noted`. Comments already in a
   ledger (the same `id`) are not filed twice.
5. Write the answer-key proposals of the scope's open adjudications (`adjudication`) to
   `build/reports/review/<scope>-answers.{md,json}` and print the worklist.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths, schemas
from itcontent.adjudication import Proposal, proposals, write_proposals
from itcontent.course import load_course
from itcontent.index import build_index
from itcontent.ledger import append, entries, ledger_rel, load_ledger, make_entry
from itcontent.review import (
    CATEGORIES,
    VERDICTS,
    load_json,
    scope_files,
    target_file,
    target_problem,
    version_hash,
)
from itcontent.review_elements import Context, build_page


class ReviewImportError(Exception):
    """Why the review can't be imported; nothing was written."""


@dataclass
class ImportResult:
    inbox: str
    ledger: str
    scope: str
    added: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    reports: list[Path] = field(default_factory=list)
    changed_elements: set[str] = field(default_factory=set)


def initial_status(c: dict[str, Any]) -> str:
    """`noted` for an OK verdict with nothing to act on (no comment, no suggestion: e.g. an element marked OK, or a
    rejected answer adjudicated as wrong); everything else starts `open`."""
    has_text = any(str(c.get(k) or "").strip() for k in ("comment", "suggestion"))
    return "noted" if c.get("verdict") == "ok" and not has_text else "open"


def inbox_name(root: Path, source: Path, raw: bytes) -> tuple[str, bool]:
    """(repo path in reviews/inbox/, already filed). Names keep the download's name, made safe for the ledger."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-.") or "review"
    inbox = root / "reviews" / "inbox"
    n = 1
    while True:
        name = f"{stem}.json" if n == 1 else f"{stem}-{n}.json"
        path = inbox / name
        if not path.exists():
            return f"reviews/inbox/{name}", False
        if path.read_bytes() == raw:
            return f"reviews/inbox/{name}", True
        n += 1


def import_review(source: Path, *, root: Path | None = None, reports: Path | None = None) -> ImportResult:
    """Import one review file. Raises ReviewImportError (and writes nothing) for a malformed file or unknown targets."""
    root = (root or paths.ROOT).resolve()
    if not source.is_file():
        raise ReviewImportError(f"{source}: no such file")
    raw = source.read_bytes()
    data, problem = load_json(source)
    if problem:
        raise ReviewImportError(problem)
    invalid = schemas.validate("review-file", data)
    if invalid:
        lines = [f"  {'.'.join(map(str, p)) or '(top)'}: {m}" for p, m in invalid]
        raise ReviewImportError(f"{source.name} is not a valid review file:\n" + "\n".join(lines))
    scope = data["scope"]
    course = load_course(root)
    index = build_index(course)
    if re.fullmatch(r"u\d{2}", scope) and course.unit(scope) is None:
        raise ReviewImportError(f"{source.name}: scope {scope} is not a unit in content/course.yaml")
    errors, warnings = [], []
    in_scope = set(scope_files(course, scope))
    for i, c in enumerate(data["comments"]):
        where = f"comments[{i}] ({c['id']})"
        problem = target_problem(course, index, c["target"])
        if problem:
            errors.append(f"{where}: {problem}")
            continue
        if not (root / c["file"]).is_file():
            errors.append(f"{where}: {c['file']} doesn't exist")
            continue
        actual = target_file(course, index, c["target"])
        if actual and actual != c["file"]:
            warnings.append(f"{where}: {c['target']} is in {actual}, but the comment names {c['file']}")
        if c["file"] not in in_scope:
            warnings.append(f"{where}: {c['file']} is outside scope {scope}; filed in {ledger_rel(scope)} anyway")
    if errors:
        raise ReviewImportError(
            f"{source.name}: {len(errors)} comment(s) name targets that don't exist; nothing was imported. "
            "Ask the owner; don't guess the target.\n" + "\n".join(f"  {e}" for e in errors)
        )
    inbox, already = inbox_name(root, source, raw)
    result = ImportResult(inbox, ledger_rel(scope), scope, warnings=warnings)
    known = {e.id: e for e in entries(root)}
    current = {rel: version_hash(root, rel) for rel in {c["file"] for c in data["comments"]}}
    seen_fp = data.get("elements") if isinstance(data.get("elements"), dict) else {}
    if seen_fp:
        now = {e.target: e.fp for e in build_page(Context.build(course), scope).elements()}
        result.changed_elements = {t for t, fp in seen_fp.items() if t in now and now[t] != fp}
    new_entries = []
    for c in data["comments"]:
        if c["id"] in known:
            result.skipped.append(c["id"])
            if known[c["id"]].data.get("review") != inbox:
                same = all(known[c["id"]].data.get(k) == v for k, v in c.items())
                if not same:
                    result.warnings.append(
                        f"comment {c['id']} is already in {known[c['id']].ledger} with different content; "
                        "not filed again"
                    )
            continue
        seen = data["files"].get(c["file"])
        stale = seen is not None and seen != current.get(c["file"])
        entry = make_entry(
            c,
            review=inbox,
            reviewer=data["reviewer"],
            hash=seen,
            stale=stale,
            resolution={"status": initial_status(c), "note": None, "commit": None},
        )
        new_entries.append(entry)
        result.added.append(dict(entry))
    if not already:
        dst = root / inbox
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dst)
    if new_entries or not (root / ledger_rel(scope)).is_file():
        append(root, scope, new_entries)
    ledger = load_ledger(root, scope)
    result.proposals = proposals(course, [c for c in ledger.get("comments", []) if isinstance(c, dict)])
    if result.proposals:
        result.reports = write_proposals(reports or root / "build" / "reports" / "review", scope, result.proposals)
    return result


def _clip(text: Any, n: int = 90) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def worklist(result: ImportResult, root: Path) -> list[str]:
    """What the agent works through next (docs/04 § Back into the project)."""
    todo = [e for e in result.added if e["resolution"]["status"] == "open"]
    noted = len(result.added) - len(todo)
    lines = [
        f"filed {result.inbox}; {len(result.added)} comment(s) added to {result.ledger} "
        f"({len(todo)} to do, {noted} marked OK)" + (f"; {len(result.skipped)} already filed" if result.skipped else "")
    ]
    lines += [f"warning: {w}" for w in result.warnings]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for e in todo:
        by_file.setdefault(str(e["file"]), []).append(e)
    for file in sorted(by_file):
        lines.append(file)
        for e in by_file[file]:
            kind = VERDICTS.get(str(e.get("verdict")), str(e.get("verdict")))
            if e.get("category"):
                kind += f" · {CATEGORIES.get(str(e['category']), e['category'])}"
            adj = e.get("adjudication")
            if isinstance(adj, dict):
                kind = f"adjudication: {adj.get('decision')}"
            flags = []
            if e.get("stale"):
                changed = e["target"] in result.changed_elements
                flags.append("stale: the file changed since" + ("; so did this element" if changed else ""))
            if e.get("reopens"):
                flags.append(f"reopens {e['reopens']}")
            text = _clip(e.get("comment") or "")
            if e.get("suggestion"):
                text += f" → {_clip(e['suggestion'], 60)}"
            if e.get("response"):
                text += f" [answer: {_clip(e['response'], 60)}]"
            flag = f" ({'; '.join(flags)})" if flags else ""
            text = text.strip() or _clip(e.get("quote"))
            lines.append(f"  - {e['target']} [{kind}]{flag}: {text}  ({e['id']})")
    if result.proposals:
        shown = ", ".join(str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in result.reports)
        n = sum(1 for p in result.proposals if p.action in ("replace", "append", "add-near"))
        lines.append(f"answer key: {n} change(s) to apply, {len(result.proposals)} decision(s) in all → {shown}")
    return lines


def run(source: Path, *, root: Path | None = None, echo: Callable[[str], Any] = print) -> int:
    root = (root or paths.ROOT).resolve()
    try:
        result = import_review(source, root=root)
    except ReviewImportError as exc:
        echo(f"error: {exc}")
        return 1
    for line in worklist(result, root):
        echo(line)
    return 0
