"""The answer-pattern language (docs/03 § The answer-pattern language): parser and expander.

Syntax: plain text; `{a|b}` alternatives (sequences, nesting); `(…)` optional; `[…]` focus; `{m:…|f:…}` gendered
alternatives; slots `{NAME}`, `{NUMBER}`, `{ME.nationality}`, `{ME.home}`, `{ME.country}`; `\\x` escapes any
character. Expansion order: alternatives left to right, an optional group present before absent, and the leftmost
choice varies slowest. The first expansion is the model answer. A pattern expands to at most 512 strings.

Every alternative of a gendered group carries `m:` or `f:`. Gendered groups are linked: an expansion takes masculine
alternatives in every gendered group or feminine ones in every one, never a mix (one person:
`sono {m:nato|f:nata} e {m:americano|f:americana}` → 2 expansions, not 4); mixed combinations are pruned before
counting toward the limit. Without a learner a slot is one token written as its placeholder (`{NAME}`, `{ME.home}`);
slot-like names that aren't slots (`{NOME}`, `{ME.city}`) are errors, not literals.

Each `Expansion` carries the normalised text (`itcontent.normalize`), its tokens, the indices of focus tokens, its
gender tag, and the slots with their token indices; `raw` is the same expansion before normalisation (case and
punctuation kept, whitespace collapsed), which is what the annotator tokenises.

`fixtures/grading/patterns.json` is the shared reference (LearningCore's `AnswerPattern` passes the same cases).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from itertools import product

from itcontent.normalize import normalize_marked

LIMIT = 512
SLOTS = frozenset({"NAME", "NUMBER", "ME.nationality", "ME.home", "ME.country"})


class PatternError(ValueError):
    """A pattern that does not parse or expands to too many strings."""


# ---------------------------------------------------------------- syntax tree


@dataclass(frozen=True)
class Lit:
    text: str


@dataclass(frozen=True)
class Slot:
    name: str


@dataclass(frozen=True)
class Seq:
    parts: tuple[Node, ...]


@dataclass(frozen=True)
class Alt:
    options: tuple[Seq, ...]
    genders: tuple[str, ...] | None = None  # ("m", "f") for {m:…|f:…}


@dataclass(frozen=True)
class Opt:
    body: Seq


@dataclass(frozen=True)
class Focus:
    body: Seq


Node = Lit | Slot | Seq | Alt | Opt | Focus


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def error(self, msg: str, at: int | None = None) -> PatternError:
        pos = self.i if at is None else at
        return PatternError(f"{msg} at character {pos + 1} of '{self.s}'")

    def parse(self) -> Seq:
        seq = self.seq(closers="")
        if self.i < len(self.s):
            raise self.error(f"unexpected '{self.s[self.i]}'")
        return seq

    def seq(self, closers: str) -> Seq:
        parts: list[Node] = []
        buf: list[str] = []

        def flush() -> None:
            if buf:
                parts.append(Lit("".join(buf)))
                buf.clear()

        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch == "\\":
                if self.i + 1 >= len(self.s):
                    raise self.error("dangling '\\'")
                buf.append(self.s[self.i + 1])
                self.i += 2
            elif ch in closers:
                break
            elif ch == "|":
                raise self.error("'|' outside {…}")
            elif ch in ")]}":
                raise self.error(f"unmatched '{ch}'")
            elif ch == "{":
                flush()
                parts.append(self.brace())
            elif ch == "(":
                flush()
                start = self.i
                self.i += 1
                body = self.seq(closers=")")
                if self.i >= len(self.s):
                    raise self.error("unclosed '('", start)
                self.i += 1
                parts.append(Opt(body))
            elif ch == "[":
                flush()
                start = self.i
                self.i += 1
                body = self.seq(closers="]")
                if self.i >= len(self.s):
                    raise self.error("unclosed '['", start)
                self.i += 1
                parts.append(Focus(body))
            else:
                buf.append(ch)
                self.i += 1
        flush()
        return Seq(tuple(parts))

    def brace(self) -> Node:
        start = self.i
        self.i += 1
        close = self.s.find("}", self.i)
        inner = self.s[self.i : close] if close >= 0 else ""
        if close >= 0 and inner in SLOTS:
            self.i = close + 1
            return Slot(inner)
        if close >= 0 and (inner.isupper() or inner.startswith("ME.")) and all(c not in inner for c in "{}|()[]\\"):
            raise self.error(f"unknown slot {{{inner}}} (known: {', '.join(sorted(SLOTS))})", start)
        options: list[Seq] = []
        genders: list[str] = []
        while True:
            gender = None
            if self.s.startswith(("m:", "f:"), self.i):
                gender = self.s[self.i]
                self.i += 2
            options.append(self.seq(closers="|}"))
            genders.append(gender or "")
            if self.i >= len(self.s):
                raise self.error("unclosed '{'", start)
            if self.s[self.i] == "}":
                self.i += 1
                break
            self.i += 1  # '|'
        if any(genders):
            if not all(genders):
                raise self.error("every alternative of a gendered group carries m: or f:", start)
            return Alt(tuple(options), tuple(genders))
        return Alt(tuple(options))


def parse(pattern: str) -> Seq:
    """Parse a pattern (after NFC) into its syntax tree; raises PatternError."""
    return _Parser(unicodedata.normalize("NFC", pattern)).parse()


# ---------------------------------------------------------------- counting (exact, before expanding)

_G = ("", "m", "f")  # gender states: none, masculine, feminine


def _count(node: Node) -> dict[str, int]:
    if isinstance(node, Lit | Slot):
        return {"": 1, "m": 0, "f": 0}
    if isinstance(node, Seq):
        acc = {"": 1, "m": 0, "f": 0}
        for part in node.parts:
            c = _count(part)
            acc = {
                "": acc[""] * c[""],
                "m": acc["m"] * c[""] + acc[""] * c["m"] + acc["m"] * c["m"],
                "f": acc["f"] * c[""] + acc[""] * c["f"] + acc["f"] * c["f"],
            }
        return acc
    if isinstance(node, Opt):
        c = _count(node.body)
        return {"": c[""] + 1, "m": c["m"], "f": c["f"]}
    if isinstance(node, Focus):
        return _count(node.body)
    # Alt
    total = {"": 0, "m": 0, "f": 0}
    for k, opt in enumerate(node.options):
        c = _count(opt)
        if node.genders:
            g = node.genders[k]
            total[g] += c[""] + c[g]
        else:
            for g in _G:
                total[g] += c[g]
    return total


def count(pattern: str | Seq) -> int:
    """How many strings the pattern expands to (gender-consistent combinations only)."""
    tree = parse(pattern) if isinstance(pattern, str) else pattern
    return sum(_count(tree).values())


# ---------------------------------------------------------------- expanding

# A variant is (pieces, gender); a piece is (text, focus) or a Slot.
Piece = tuple[str, bool] | Slot
Variant = tuple[tuple[Piece, ...], str]


def _merge(a: str, b: str) -> str | None:
    if not a:
        return b
    if not b or a == b:
        return a
    return None


def _variants(node: Node, focus: bool) -> list[Variant]:
    if isinstance(node, Lit):
        return [(((node.text, focus),), "")]
    if isinstance(node, Slot):
        return [((node,), "")]
    if isinstance(node, Focus):
        return _variants(node.body, True)
    if isinstance(node, Opt):
        return [*_variants(node.body, focus), ((), "")]
    if isinstance(node, Alt):
        out: list[Variant] = []
        for k, opt in enumerate(node.options):
            g = node.genders[k] if node.genders else ""
            for pieces, vg in _variants(opt, focus):
                merged = _merge(g, vg)
                if merged is not None:
                    out.append((pieces, merged))
        return out
    # Seq: cartesian product, leftmost slowest
    seqs = [_variants(p, focus) for p in node.parts]
    out = []
    for combo in product(*seqs):
        pieces: tuple[Piece, ...] = ()
        gender: str | None = ""
        for p, g in combo:
            pieces += p
            gender = _merge(gender, g) if gender is not None else None
        if gender is not None:
            out.append((pieces, gender))
    return out


@dataclass(frozen=True)
class Expansion:
    text: str  # normalised (docs/05)
    tokens: tuple[str, ...]
    focus: tuple[int, ...]  # indices into tokens
    gender: str | None  # "m" | "f" | None
    slots: tuple[tuple[int, str], ...]  # (token index, slot name)
    raw: str  # before normalisation: case and punctuation kept, whitespace collapsed; slots written {NAME}
    raw_slots: tuple[tuple[int, int, str], ...] = field(default=())  # (start, end, name) character spans in raw
    raw_focus: tuple[tuple[int, int], ...] = field(default=())  # focus character spans in raw


@dataclass(frozen=True)
class _Mark:
    focus: bool
    slot: str | None


def _build(pieces: tuple[Piece, ...], gender: str) -> Expansion:
    chars: list[str] = []  # for normalising: a slot is always a whole token, so it gets spaces around it
    marks: list[_Mark] = []
    src_c: list[str] = []  # as written
    src_m: list[_Mark] = []
    for piece in pieces:
        if isinstance(piece, Slot):
            text = "{" + piece.name + "}"
            chars.append(" ")
            marks.append(_Mark(False, None))
            for ch in text:
                chars.append(ch)
                marks.append(_Mark(False, piece.name))
                src_c.append(ch)
                src_m.append(_Mark(False, piece.name))
            chars.append(" ")
            marks.append(_Mark(False, None))
        else:
            text, foc = piece
            for ch in text:
                chars.append(ch)
                marks.append(_Mark(foc, None))
                src_c.append(ch)
                src_m.append(_Mark(foc, None))
    # raw: collapse whitespace, trim, keep the marks
    raw_c: list[str] = []
    raw_m: list[_Mark] = []
    for ch, m in zip(src_c, src_m, strict=True):
        if ch.isspace() and m.slot is None:
            if not raw_c or raw_c[-1] == " ":
                continue
            raw_c.append(" ")
            raw_m.append(m)
        else:
            raw_c.append(ch)
            raw_m.append(m)
    while raw_c and raw_c[-1] == " ":
        raw_c.pop()
        raw_m.pop()
    raw = "".join(raw_c)
    raw_slots = tuple(_spans(raw_m, lambda m: m.slot))
    raw_focus = tuple((a, b) for a, b, _ in _spans(raw_m, lambda m: "f" if m.focus else None))

    norm_c, norm_m = normalize_marked(chars, marks, protected=lambda m: m.slot is not None)
    text = "".join(norm_c)
    toks: list[str] = []
    focus: list[int] = []
    slots: list[tuple[int, str]] = []
    cur: list[str] = []
    cur_focus = False
    cur_slot: str | None = None
    for ch, m in [*zip(norm_c, norm_m, strict=True), (" ", _Mark(False, None))]:
        if ch == " " and m.slot is None:
            if cur:
                if cur_focus:
                    focus.append(len(toks))
                if cur_slot:
                    slots.append((len(toks), cur_slot))
                toks.append("".join(cur))
            cur, cur_focus, cur_slot = [], False, None
            continue
        cur.append(ch)
        cur_focus = cur_focus or m.focus
        cur_slot = cur_slot or m.slot
    return Expansion(
        text=text,
        tokens=tuple(toks),
        focus=tuple(focus),
        gender=gender or None,
        slots=tuple(slots),
        raw=raw,
        raw_slots=raw_slots,
        raw_focus=raw_focus,
    )


def _spans(marks: list[_Mark], key) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    start = None
    cur = None
    for i, m in enumerate([*marks, _Mark(False, None)]):
        k = key(m)
        if k != cur:
            if cur is not None and start is not None:
                out.append((start, i, cur))
            start, cur = (i, k) if k is not None else (None, None)
    return out


def expand(pattern: str, limit: int = LIMIT) -> list[Expansion]:
    """All expansions of a pattern in order (the first is the model answer). Raises PatternError past `limit`."""
    tree = parse(pattern)
    n = count(tree)
    if n > limit:
        raise PatternError(f"expansion limit {limit} exceeded ({n})")
    return [_build(pieces, gender) for pieces, gender in _variants(tree, False)]


def model_answer(pattern: str) -> Expansion:
    return expand(pattern)[0]
