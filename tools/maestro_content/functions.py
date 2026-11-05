"""Communicative functions: what people do with language (invite, accept, ask the price), HANDOFF.md 3.9.

The inventory is content/<lang>/functions.yaml: a `functions:` list of flat `key: value` entries, read
without a YAML library like the grammar base. Each function has

    id       stable short ID (invite); German IDs get the de: prefix, which the file doesn't carry
    level    the first level that uses it, A1 to B2
    name     what the learner does, in English, as the drills show it ("Inviting someone")
    goal     the same as a role-play goal ("Invite Sara", without the name: "Invite")
    label    the function's name in the language (invitare)
    source   where the inventory takes it from (the Profilo della lingua italiana, Profile deutsch)
    phrases  a small bank of ways to say it, separated by " | "

Sentences in a text carry functions with `@fn invite` after the sentence. The bank gives role-plays
their wrong replies (a phrase of another function) and "You could also say".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .grammar import id_prefix

LEVELS = ("A1", "A2", "B1", "B2")


@dataclass
class Function:
    id: str
    level: str
    name: str
    goal: str
    label: str
    source: str = ""
    phrases: list[str] = field(default_factory=list)


def load(path: str, language: str = "it") -> dict[str, Function]:
    """The inventory by ID; empty when the file is missing."""
    if not os.path.exists(path):
        return {}
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#") or line == "functions:":
                continue
            if line.startswith("- "):
                if current is not None:
                    entries.append(current)
                current = {}
                line = "  " + line[2:]
            if current is None or not line.startswith("  ") or ":" not in line:
                raise ValueError(f"{path}:{n}: expected '  key: value'")
            key, _, value = line.strip().partition(":")
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            current[key] = value
    if current is not None:
        entries.append(current)
    prefix = id_prefix(language)
    out: dict[str, Function] = {}
    for e in entries:
        missing = [k for k in ("id", "level", "name", "goal", "label") if k not in e]
        if missing:
            raise ValueError(f"{path}: function {e.get('id', '?')} is missing {', '.join(missing)}")
        fid = prefix + e["id"]
        if fid in out:
            raise ValueError(f"{path}: duplicate function {fid}")
        if e["level"] not in LEVELS:
            raise ValueError(f"{path}: function {fid} has level {e['level']!r}")
        phrases = [p.strip() for p in e.get("phrases", "").split("|") if p.strip()]
        out[fid] = Function(fid, e["level"], e["name"], e["goal"], e["label"], e.get("source", ""), phrases)
    return out


def default_path(content_dir: str, language: str) -> str:
    return os.path.join(content_dir, language, "functions.yaml")
