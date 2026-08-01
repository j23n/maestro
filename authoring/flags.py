"""Learner problem reports: read them, resolve them against the sources.

The app writes an `item_flagged` event whenever a learner reports a broken
item, and exports those events as JSONL (``maestro-flags.jsonl``, header
``{"maestro_flags":1}``). This module is the receiving end: it reads that
file, pairs each report with the pack source it names, and prints the
report next to the item so the complaint can be judged without hunting.

Reviewing is non-destructive by default. ``--apply`` is the opt-in that
marks the reported items ``status: flagged`` — which takes them out of the
next build, so it stays a deliberate act.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_HEADER = {"maestro_flags": 1}
# Passage questions are generated at build time as `<parent>.q<n>`; they
# have no entry of their own in the sources.
_QUESTION_SUFFIX = re.compile(r"\.q\d+$")


@dataclass
class Flag:
    """One report, as exported by the app."""

    item_id: str
    note: str
    pack_version: str | None = None
    at: int | None = None

    @property
    def when(self) -> str:
        if self.at is None:
            return "unknown date"
        import datetime

        return datetime.datetime.fromtimestamp(
            self.at, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d")


@dataclass
class Resolved:
    """A reported item paired with whatever the sources know about it."""

    item_id: str
    flags: list[Flag] = field(default_factory=list)
    entry: dict | None = None
    path: Path | None = None
    # Set when the id is a build-time question sub-item: the maintainer
    # needs to edit the parent passage, not this id.
    parent_id: str | None = None
    tombstoned_in: str | None = None

    @property
    def status(self) -> str:
        if self.tombstoned_in:
            return f"removed in {self.tombstoned_in}"
        if self.parent_id:
            return f"question of {self.parent_id}"
        if self.entry is not None:
            return self.entry.get("status", "reviewed")
        return "not in pack sources"


class FlagFileError(ValueError):
    """The file isn't a flag export."""


def load_flags(path: Path) -> list[Flag]:
    """Parse an exported flag file. Rejects a backup by its header, so a
    learner log can't be imported here by accident."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise FlagFileError(f"{path}: empty file")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise FlagFileError(f"{path}: first line is not JSON ({exc})") from exc
    if header != _HEADER:
        hint = ""
        if "maestro_export" in header:
            hint = " — that's a full backup (export_log), not a flag export"
        raise FlagFileError(f"{path}: unexpected header {header!r}{hint}")

    flags: list[Flag] = []
    for n, line in enumerate(lines[1:], start=2):
        try:
            envelope = json.loads(line)
            payload = envelope.get("payload", {})
        except json.JSONDecodeError as exc:
            raise FlagFileError(f"{path}: line {n} is not JSON ({exc})") from exc
        if payload.get("type") != "item_flagged":
            raise FlagFileError(f"{path}: line {n} is not an item_flagged event")
        if not payload.get("item_id"):
            raise FlagFileError(f"{path}: line {n} has no item_id")
        flags.append(
            Flag(
                item_id=payload["item_id"],
                note=(payload.get("note") or "").strip(),
                pack_version=payload.get("pack_version"),
                # `record_event` doesn't stamp `at` into the payload; the
                # store keeps it on the row, and the export carries it on
                # the envelope.
                at=payload.get("at") or envelope.get("created_at"),
            )
        )
    return flags


def _source_files(pack_dir: Path) -> list[Path]:
    return sorted(p for p in pack_dir.glob("*/*.yaml"))


def _tombstones(pack_dir: Path) -> dict[str, str]:
    f = pack_dir / "tombstones.yaml"
    if not f.exists():
        return {}
    return {
        t["item_id"]: t.get("removed_in", "?")
        for t in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])
    }


def resolve(flags: list[Flag], pack_dir: Path) -> list[Resolved]:
    """Group reports by item and pair each with its source entry.

    Ordered by report count, so the loudest complaint reads first.
    """
    by_item: dict[str, Resolved] = {}
    for flag in flags:
        by_item.setdefault(flag.item_id, Resolved(item_id=flag.item_id)).flags.append(
            flag
        )

    index: dict[str, tuple[Path, dict]] = {}
    for path in _source_files(pack_dir):
        for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if isinstance(entry, dict) and entry.get("id"):
                index[entry["id"]] = (path, entry)

    tombstones = _tombstones(pack_dir)
    for item_id, res in by_item.items():
        if item_id in index:
            res.path, res.entry = index[item_id]
        elif item_id in tombstones:
            res.tombstoned_in = tombstones[item_id]
        else:
            parent = _QUESTION_SUFFIX.sub("", item_id)
            if parent != item_id and parent in index:
                res.parent_id = parent
                res.path, res.entry = index[parent]

    return sorted(by_item.values(), key=lambda r: (-len(r.flags), r.item_id))


def _accepted(entry: dict) -> list[str]:
    return [a.get("text", "") for a in entry.get("answers", []) or []]


def format_report(resolved: list[Resolved]) -> str:
    """The human-readable review, one block per reported item."""
    total = sum(len(r.flags) for r in resolved)
    versions = sorted(
        {f.pack_version for r in resolved for f in r.flags if f.pack_version}
    )
    head = f"{total} report{'s' if total != 1 else ''} across {len(resolved)} item"
    head += "s" if len(resolved) != 1 else ""
    if versions:
        head += f" · pack {', '.join(versions)}"
    out = [head, ""]

    for res in resolved:
        out.append(f"⚑ {res.item_id}  ·  {res.status}")
        for flag in res.flags:
            out.append(f"    “{flag.note or '(no note)'}”  — {flag.when}")
        entry = res.entry
        if entry is not None:
            if res.parent_id:
                out.append(
                    f"    → generated from {res.parent_id}; edit that item's "
                    "questions, not this id"
                )
            if entry.get("prompt"):
                out.append(f"    prompt:  {entry['prompt']}")
            if _accepted(entry):
                out.append(f"    accepts: {', '.join(_accepted(entry))}")
            if entry.get("choices"):
                out.append(f"    choices: {', '.join(entry['choices'])}")
            if res.path:
                out.append(f"    source:  {res.path}")
        elif res.tombstoned_in:
            out.append("    → already removed from the pack; nothing to fix")
        else:
            out.append("    → no such item in the sources (stale flag, or renamed)")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def apply_flags(resolved: list[Resolved]) -> list[str]:
    """Mark reported items ``status: flagged``, carrying the learner's own
    words into ``review_note``. Returns the ids changed.

    Flagged items build in neither the reviewed-only nor the draft path, so
    this is what stops a broken item shipping — and why it isn't the default.
    """
    changed: list[str] = []
    by_path: dict[Path, list[Resolved]] = {}
    for res in resolved:
        if res.entry is not None and res.path is not None:
            by_path.setdefault(res.path, []).append(res)

    for path, items in by_path.items():
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        target = {r.entry["id"]: r for r in items if r.entry}
        for entry in entries:
            res = target.get(entry.get("id"))
            if res is None:
                continue
            notes = "; ".join(f.note for f in res.flags if f.note)
            entry["status"] = "flagged"
            entry["review_note"] = (
                f"learner report: {notes}" if notes else ("learner report")
            )
            changed.append(entry["id"])
        path.write_text(
            yaml.dump(entries, allow_unicode=True, sort_keys=False, width=88),
            encoding="utf-8",
        )
    return changed
