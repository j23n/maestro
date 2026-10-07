"""`content lint` (docs/04 § Commands). M0.4 scope: YAML parse (ruamel, YAML 1.2) and ID format.

Later tasks add JSON Schemas (M1.1), references, uniqueness, ids.lock and approval hashes (M1.2), and ledgers (M1.13).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itcontent import ids, paths, yamlio


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning | pending
    file: str
    where: str
    message: str

    def __str__(self) -> str:
        loc = f"{self.file}{(' › ' + self.where) if self.where else ''}"
        return f"{self.level}: {loc}: {self.message}"


def content_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "content").rglob("*.yaml") if ".annotations" not in p.parts)


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
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (("." if out else "") + str(p))
    return out


def check_id_formats(rel: str, doc: Any) -> list[Finding]:
    findings = []
    for path, value in _walk_ids(doc, []):
        if ids.kind_of(value) is None:
            findings.append(Finding("error", rel, _fmt_path(path), f"ID '{value}' has no valid format (docs/03 § IDs)"))
    return findings


def run_lint(root: Path | None = None, *, echo=print) -> int:
    root = root or paths.ROOT
    findings: list[Finding] = []
    for f in content_files(root):
        rel = f.relative_to(root).as_posix()
        try:
            doc = yamlio.load(f)
        except yamlio.ContentYAMLError as exc:
            findings.append(Finding("error", rel, "", str(exc)))
            continue
        findings.extend(check_id_formats(rel, doc))
    errors = [x for x in findings if x.level == "error"]
    for x in findings:
        echo(str(x))
    echo(f"lint: {len(errors)} error(s), {len(findings) - len(errors)} other finding(s)")
    return 1 if errors else 0
