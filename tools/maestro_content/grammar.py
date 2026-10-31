"""Grammar topics: content/grammar/<id>.md with a small key: value header, then Markdown."""

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


def parse(path: str) -> Topic:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    header, _, body = text.partition("\n---\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    topic_id = os.path.splitext(os.path.basename(path))[0]
    missing = [k for k in ("title", "level", "summary", "order") if k not in meta]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)}")
    return Topic(id=topic_id, title=meta["title"], level=meta["level"], summary=meta["summary"],
                 body=body.strip(), order=int(meta["order"]))


def load_all(directory: str) -> list[Topic]:
    if not os.path.isdir(directory):
        return []
    topics = [parse(os.path.join(directory, f)) for f in sorted(os.listdir(directory)) if f.endswith(".md")]
    return sorted(topics, key=lambda t: (t.order, t.id))
