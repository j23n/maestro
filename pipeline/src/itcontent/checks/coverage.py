"""Check 1 · Syllabus coverage (docs/04): every entry of `syllabus/a1-syllabus.yaml` traced to where it is
introduced, practised and assessed (only the roles in its `roles` list, when given; `roles: []` is information only).

- `g:` / `s:` refs: introduced by the step that introduces them (written, never a fallback); practised by a learn
  exercise targeting them; assessed by a check or final exercise targeting them. A point with status `chunk` is taught
  only through its chunks, so exercises targeting a chunk that `exemplifies` it count too.
- `cd:` refs: introduced by their unit's opener once a lesson of the unit is written; practised by a learn exercise
  tagged with them; assessed by a check or final exercise tagged with them.
- `topic:` refs: introduced by an introduced item with that topic; practised and assessed by exercises whose primary
  target has the topic.
- `kind:` refs: introduced and practised by a written step of that kind (never assessed).
- `format:` refs: introduced and practised by a learn exercise of that format; assessed by a check or final exercise
  of that format.
- `section:` refs: every role by a check or final section of that id holding exercises.
- a direct `sy:` tag: introduced by the first tagged exercise's step; practised by a tagged learn exercise; assessed
  by a tagged check exercise.

A can-do whose own `syllabus` lists the entry counts like a `cd:` ref. Learn exercises are those of lessons and tasks;
placement items never count. Every satisfying step, exercise or item is kept (sorted by course position), which is
also what the pack's `syllabus_trace` stores; the report shows the first.

An entry is *covered* when every required role has a location, a *gap* otherwise. A gap whose units (or, for `units:
all`, any unit) are still incomplete is *pending*: written content may still cover it. With `coverage_mode: report`
each gap is a warning and the summary line shows the percentage; with `enforce` each gap is an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from itcontent.checks.context import CheckContext, Pos
from itcontent.course import ExerciseRef, Loc, exercises

ROLES = ("introduced", "practised", "assessed")


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


@dataclass(frozen=True, order=True)
class Hit:
    pos: Pos
    ref: str  # the step, exercise or item that satisfies the role
    unit: str
    via: str  # the covered_by ref, the can-do, or "tag"


@dataclass
class Entry:
    id: str
    label: str
    area: str
    units: list[str] | str
    roles: tuple[str, ...]
    loc: Loc
    hits: dict[str, list[Hit]] = field(default_factory=dict)
    status: str = ""  # covered | gap | pending | info

    def first(self, role: str) -> Hit | None:
        hits = self.hits.get(role) or []
        return hits[0] if hits else None

    @property
    def missing(self) -> list[str]:
        return [r for r in self.roles if not self.hits.get(r)]


@dataclass
class CoverageResult:
    mode: str
    entries: list[Entry]

    @property
    def required(self) -> list[Entry]:
        return [e for e in self.entries if e.roles]

    @property
    def percent(self) -> float:
        req = self.required
        return 100.0 * sum(1 for e in req if e.status == "covered") / len(req) if req else 100.0

    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in ("covered", "gap", "pending", "info")}
        for e in self.entries:
            out[e.status] += 1
        return out

    def trace_rows(self) -> list[tuple[str, str, str, str]]:
        """(syllabus_id, role, unit_id, ref) rows for the pack's `syllabus_trace`, sorted, one per ref."""
        rows = {(e.id, role, h.unit, h.ref) for e in self.entries for role, hs in e.hits.items() for h in hs}
        return sorted(rows)


