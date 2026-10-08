"""Check 5 · Story consistency, the deterministic part (docs/04).

- Every speaker, addressee and conversation partner exists in `story-bible.yaml` (`narrator` and `announcer` are
  reserved speakers).
- **Register matrix.** A line with `to:` must use a register the matrix allows at its step. Rows apply to the units in
  their `units` range; an exact (speaker, addressee) row wins over (speaker, '*'), which wins over ('*', addressee);
  two matching rows at the same level are an error in the story bible. A row with a switch point allows `register`
  before its `switch_at` step, both registers at that step and `then` after it (course order, docs/06 § Unit-level
  steps; a step of a lesson that isn't written yet sits at that lesson's start). A pair no row covers is an error too:
  the register can't be checked, so the story bible needs a row.
- **Conversations** are between their `with` character and `ch:you`, in the conversation's `register`, or a node's
  `register` from that node on; both directions must be allowed at the conversation's step.
- **Heuristic warnings:** a second-person-singular form (a verb whose every reading is 2nd singular, or *tu, ti, te,
  tuo, tua, tuoi, tue*) in a `lei` line, and formal *Lei, Suo, Sua, Suoi, Sue* (or *La, Le* inside a sentence or in a
  chunk) in a `tu` line. Conversation lines are checked with the node's register.

Everything else about the story (ages, places, prices, the timeline) is the content-critic's job.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from itcontent import ids
from itcontent.checks.context import CheckContext, Pos, Str
from itcontent.course import Loc, exercises
from itcontent.tokenize import sentence_initial

YOU = "ch:you"
SECOND_SINGULAR = frozenset({"tu", "ti", "te", "tuo", "tua", "tuoi", "tue"})
FORMAL = frozenset({"Lei", "Suo", "Sua", "Suoi", "Sue"})
FORMAL_CLITICS = frozenset({"La", "Le"})
TWO_SG = re.compile(r"(^|\+)2\+s$")


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


@dataclass(frozen=True)
class Row:
    i: int
    frm: str
    to: str
    register: str
    then: str | None
    switch_at: str | None
    lo: int
    hi: int
    loc: Loc

    def describe(self) -> str:
        sw = f", {self.then} from {self.switch_at}" if self.then and self.switch_at else ""
        return f"registers[{self.i}]: {self.frm} → {self.to}: {self.register}{sw}"


class Matrix:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx
        self.rows: list[Row] = []
        doc = ctx.course.singles.get("story_bible")
        data = _map(doc.data) if doc else {}
        self.characters = {str(c["id"]) for c in _seq(data.get("characters")) if isinstance(_map(c).get("id"), str)}
        last = len(ctx.unit_ids) - 1
        for i, r in enumerate(_seq(data.get("registers"))):
            r = _map(r)
            units = r.get("units")
            if units == "all":
                lo, hi = 0, last
            elif isinstance(units, list) and len(units) == 2:
                lo, hi = ctx.unit_index.get(str(units[0]), 0), ctx.unit_index.get(str(units[1]), last)
            else:
                continue  # the schema reports it
            if not all(isinstance(r.get(k), str) for k in ("from", "to", "register")):
                continue
            loc = doc.loc.child("registers", i) if doc else Loc("content/story-bible.yaml")
            self.rows.append(Row(i, r["from"], r["to"], r["register"], r.get("then"), r.get("switch_at"), lo, hi, loc))

    def exists(self, who: str) -> bool:
        return who in self.characters or who in ids.RESERVED_SPEAKERS or who in ids.RESERVED_SPEAKERS.values()

    def lookup(self, speaker: str, addressee: str, unit: int) -> list[Row]:
        for f, t in ((speaker, addressee), (speaker, "*"), ("*", addressee)):
            rows = [r for r in self.rows if r.frm == f and r.to == t and r.lo <= unit <= r.hi]
            if rows:
                return rows
        return []

    def allowed(self, row: Row, pos: Pos) -> set[str]:
        if not (row.then and row.switch_at):
            return {row.register}
        at = self.ctx.step_pos(row.switch_at)
        if at is None:
            return {row.register, row.then}
        if pos < at:
            return {row.register}
        if pos == at:
            return {row.register, row.then}
        return {row.then}

    def check_rows(self) -> None:
        """Two rows for the same (from, to) whose unit ranges overlap would both match: a story-bible error."""
        for a in self.rows:
            for b in self.rows:
                if a.i < b.i and a.frm == b.frm and a.to == b.to and a.lo <= b.hi and b.lo <= a.hi:
                    self.ctx.add(
                        "error",
                        5,
                        "register",
                        b.loc,
                        f"registers[{a.i}] and registers[{b.i}] both cover {a.frm} → {a.to} in "
                        f"{self.ctx.unit_ids[max(a.lo, b.lo)]}: narrow their `units`",
                    )


class StoryCheck:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx
        self.matrix = Matrix(ctx)

    def at(self, pos: Pos, step: str | None) -> str:
        return step or self.ctx.describe(pos)

    def register(self, loc: Loc, speaker: str, to: str, register: str, pos: Pos, step: str | None, what: str) -> None:
        rows = self.matrix.lookup(speaker, to, pos[0])
        unit = self.ctx.unit_of_pos(pos)
        if not rows:
            self.ctx.add(
                "error",
                5,
                "register",
                loc,
                f"{what}: no register-matrix row covers {speaker} → {to} in {unit}; add one to story-bible.yaml "
                "(ask the content lead)",
            )
            return
        if len(rows) > 1:
            return  # check_rows reports the overlap
        row = rows[0]
        allowed = self.matrix.allowed(row, pos)
        if register not in allowed:
            want = " or ".join(sorted(allowed))
            self.ctx.add(
                "error",
                5,
                "register",
                loc,
                f"{what}: {speaker} says {register} to {to} at {self.at(pos, step)}, but the story bible says {want} "
                f"({row.describe()}). Fix the line, not the bible",
            )

    # ------------------------------------------------------------ lines

    def lines(self) -> None:
        for s in self.ctx.strings:
            if s.role != "line" or s.line is None or s.pos is None:
                continue
            line = s.line
            line_loc = Loc(s.file, s.path[:-1])
            speaker = line.get("speaker")
            if isinstance(speaker, str) and not self.matrix.exists(speaker):
                self.ctx.add(
                    "error", 5, "speaker", line_loc.child("speaker"), f"speaker {speaker} isn't in story-bible.yaml"
                )
            to, reg = line.get("to"), line.get("register")
            if isinstance(to, str) and not self.matrix.exists(to):
                self.ctx.add("error", 5, "speaker", line_loc.child("to"), f"addressee {to} isn't in story-bible.yaml")
                continue
            if isinstance(speaker, str) and isinstance(to, str) and isinstance(reg, str):
                self.register(line_loc.child("register"), speaker, to, reg, s.pos, s.step, f"line {s.ref}")
                self.heuristics(s, reg, f"line {s.ref}")

    # ------------------------------------------------------------ conversations

    def conversations(self) -> None:
        strings: dict[str, list[Str]] = {}
        for s in self.ctx.strings:
            if s.exercise is not None and s.exercise.format == "conversation":
                strings.setdefault(s.exercise.id, []).append(s)
        for x in exercises(self.ctx.course):
            if x.format != "conversation" or x.loc.file not in self.ctx.checked_files:
                continue
            place = self.ctx.place(x.loc)
            if place is None or place.pos is None:
                continue
            ex = x.data
            partner = ex.get("with")
            if not isinstance(partner, str):
                continue
            if not self.matrix.exists(partner):
                self.ctx.add("error", 5, "speaker", x.loc.child("with"), f"{partner} isn't in story-bible.yaml")
                continue
            regs = node_registers(ex)
            checked: set[tuple[str, str | None]] = set()
            for _nid, (reg, source) in sorted(regs.items()):
                if not isinstance(reg, str) or (reg, source) in checked:
                    continue
                checked.add((reg, source))
                loc = x.loc.child("nodes", source, "register") if source else x.loc.child("register")
                what = f"conversation {x.id}" + (f" from node {source}" if source else "")
                self.register(loc, partner, YOU, reg, place.pos, place.step, what)
                self.register(loc, YOU, partner, reg, place.pos, place.step, what)
            for s in strings.get(x.id, []):
                node = s.path[s.path.index("nodes") + 1] if "nodes" in s.path else None
                reg = regs.get(str(node), (None, None))[0] if node is not None else None
                if not isinstance(reg, str):
                    continue
                if s.role == "say" or s.role == "help" or (s.role == "accept" and s.model):
                    self.heuristics(s, reg, f"conversation {x.id}/{node}")

    # ------------------------------------------------------------ heuristics

    def heuristics(self, s: Str, register: str, what: str) -> None:
        toks = s.tokens
        hits: list[str] = []
        for k, t in enumerate(toks):
            if not t.is_word:
                continue
            if register == "lei":
                verbs = [a for a in t.analyses if a.is_verb()]
                if t.norm in SECOND_SINGULAR or (verbs and all(TWO_SG.search(a.features) for a in verbs)):
                    hits.append(t.surface)
            elif register == "tu" and (
                t.surface in FORMAL
                or (t.surface in FORMAL_CLITICS and (t.chunk is not None or not sentence_initial(toks, k)))  # type: ignore[arg-type]
            ):
                hits.append(t.surface)
        if hits:
            kind = "second-person-singular" if register == "lei" else "formal"
            self.ctx.add(
                "warning",
                5,
                "register",
                s.loc,
                f"{what} is {register} but has {kind} form(s) {', '.join(repr(h) for h in hits)} "
                f'(in "{s.text}"): check the register',
            )

    def run(self) -> None:
        self.matrix.check_rows()
        self.lines()
        self.conversations()


def node_registers(ex: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    """Each node's register and the node that set it (None: the conversation's `register`), following the graph from
    `start` (a node's `register` holds from that node on)."""
    base = ex.get("register") if isinstance(ex.get("register"), str) else None
    nodes = _map(ex.get("nodes"))
    out: dict[str, tuple[str | None, str | None]] = {}
    queue: deque[tuple[Any, tuple[str | None, str | None]]] = deque([(ex.get("start"), (base, None))])
    while queue:
        nid, inherited = queue.popleft()
        if not isinstance(nid, str) or nid in out or nid not in nodes:
            continue
        node = _map(nodes[nid])
        here = (node["register"], nid) if isinstance(node.get("register"), str) else inherited
        out[nid] = here
        for intent in _seq(node.get("expect")):
            queue.append((_map(intent).get("next"), here))
    for nid, node in nodes.items():
        if isinstance(nid, str) and nid not in out:
            node = _map(node)
            out[nid] = (node["register"], nid) if isinstance(node.get("register"), str) else (base, None)
    return out


def check_story(ctx: CheckContext) -> None:
    StoryCheck(ctx).run()
