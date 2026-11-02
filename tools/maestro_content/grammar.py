"""Grammar topics: content/<lang>/grammar/<id>.md with a small key: value header, then Markdown.

The grammar base, content/<lang>/grammar/base.yaml, lists every syllabus point and the topic page that covers it.
Italian IDs are the file names and base IDs as written; every other language's IDs get its prefix (de:dativ),
which the files don't carry (HANDOFF.md 6.5)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Topic:
    id: str
    title: str
    level: str
    summary: str
    body: str
    order: int


def id_prefix(language: str) -> str:
    """The prefix the pipeline adds to a language's grammar topic and base IDs: none for Italian, de: for German."""
    return "" if language == "it" else f"{language}:"


def parse(path: str, language: str = "it") -> Topic:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    header, _, body = text.partition("\n---\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    topic_id = id_prefix(language) + os.path.splitext(os.path.basename(path))[0]
    missing = [k for k in ("title", "level", "summary", "order") if k not in meta]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)}")
    return Topic(id=topic_id, title=meta["title"], level=meta["level"], summary=meta["summary"],
                 body=body.strip(), order=int(meta["order"]))


def load_all(directory: str, language: str = "it") -> list[Topic]:
    if not os.path.isdir(directory):
        return []
    topics = [parse(os.path.join(directory, f), language) for f in sorted(os.listdir(directory)) if f.endswith(".md")]
    return sorted(topics, key=lambda t: (t.order, t.id))


@dataclass
class Point:
    """One point of the grammar base (content/<lang>/grammar/base.yaml)."""
    id: str
    level: str
    category: str
    label: str
    topic: str | None = None
    source: str | None = None


def load_base(path: str, language: str = "it") -> list[Point]:
    """Reads base.yaml: a `points:` list of flat `key: value` entries (no YAML library needed)."""
    points: list[Point] = []
    current: dict[str, str] | None = None
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#") or line == "points:":
                continue
            if line.startswith("- "):
                if current is not None:
                    points.append(Point(**current))
                current = {}
                line = "  " + line[2:]
            if current is None or not line.startswith("  ") or ":" not in line:
                raise ValueError(f"{path}:{n}: expected '  key: value'")
            key, _, value = line.strip().partition(":")
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            current[key] = value
    if current is not None:
        points.append(Point(**current))
    prefix = id_prefix(language)
    if prefix:
        for p in points:
            p.id = prefix + p.id
            p.topic = prefix + p.topic if p.topic else p.topic
    return points


def check_base(points: list[Point], topics: list[Topic]) -> list[str]:
    """Errors in the grammar base: duplicate IDs, unknown levels, topics without a page."""
    errors = []
    seen: set[str] = set()
    topic_ids = {t.id for t in topics}
    for p in points:
        if p.id in seen:
            errors.append(f"grammar base: duplicate id {p.id}")
        seen.add(p.id)
        if p.level not in ("A0", "A1", "A2", "B1", "B2"):
            errors.append(f"grammar base: {p.id} has level {p.level!r}")
        if p.topic and p.topic not in topic_ids:
            errors.append(f"grammar base: {p.id} names topic {p.topic!r}, which has no page")
    return errors
