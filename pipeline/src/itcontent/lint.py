"""`content lint` (docs/04 § Commands): YAML parse, JSON Schemas, ID formats, uniqueness and references (with the
pending/error rule), `ids.lock` stability, approval hashes and review ledgers.

Output is one line per finding, `error|warning|pending: <file> › <path> (line N): <message>`, sorted, then a summary
line; `--json` prints the same findings as JSON. Any error makes the exit status 1.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from itcontent import ids, paths, schemas, yamlio
from itcontent.findings import Finding, PathT, format_path, make


def content_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "content").rglob("*.yaml") if ".annotations" not in p.parts)


def review_files(root: Path) -> list[Path]:
    """Review ledgers (`reviews/<scope>.yaml`) and filed review files (`reviews/inbox/*.json`)."""
    reviews = root / "reviews"
    return sorted([*reviews.glob("*.yaml"), *(reviews / "inbox").glob("*.json")])


# ---------------------------------------------------------------- M0.4 API, kept for callers


def _walk_ids(node: Any, path: list[str | int]) -> Iterator[tuple[list[str | int], str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "id" and isinstance(v, str):
                yield [*path, k], v
            yield from _walk_ids(v, [*path, k])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_ids(v, [*path, i])


def _fmt_path(path: list[str | int]) -> str:
    return format_path(tuple(path))


def check_id_formats(rel: str, doc: Any) -> list[Finding]:
    """Every `id:` value has some valid format. `lint` checks the exact kind per field through the schemas."""
    findings = []
    for path, value in _walk_ids(doc, []):
        if ids.kind_of(value) is None:
            findings.append(make("error", rel, tuple(path), f"ID '{value}' has no valid format (docs/03 § IDs)"))
    return findings


# ---------------------------------------------------------------- loading and line numbers


class Lines:
    """1-based line numbers for findings, from a round-trip load of each file (on demand, cached)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._docs: dict[str, Any] = {}

    def __call__(self, rel: str, path: PathT) -> int | None:
        if not path:
            return None
        if rel not in self._docs:
            p = self.root / rel
            try:
                self._docs[rel] = _roundtrip(p) if p.suffix in (".yaml", ".json") else None
            except Exception:
                self._docs[rel] = None
        doc = self._docs[rel]
        if doc is None:
            return None
        return yamlio.locate(doc, list(path)) or 1


# Parses keyed by file text: lint never mutates them, and repeated runs (tests, approve) see mostly the same files.
_parsed: dict[str, Any] = {}
_roundtrips: dict[str, Any] = {}


def _parse_yaml(p: Path) -> Any:
    text = p.read_text(encoding="utf-8")
    if text not in _parsed:
        if len(_parsed) > 512:
            _parsed.clear()
        _parsed[text] = yamlio.loads(text, str(p))
    return copy.deepcopy(_parsed[text])


def _roundtrip(p: Path) -> Any:
    text = p.read_text(encoding="utf-8")
    if text not in _roundtrips:
        if len(_roundtrips) > 512:
            _roundtrips.clear()
        _roundtrips[text] = yamlio.load_roundtrip(p)
    return _roundtrips[text]


def load_file(root: Path, p: Path) -> tuple[Any, Finding | None]:
    rel = p.relative_to(root).as_posix()
    try:
        if p.suffix == ".json":
            return json.loads(p.read_text(encoding="utf-8")), None
        return _parse_yaml(p), None
    except yamlio.ContentYAMLError as exc:
        return None, make("error", rel, (), f"does not parse: {exc.problem}", line=exc.line)
    except json.JSONDecodeError as exc:
        return None, make("error", rel, (), f"does not parse: {exc.msg}", line=exc.lineno)
    except UnicodeDecodeError as exc:
        return None, make("error", rel, (), f"is not UTF-8 ({exc.reason})")


def schema_findings(rel: str, data: Any) -> list[Finding]:
    """Schema problems for one loaded file (or a warning when no schema maps to its path)."""
    name = schemas.schema_for(rel)
    if name is None:
        return [make("warning", rel, (), "no schema covers this file; is it in the right place? (docs/03 § Files)")]
    if data is None:
        return [make("error", rel, (), f"the file is empty (expected a {name} document)")]
    return [make("error", rel, path, msg) for path, msg in schemas.validate(name, data)]


# ---------------------------------------------------------------- the command


def lint_findings(root: Path | None = None) -> list[Finding]:
    """Every finding for the repository at `root`, sorted, with line numbers."""
    root = (root or paths.ROOT).resolve()
    lines = Lines(root)
    findings: list[Finding] = []
    docs: dict[str, Any] = {}
    for p in [*content_files(root), *review_files(root)]:
        rel = p.relative_to(root).as_posix()
        data, problem = load_file(root, p)
        if problem:
            findings.append(problem)
            continue
        docs[rel] = data
        findings.extend(schema_findings(rel, data))
    if not (root / "content" / "course.yaml").is_file():
        findings.append(make("error", "content/course.yaml", (), "is missing: the course can't be loaded"))
    out = []
    for f in set(findings):
        if f.line is None and f.path is not None:
            f = Finding(f.level, f.file, f.where, f.message, lines(f.file, f.path), f.path, f.related)
        out.append(f)
    return sorted(out, key=Finding.sort_key)


def summary(findings: list[Finding]) -> dict[str, int]:
    return {level: sum(1 for f in findings if f.level == level) for level in ("error", "warning", "pending")}


def run_lint(root: Path | None = None, *, echo: Callable[[str], Any] | None = print, as_json: bool = False) -> int:
    """Print the findings (text or JSON) and return the exit status: 1 on any error."""
    findings = lint_findings(root)
    counts = summary(findings)
    if echo is not None:
        if as_json:
            echo(json.dumps({"summary": counts, "findings": [f.as_dict() for f in findings]}, indent=2))
        else:
            for f in findings:
                echo(str(f))
            echo(f"lint: {counts['error']} error(s), {counts['warning']} warning(s), {counts['pending']} pending")
    return 1 if counts["error"] else 0
