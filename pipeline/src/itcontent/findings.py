"""Lint findings: what `content lint` reports, one line each (docs/04 § Commands)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEVELS = ("error", "warning", "pending")

PathT = tuple[str | int, ...]


def format_path(path: PathT) -> str:
    """('steps', 3, 'block', 0) → 'steps[3].block[0]' (the same style as `course.Loc`)."""
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (("." if out else "") + str(p))
    return out


@dataclass(frozen=True)
class Finding:
    """One finding. `where` is the YAML path as text; `path` keeps it as keys for line lookup and sorting."""

    level: str  # error | warning | pending
    file: str  # repo-relative path
    where: str
    message: str
    line: int | None = None
    path: PathT = ()
    related: tuple[str, ...] = field(default=(), compare=False)  # other files the finding is about

    def __str__(self) -> str:
        loc = f"{self.file}{(' › ' + self.where) if self.where else ''}"
        line = f" (line {self.line})" if self.line else ""
        return f"{self.level}: {loc}{line}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "file": self.file,
            "path": self.where,
            "keys": list(self.path),
            "line": self.line,
            "message": self.message,
        }

    def sort_key(self) -> tuple[Any, ...]:
        keys = tuple((0, p, "") if isinstance(p, int) else (1, 0, str(p)) for p in self.path)
        return (self.file, self.line or 0, keys, LEVELS.index(self.level), self.message)


def make(level: str, file: str, path: PathT, message: str, *, line: int | None = None, related=()) -> Finding:
    return Finding(level, file, format_path(path), message, line, tuple(path), tuple(related))
