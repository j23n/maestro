"""Annotation lock files as the pack builder reads them (docs/03 § Annotation lock files).

`content/.annotations/<path>.json` holds every Italian string of `content/<path>.yaml` with its tokens. The builder
looks strings up by their YAML path and checks that the text still matches the YAML: a mismatch means the lock file
is stale (`make annotate`), which is a build error rather than a pack with wrong tokens.

`tokenized()` turns a lock string (or a slice of it, for cloze `before`/`after`) into the payload's `TokenizedText`
(`schemas/pack-payloads.schema.json` § tokenizedText): a token's `itemId` is its chunk if it is inside one, else its
item (a lexical article carries its noun's item; an article or articulated preposition carries its grammar point),
and `flags` are 1 new in this step, 2 recognise-only, 4 a target grammar point of the lesson.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itcontent.annotate import fmt_path, lock_path
from itcontent.pack.common import BuildError

PathT = tuple[str | int, ...]

FLAG_NEW = 1
FLAG_RECOGNISE = 2
FLAG_TARGET = 4
PAYLOAD_KINDS = frozenset({"word", "punct", "name", "number", "foreign"})


@dataclass(frozen=True)
class Detection:
    point: str
    first: int
    last: int


@dataclass(frozen=True)
class LockString:
    """One annotated string of a lock file."""

    file: str  # the YAML file it belongs to
    path: str
    role: str
    text: str
    lead: str
    tokens: tuple[dict[str, Any], ...]
    detections: tuple[Detection, ...]
    ref: str | None = None
    model: bool | None = None
    pattern: str | None = None
    expansion: int | None = None
    gap: tuple[int, int] | None = None
    fragment: tuple[int, int] | None = None

    @classmethod
    def from_json(cls, file: str, d: dict[str, Any]) -> LockString:
        gap = d.get("gap")
        frag = d.get("fragment")
        return cls(
            file=file,
            path=str(d["path"]),
            role=str(d["role"]),
            text=str(d["text"]),
            lead=str(d.get("lead", "")),
            tokens=tuple(d.get("tokens") or ()),
            detections=tuple(Detection(str(x["point"]), *x["tokens"]) for x in d.get("detections") or ()),
            ref=d.get("ref"),
            model=d.get("model"),
            pattern=d.get("pattern"),
            expansion=d.get("expansion"),
            gap=(int(gap[0]), int(gap[1])) if isinstance(gap, list) and len(gap) == 2 else None,
            fragment=(int(frag[0]), int(frag[1])) if isinstance(frag, list) and len(frag) == 2 else None,
        )

    def where(self) -> str:
        return f"{self.file} › {self.path}"


class LockFile:
    """The strings of one lock file, by YAML path (in file order)."""

    def __init__(self, file: str, strings: Iterable[LockString], *, exists: bool = True) -> None:
        self.file = file
        self.exists = exists
        self.by_path: dict[str, list[LockString]] = {}
        for s in strings:
            self.by_path.setdefault(s.path, []).append(s)

    def entries(self, path: PathT | str) -> list[LockString]:
        key = path if isinstance(path, str) else fmt_path(path)
        return self.by_path.get(key, [])

    def plain(self, path: PathT, text: str) -> LockString:
        """The one annotation of a plain string; raises when it is missing or its text differs (a stale lock)."""
        found = [s for s in self.entries(path) if s.fragment is None and s.expansion is None]
        where = f"{self.file} › {fmt_path(path)}"
        if not found:
            raise BuildError(f"{where}: no annotation for {text!r}{self._hint()}")
        if found[0].text != text:
            raise BuildError(f"{where}: the annotation is stale ({found[0].text!r} ≠ {text!r}); run `make annotate`")
        return found[0]

    def model(self, path: PathT, pattern: str | None = None) -> LockString:
        """The model answer's annotation of a pattern (or a cloze text): the entry marked `model: true`."""
        where = f"{self.file} › {fmt_path(path)}"
        found = [s for s in self.entries(path) if s.model]
        if not found:
            raise BuildError(f"{where}: no annotated model answer{self._hint()}")
        if pattern is not None and found[0].pattern is not None and found[0].pattern != pattern:
            raise BuildError(f"{where}: the annotation is stale (pattern {found[0].pattern!r} ≠ {pattern!r})")
        return found[0]

    def under(self, prefix: PathT) -> Iterator[LockString]:
        """Every string at or below a YAML path, in path order."""
        p = fmt_path(prefix)
        for key, strings in self.by_path.items():
            if key == p or key.startswith(p + ".") or key.startswith(p + "["):
                yield from strings

    def all(self) -> Iterator[LockString]:
        for strings in self.by_path.values():
            yield from strings

    def _hint(self) -> str:
        if not self.exists:
            return f" (the lock file for {self.file} is missing; run `make annotate`)"
        return "; run `make annotate`"


class Locks:
    """Lock files of a repository, loaded on demand."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, LockFile] = {}

    def __getitem__(self, rel: str) -> LockFile:
        if rel not in self._cache:
            path = self.root / lock_path(rel)
            if not path.is_file():
                self._cache[rel] = LockFile(rel, (), exists=False)
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("source") != rel:
                    raise BuildError(f"{path}: written for {data.get('source')!r}, not {rel}")
                self._cache[rel] = LockFile(rel, (LockString.from_json(rel, s) for s in data.get("strings") or ()))
        return self._cache[rel]


# ---------------------------------------------------------------- tokens → payload


def token_item(t: dict[str, Any]) -> str | None:
    """The item a token belongs to: its chunk, else its item (a lexical article's noun; an article's point)."""
    return t.get("chunk") or t.get("item")


def token_flags(t: dict[str, Any], targets: frozenset[str]) -> int:
    flags = set(t.get("flags") or ())
    out = 0
    if "new" in flags:
        out |= FLAG_NEW
    if "recognise" in flags:
        out |= FLAG_RECOGNISE
    if targets and (set(t.get("detections") or ()) & targets or t.get("item") in targets):
        out |= FLAG_TARGET
    return out


def payload_token(s: LockString, t: dict[str, Any], targets: frozenset[str]) -> dict[str, Any]:
    kind = str(t.get("kind"))
    if kind not in PAYLOAD_KINDS:
        raise BuildError(f"{s.where()}: token {t.get('surface')!r} of kind {kind!r} can't be shown to learners")
    return {
        "surface": str(t["surface"]),
        "trailing": str(t.get("trailing", "")),
        "kind": kind,
        "itemId": token_item(t),
        "gloss": t.get("gloss"),
        "flags": token_flags(t, targets),
    }


def tokenized(
    s: LockString,
    targets: frozenset[str] = frozenset(),
    *,
    start: int = 0,
    end: int | None = None,
    lead: str | None = None,
) -> dict[str, Any]:
    """A `TokenizedText` from a lock string, or from tokens [start, end) of it with the given lead."""
    tokens = [payload_token(s, t, targets) for t in s.tokens[start:end]]
    lead = s.lead if lead is None else lead
    text = lead + "".join(t["surface"] + t["trailing"] for t in tokens)
    if start == 0 and end is None and text != s.text:
        raise BuildError(f"{s.where()}: tokens don't rebuild the text ({text!r} ≠ {s.text!r}); run `make annotate`")
    return {"text": text, "lead": lead, "tokens": tokens}


def has_words(s: LockString) -> bool:
    """True when a string has anything to tap (words, names or foreign words), not only digits and punctuation."""
    return any(t.get("kind") in ("word", "name", "foreign") for t in s.tokens)
