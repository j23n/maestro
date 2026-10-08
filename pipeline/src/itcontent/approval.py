"""Approval of content files (docs/03 § Review status and approval, docs/04 § Approval hash, ADR-15).

`review.hash` is the sha256 of the file's bytes after normalising line endings to LF and removing the top-level
`review:` entry: its line and its indented continuation lines (blank lines and column-0 comments between them count
as part of the entry; trailing ones don't). So the hash covers everything except the approval itself, in flow style
(`review: {status: draft, …}`) and block style alike.

`content approve` and `content reopen` rewrite only the `review:` entry (in the style it was written) and keep every
other byte. They are for humans: they refuse when stdin is not a terminal or `CLAUDECODE` is set, and ask the person
to type the file name to confirm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from itcontent import paths, yamlio
from itcontent.findings import Finding, make

REVIEW_KEY = re.compile(rb"^review[ \t]*:")
clock: Callable[[], dt.date] = dt.date.today  # injectable: tests and the CLI's callers may replace it


class ApprovalError(Exception):
    """Why approve/reopen can't proceed; the message is for the person at the terminal."""


# ---------------------------------------------------------------- the hash


def normalise(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def review_span(lines: list[bytes]) -> tuple[int, int] | None:
    """[start, end) indexes of the top-level `review:` entry in `lines` (line endings already removed)."""
    for i, line in enumerate(lines):
        if REVIEW_KEY.match(line):
            end = i + 1
            for j in range(i + 1, len(lines)):
                cur = lines[j]
                if cur[:1] in (b" ", b"\t") and cur.strip():
                    end = j + 1  # an indented continuation line (a key, a wrapped flow mapping, an indented comment)
                elif cur.strip() and not cur.startswith(b"#"):
                    break  # the next top-level key
            return i, end
    return None


def strip_review(data: bytes) -> bytes:
    lines = normalise(data).split(b"\n")
    span = review_span(lines)
    if span is None:
        return b"\n".join(lines)
    start, end = span
    return b"\n".join(lines[:start] + lines[end:])


def approval_hash(data: bytes) -> str:
    return hashlib.sha256(strip_review(data)).hexdigest()


def file_hash(path: Path) -> str:
    return approval_hash(path.read_bytes())


# ---------------------------------------------------------------- rewriting the review entry


def _scalar(value: str | None, *, bare: bool = False) -> str:
    if value is None:
        return "null"
    return value if bare else json.dumps(value, ensure_ascii=False)  # a JSON string is a YAML double-quoted scalar


def render_review(
    review: Mapping[str, str | None], *, flow: bool, indent: bytes = b"  ", eol: bytes = b"\n"
) -> list[bytes]:
    fields = [("status", _scalar(review["status"], bare=True))]
    fields += [(k, _scalar(review.get(k))) for k in ("by", "date", "hash")]
    if flow:
        body = ", ".join(f"{k}: {v}" for k, v in fields)
        return [f"review: {{{body}}}".encode() + eol]
    return [b"review:" + eol] + [indent + f"{k}: {v}".encode() + eol for k, v in fields]


def set_review(path: Path, review: Mapping[str, str | None]) -> None:
    """Replace the top-level `review:` entry of `path` with `review`, keeping every other byte."""
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    span = review_span([ln.rstrip(b"\r\n") for ln in lines])
    if span is None:
        raise ApprovalError(f"{path.name} has no top-level review: entry")
    start, end = span
    old = lines[start:end]
    eol = b"\r\n" if old[0].endswith(b"\r\n") else b"\n"
    flow = b"{" in old[0]
    indent = b"  "
    for ln in old[1:]:
        m = re.match(rb"^([ \t]+)\S", ln)
        if m:
            indent = m.group(1)
            break
    new = render_review(review, flow=flow, indent=indent, eol=eol)
    if not old[-1].endswith((b"\n", b"\r")) and end == len(lines):
        new[-1] = new[-1].rstrip(b"\r\n")  # the entry ended the file without a newline: keep it that way
    path.write_bytes(b"".join(lines[:start] + new + lines[end:]))


def read_review(path: Path) -> dict[str, Any] | None:
    data = yamlio.load(path)
    review = data.get("review") if isinstance(data, dict) else None
    return review if isinstance(review, dict) else None


# ---------------------------------------------------------------- humans only


def agent_refusal(env: Mapping[str, str] | None = None, stdin: TextIO | None = None) -> str | None:
    """Why this process may not approve or reopen (ADR-15), or None for a person at a terminal."""
    env = os.environ if env is None else env
    stdin = sys.stdin if stdin is None else stdin
    if "CLAUDECODE" in env:
        return (
            "refused: CLAUDECODE is set, so this is an agent's shell. Only the owner approves or reopens content "
            "(ADR-15); ask them to run the command in their own terminal."
        )
    try:
        tty = stdin.isatty()
    except (AttributeError, ValueError):
        tty = False
    if not tty:
        return (
            "refused: stdin is not a terminal. Approving and reopening content is for a person at a terminal (ADR-15)."
        )
    return None


def resolve_file(root: Path, file: Path) -> tuple[Path, str]:
    """The content file named on the command line (relative to the cwd or the repo root) and its repo path."""
    candidates = [file] if file.is_absolute() else [Path.cwd() / file, root / file]
    for c in candidates:
        if not c.is_file():
            continue
        path = c.resolve()
        try:
            rel = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue  # a file of another checkout: never touch it
        if rel.startswith("content/") and path.suffix == ".yaml":
            return path, rel
        raise ApprovalError(f"{rel} is not a content YAML file")
    raise ApprovalError(f"{file}: no such file under {root}/content")


def _confirm(ask: Callable[[str], str], path: Path, rel: str, action: str) -> bool:
    answer = ask(f"{action} {rel}? Type the file name ({path.name}) to confirm").strip()
    return answer in (path.name, rel)


def _lint_errors(root: Path, rel: str) -> list[Finding]:
    from itcontent.lint import lint_findings  # lint uses this module for hash checks

    return [f for f in lint_findings(root) if f.level == "error" and (f.file == rel or rel in f.related)]


def _check_errors(root: Path, rel: str) -> list[Finding]:
    from itcontent.checks import check_errors_for  # the checks read lint's line lookup; import late

    return list(check_errors_for(root, rel))


def approve(
    file: Path,
    by: str,
    *,
    root: Path | None = None,
    signoff: Path | None = None,
    today: Callable[[], dt.date] | None = None,
    ask: Callable[[str], str] = input,
    echo: Callable[[str], Any] = print,
    env: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
) -> int:
    """`content approve <file> --by "<name>"`: set status approved, by, date and hash. Returns the exit status."""
    refusal = agent_refusal(env, stdin)
    if refusal:
        echo(refusal)
        return 1
    root = (root or paths.ROOT).resolve()
    try:
        path, rel = resolve_file(root, file)
        name = by.strip()
        if not name:
            raise ApprovalError('--by needs the content lead\'s name, e.g. --by "Maria Rossi"')
        review = read_review(path)
        if review is None:
            raise ApprovalError(f"{rel} has no review: entry, so it isn't approved content (docs/03)")
        if review.get("status") == "approved":
            raise ApprovalError(
                f"{rel} is already approved (by {review.get('by')}, {review.get('date')}); reopen it first"
            )
        if signoff is not None:
            # docs/04 § Content review loop › Back into the project, step 5: the teacher signed exactly this version,
            # and no ledger comment on the file is still open.
            from itcontent.ledger import signoff_problems

            problems = signoff_problems(root, rel, signoff, name)
            if problems:
                for p in problems:
                    echo(p)
                raise ApprovalError(f"{rel}: the sign-off doesn't allow approval ({len(problems)} problem(s))")
        errors = _lint_errors(root, rel)
        if errors:
            for f in errors:
                echo(str(f))
            raise ApprovalError(f"{rel} fails lint ({len(errors)} error(s)); fix them before approving")
        failed = _check_errors(root, rel)
        if failed:
            for f in failed:
                echo(str(f))
            raise ApprovalError(f"{rel} fails content check ({len(failed)} error(s)); fix them before approving")
        if not _confirm(ask, path, rel, f'Approve as reviewed by "{name}":'):
            raise ApprovalError("not confirmed; nothing changed")
        digest = file_hash(path)
        date = (today or clock)().isoformat()
        set_review(path, {"status": "approved", "by": name, "date": date, "hash": digest})
        if file_hash(path) != digest or (read_review(path) or {}).get("hash") != digest:
            raise ApprovalError(f"{rel}: the rewritten review entry doesn't verify; restore the file from git")
    except (ApprovalError, yamlio.ContentYAMLError) as exc:
        echo(str(exc))
        return 1
    echo(f"approved {rel}: by {name}, {date}, hash {digest}")
    return 0


def reopen(
    file: Path,
    *,
    root: Path | None = None,
    ask: Callable[[str], str] = input,
    echo: Callable[[str], Any] = print,
    env: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
) -> int:
    """`content reopen <file>`: set status in-review and clear by, date and hash. Returns the exit status."""
    refusal = agent_refusal(env, stdin)
    if refusal:
        echo(refusal)
        return 1
    root = (root or paths.ROOT).resolve()
    try:
        path, rel = resolve_file(root, file)
        review = read_review(path)
        if review is None:
            raise ApprovalError(f"{rel} has no review: entry")
        if not _confirm(ask, path, rel, "Reopen (set back to in-review)"):
            raise ApprovalError("not confirmed; nothing changed")
        set_review(path, {"status": "in-review", "by": None, "date": None, "hash": None})
    except (ApprovalError, yamlio.ContentYAMLError) as exc:
        echo(str(exc))
        return 1
    echo(f"reopened {rel}: status in-review")
    return 0


# ---------------------------------------------------------------- lint


def check_approvals(root: Path, docs: Mapping[str, Any]) -> list[Finding]:
    """An approved file whose hash doesn't match was edited after approval (docs/04 § Approval hash)."""
    out = []
    for rel, data in sorted(docs.items()):
        review = data.get("review") if isinstance(data, dict) and rel.startswith("content/") else None
        if not isinstance(review, dict) or review.get("status") != "approved":
            continue
        stored = review.get("hash")
        if not isinstance(stored, str):
            continue  # the schema reports a missing hash
        actual = file_hash(root / rel)
        if actual != stored:
            out.append(
                make(
                    "error",
                    rel,
                    ("review", "hash"),
                    f"the file changed after approval: review.hash is {stored[:12]}…, the file now hashes to "
                    f"{actual[:12]}… (docs/04 § Approval hash). Approved content changes only after the owner runs "
                    "content reopen",
                )
            )
    return out
