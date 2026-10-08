"""Shared pieces of the pack builder: errors, the build report and deterministic JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class BuildError(Exception):
    """A problem that stops the build. The message names the file, the YAML path or the ID concerned."""


@dataclass
class Report:
    """Warnings and notes collected during a build (errors raise `BuildError` instead)."""

    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


def cjson(value: Any) -> str:
    """Compact, deterministic JSON for pack columns: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    """Readable, deterministic JSON for committed fixtures (sorted keys, one-space indent, trailing newline)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def mapping(x: Any) -> dict[str, Any]:
    """A mapping, or {} for anything else (lint reports malformed data; the builder must not crash on it)."""
    return x if isinstance(x, dict) else {}


def seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def opt_str(x: Any) -> str | None:
    return x if isinstance(x, str) and x != "" else None
