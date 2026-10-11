"""Review ledgers `reviews/<scope>.yaml` (docs/04 § Content review loop › The review file, schema
`schemas/review-ledger.schema.json`): every comment of every imported review file, as filed, plus where it came from
(`review`), whether it was made on an older version (`stale`) and what was done about it (`resolution`).

`content review-import` appends to a ledger; agents fill in resolutions (docs/04 § Back into the project); comments are
never deleted or merged. This module also answers the two questions the rest of the loop asks of the ledgers: which
comments are still unresolved (sign-off, `content approve --signoff`, `content report`), and whether a teacher's
sign-off allows a file to be approved.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString

from itcontent import approval, schemas, yamlio
from itcontent.review import CATEGORIES, UNRESOLVED, VERDICTS, load_json, unit_of_comment

# The order of an entry's keys: the comment as filed, then the ledger's own fields.
COMMENT_KEYS = (
    "id",
    "target",
    "file",
    "quote",
    "verdict",
    "category",
    "comment",
    "suggestion",
    "response",
    "adjudication",
    "reopens",
    "at",
)
LEDGER_KEYS = ("review", "reviewer", "hash", "stale", "resolution")


def ledger_rel(scope: str) -> str:
    return f"reviews/{scope}.yaml"


def ledger_paths(root: Path) -> list[Path]:
    return sorted((root / "reviews").glob("*.yaml"))


def load_ledger(root: Path, scope: str) -> dict[str, Any]:
    path = root / ledger_rel(scope)
    if not path.is_file():
        return {"scope": scope, "comments": []}
    data = yamlio.load(path)
    return data if isinstance(data, dict) else {"scope": scope, "comments": []}


@dataclass(frozen=True)
class Entry:
    """One ledger comment and where it is."""

    ledger: str  # reviews/u02.yaml
    index: int
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))

    @property
    def status(self) -> str:
        res = self.data.get("resolution")
        return str(res.get("status")) if isinstance(res, dict) else "open"

    @property
    def unresolved(self) -> bool:
        return self.status in UNRESOLVED


def entries(root: Path) -> list[Entry]:
    """Every comment of every ledger (ledgers that don't parse are lint's to report)."""
    out = []
    for path in ledger_paths(root):
        try:
            data = yamlio.load(path)
        except yamlio.ContentYAMLError:
            continue
        comments = data.get("comments") if isinstance(data, dict) else None
        for i, c in enumerate(comments if isinstance(comments, list) else []):
            if isinstance(c, dict):
                out.append(Entry(path.relative_to(root).as_posix(), i, c))
    return out


def unresolved(root: Path, files: Iterable[str] | None = None) -> list[Entry]:
    """Open (and owner) comments, optionally only those on `files`."""
    wanted = set(files) if files is not None else None
    return [e for e in entries(root) if e.unresolved and (wanted is None or e.data.get("file") in wanted)]


# ---------------------------------------------------------------- writing


def _yaml() -> YAML:
    y = YAML(typ="rt", pure=True)
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.representer.add_representer(type(None), lambda r, _d: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def _scalar(value: Any) -> Any:
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value)
    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = _scalar(v)
        return m
    return value


def make_entry(comment: dict[str, Any], **ledger_fields: Any) -> CommentedMap:
    """A ledger entry: the comment's fields as filed (in schema order), then review, reviewer, hash, stale,
    resolution (a flow mapping, so agents edit one line)."""
    m = CommentedMap()
    for k in COMMENT_KEYS:
        if k in comment:
            m[k] = _scalar(comment[k])
    for k in comment:
        if k not in m:
            m[k] = _scalar(comment[k])  # unknown keys can't pass the schema; kept so nothing is lost
    for k in LEDGER_KEYS:
        if k in ledger_fields:
            m[k] = _scalar(ledger_fields[k])
    res = m.get("resolution")
    if isinstance(res, CommentedMap):
        res.fa.set_flow_style()
    return m


HEADER = (
    "# Review ledger for {scope} (docs/04 § Content review loop). content review-import appends every comment of\n"
    "# every review file; agents record each comment's resolution (open | fixed | answered | declined | owner;\n"
    "# noted = marked OK, nothing to do). Never delete or merge comments.\n"
)


def append(root: Path, scope: str, new: list[CommentedMap]) -> Path:
    """Append entries to `reviews/<scope>.yaml` (created if missing), keeping the rest of the file as it is."""
    path = root / ledger_rel(scope)
    y = _yaml()
    if path.is_file():
        doc = y.load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, CommentedMap):
            raise ValueError(f"{ledger_rel(scope)} is not a ledger mapping")
        if not isinstance(doc.get("comments"), CommentedSeq):
            doc["comments"] = CommentedSeq()
        prefix = ""
    else:
        doc = CommentedMap()
        doc["scope"] = scope
        doc["comments"] = CommentedSeq()
        prefix = HEADER.format(scope=scope)
    doc["comments"].extend(new)
    buf = io.StringIO()
    y.dump(doc, buf)
    text = prefix + buf.getvalue()
    problems = schemas.validate("review-ledger", yamlio.loads(text, ledger_rel(scope)))
    if problems:
        raise ValueError(f"{ledger_rel(scope)} would not validate: {problems[:3]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- sign-off (content approve --signoff)


def _resolve(root: Path, path: Path) -> Path | None:
    for c in [path] if path.is_absolute() else [Path.cwd() / path, root / path]:
        if c.is_file():
            return c.resolve()
    return None


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def signoff_problems(root: Path, rel: str, signoff: Path, by: str) -> list[str]:
    """Why the teacher's sign-off doesn't allow approving `rel` (docs/04 § Back into the project, step 5); [] if it
    does. The sign-off must be a filed review (reviews/inbox/), signed by `by`, cover `rel` at its current approval
    hash, and no ledger may have an open or owner comment on `rel`."""
    root = root.resolve()
    path = _resolve(root, signoff)
    if path is None:
        return [f"{signoff}: no such review file"]
    try:
        filed = path.relative_to(root).as_posix()
    except ValueError:
        filed = ""
    if not re.fullmatch(r"reviews/inbox/[^/\s]+\.json", filed):
        return [
            f"{signoff}: import the review first (uv run content review-import {signoff}), "
            "then pass its copy in reviews/inbox/"
        ]
    data, problem = load_json(path)
    if problem:
        return [problem]
    invalid = schemas.validate("review-file", data)
    if invalid:
        return [f"{filed}: not a valid review file ({'; '.join(m for _, m in invalid[:3])})"]
    block = data.get("signoff")
    if not isinstance(block, dict):
        return [f"{filed} has no sign-off: the teacher signs off on the review page when no comment is open"]
    problems = []
    if not _same_name(str(block.get("name", "")), by):
        problems.append(f'--by "{by}" doesn\'t match the sign-off, which is by "{block.get("name")}"')
    signed = block.get("files", {}).get(rel)
    if signed is None:
        problems.append(f"the sign-off in {filed} doesn't cover {rel}")
    else:
        current = approval.file_hash(root / rel)
        if signed != current:
            problems.append(
                f"stale sign-off: {block.get('name')} signed {rel} at hash {signed[:12]}…, but the file now hashes to "
                f"{current[:12]}…; export the review page again and ask for a new sign-off"
            )
    still_open = unresolved(root, [rel])
    if still_open:
        listing = ", ".join(f"{e.id} ({e.status}, {e.ledger})" for e in still_open[:5])
        more = f" and {len(still_open) - 5} more" if len(still_open) > 5 else ""
        problems.append(f"{len(still_open)} comment(s) on {rel} are still open: {listing}{more}")
    return problems


# ---------------------------------------------------------------- content report: open comments


def report_lines(root: Path, unit: str | None = None) -> list[str]:
    """The "Open review comments" section of `content report` (docs/04): unresolved comments per unit."""
    by_unit: dict[str, list[Entry]] = {}
    for e in unresolved(root):
        u = unit_of_comment(str(e.data.get("target", "")), e.data.get("file"))
        if unit is None or u == unit:
            by_unit.setdefault(u, []).append(e)
    total = sum(len(v) for v in by_unit.values())
    lines = ["## Open review comments", ""]
    if not total:
        lines.append(f"No open review comments{f' for {unit}' if unit else ''}.")
        return lines
    lines.append(f"{total} open comment(s) (status open or owner) in reviews/*.yaml.")
    for u in sorted(by_unit):
        lines += ["", f"### {u} ({len(by_unit[u])})", ""]
        for e in sorted(by_unit[u], key=lambda x: (str(x.data.get("file")), str(x.data.get("target")), x.id)):
            d = e.data
            kind = VERDICTS.get(str(d.get("verdict")), str(d.get("verdict")))
            if d.get("category"):
                kind += f" · {CATEGORIES.get(str(d['category']), d['category'])}"
            text = " ".join(str(d.get("comment") or d.get("response") or d.get("quote") or "").split())
            if len(text) > 100:
                text = text[:99] + "…"
            owner = " **owner**" if e.status == "owner" else ""
            stale = " (stale)" if d.get("stale") else ""
            lines.append(f"- `{d.get('target')}` {kind}{owner}{stale}: {text} — {e.ledger} `{e.id}`")
    return lines