class Coverage:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx
        self.learn: list[tuple[ExerciseRef, Pos, str]] = []  # exercise, position, step or exercise id
        self.check: list[tuple[ExerciseRef, Pos, str]] = []
        for x in exercises(ctx.course):
            if x.container == "placement":
                continue
            place = ctx.place(x.loc)
            if place is None or place.pos is None:
                continue
            target = (x, place.pos, place.step or x.id)
            (self.check if x.container in ("check", "final") else self.learn).append(target)
        self.learn.sort(key=lambda t: t[1])
        self.check.sort(key=lambda t: t[1])
        self.can_do_unit: dict[str, str] = {}
        self.can_do_syllabus: dict[str, list[str]] = {}
        for u in ctx.course.units:
            for cd in _seq(_map(u.spec.data).get("can_do")) if u.spec else []:
                cid = _map(cd).get("id")
                if isinstance(cid, str):
                    self.can_do_unit[cid] = u.id
                    for sy in _seq(_map(cd).get("syllabus")):
                        if isinstance(sy, str):
                            self.can_do_syllabus.setdefault(sy, []).append(cid)
        self.started = {u.id for u in ctx.course.units if u.lessons}

    # ------------------------------------------------------------ evidence per ref

    def _ex_hits(self, pool: list[tuple[ExerciseRef, Pos, str]], pred, via: str) -> list[Hit]:
        return [Hit(pos, x.id, x.unit_id, via) for x, pos, _ in pool if pred(x)]

    @staticmethod
    def _targets(x: ExerciseRef) -> list[str]:
        return [str(_map(t).get("item")) for t in _seq(x.data.get("targets")) if isinstance(_map(t).get("item"), str)]

    @staticmethod
    def _tags(x: ExerciseRef) -> list[str]:
        return [t for t in _seq(x.data.get("tags")) if isinstance(t, str)]

    def ref_hits(self, ref: str) -> dict[str, list[Hit]]:
        ctx = self.ctx
        prefix = ref.split(":", 1)[0]
        name = ref.split(":", 1)[1] if ":" in ref else ""
        out: dict[str, list[Hit]] = {r: [] for r in ROLES}
        if prefix in ("g", "s"):
            refs = {ref}
            if ctx.point_status(ref) == "chunk":
                refs |= {i for i, it in ctx.items.items() if ref in _seq(it.get("exemplifies"))}
            out["introduced"] = [Hit(i.pos, i.step, ctx.unit_of_pos(i.pos), ref) for i in ctx.intros.written(ref)]
            out["practised"] = self._ex_hits(self.learn, lambda x: bool(refs & set(self._targets(x))), ref)
            out["assessed"] = self._ex_hits(self.check, lambda x: bool(refs & set(self._targets(x))), ref)
        elif prefix == "cd":
            unit = self.can_do_unit.get(ref)
            if unit and unit in self.started:
                out["introduced"] = [Hit((ctx.unit_index[unit], 0, 0), f"{unit}.step-opener", unit, ref)]
            out["practised"] = self._ex_hits(self.learn, lambda x: ref in self._tags(x), ref)
            out["assessed"] = self._ex_hits(self.check, lambda x: ref in self._tags(x), ref)
        elif prefix == "topic":
            items = {i for i, it in ctx.items.items() if ref in _seq(it.get("topics"))}
            for iid in sorted(items):
                for intro in ctx.intros.written(iid)[:1]:
                    out["introduced"].append(Hit(intro.pos, iid, ctx.unit_of_pos(intro.pos), ref))
            out["practised"] = self._ex_hits(self.learn, lambda x: bool(items & set(self._targets(x))), ref)
            out["assessed"] = self._ex_hits(self.check, lambda x: bool(items & set(self._targets(x))), ref)
        elif prefix == "kind":
            steps = [s for s in ctx.steps.values() if s.kind == name and s.lesson is not None]
            hits = [Hit(s.pos, s.id, s.unit, ref) for s in steps]
            # unit-level step kinds exist once the task or check holds an exercise for them
            hits += [
                Hit(pos, step, x.unit_id, ref)
                for x, pos, step in self.learn
                if x.container == "task" and x.step_kind == name
            ]
            if name == "check":
                hits += [Hit(pos, step, x.unit_id, ref) for x, pos, step in self.check if x.container == "check"]
            out["introduced"] = out["practised"] = sorted(set(hits))
        elif prefix == "format":
            out["introduced"] = out["practised"] = self._ex_hits(self.learn, lambda x: x.format == name, ref)
            out["assessed"] = self._ex_hits(self.check, lambda x: x.format == name, ref)
        elif prefix == "section":
            hits = self._ex_hits(self.check, lambda x: x.section == name, ref)
            out["introduced"] = out["practised"] = out["assessed"] = hits
        for r in ROLES:
            out[r] = sorted(set(out[r]))
        return out

    def tag_hits(self, sy: str) -> dict[str, list[Hit]]:
        tagged = lambda x: sy in self._tags(x)  # noqa: E731
        steps = sorted({Hit(pos, step, x.unit_id, "tag") for x, pos, step in [*self.learn, *self.check] if tagged(x)})
        return {
            "introduced": steps[:1],
            "practised": self._ex_hits(self.learn, tagged, "tag"),
            "assessed": self._ex_hits(self.check, tagged, "tag"),
        }

    # ------------------------------------------------------------ entries

    def incomplete(self, units: list[str] | str) -> bool:
        ids = self.ctx.unit_ids if units == "all" else [u for u in units if isinstance(u, str)]
        for uid in ids:
            uf = self.ctx.unit(uid)
            if uf is None or not uf.complete:
                return True
        return False

    def run(self) -> CoverageResult:
        ctx = self.ctx
        mode = str(ctx.checker.get("coverage_mode", "report"))
        doc = ctx.course.singles.get("syllabus")
        entries: list[Entry] = []
        cache: dict[str, dict[str, list[Hit]]] = {}
        for i, e in enumerate(_seq(_map(doc.data).get("items")) if doc else []):
            e = _map(e)
            eid = e.get("id")
            if not isinstance(eid, str):
                continue
            roles = tuple(r for r in _seq(e.get("roles")) if r in ROLES) if "roles" in e else ROLES
            units = e.get("units") if e.get("units") == "all" else [u for u in _seq(e.get("units"))]
            entry = Entry(eid, str(e.get("label", "")), str(e.get("area", "")), units, roles, doc.loc.child("items", i))
            refs = [r for r in _seq(e.get("covered_by")) if isinstance(r, str)]
            refs += [cd for cd in self.can_do_syllabus.get(eid, []) if cd not in refs]
            sources = [cache.setdefault(r, self.ref_hits(r)) for r in refs] + [self.tag_hits(eid)]
            for role in ROLES:
                entry.hits[role] = sorted({h for src in sources for h in src[role]})
            if not roles:
                entry.status = "info"
            elif not entry.missing:
                entry.status = "covered"
            else:
                entry.status = "pending" if self.incomplete(units) else "gap"
            entries.append(entry)
        result = CoverageResult(mode, entries)
        self.findings(result)
        return result

    def findings(self, result: CoverageResult) -> None:
        pct = result.percent
        level = "error" if result.mode == "enforce" else "warning"
        for e in result.entries:
            if e.status != "gap":
                continue
            units = e.units if isinstance(e.units, list) else []
            self.ctx.add(
                level,
                1,
                "coverage",
                e.loc,
                f"{e.id} ({e.label}) is not {' or '.join(e.missing)} anywhere in the course; coverage is {pct:.0f}%",
                unit=units[0] if len(units) == 1 else "",
            )
        counts = result.counts()
        if counts["pending"]:
            self.ctx.add(
                "pending",
                1,
                "coverage",
                Loc("content/syllabus/a1-syllabus.yaml"),
                f"syllabus coverage {pct:.0f}% ({counts['covered']} of {len(result.required)} entries traced); "
                f"{counts['pending']} wait for incomplete units ({result.mode} mode; see build/reports/check.md)",
                unit="",
            )


def check_coverage(ctx: CheckContext) -> CoverageResult:
    return Coverage(ctx).run()
