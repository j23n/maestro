"""The closure contract: is every A0–A2 thing actually taught, and taught
more than once?

This is docs/plans/07 §3 made executable. Coverage is not "some item
mentions it" — the old `coverage_report` in ``build_pack`` counts items
per grammar point, which says nothing about whether a learner ever meets
the point in a lesson, or meets it more than once, or is ever asked to
produce it without help.

Four rules apply to every axis (grammar, function, can-do, lemma):

1. **Introduced once** — exactly one lesson lists it under ``introduces``.
   Zero is an orphan; two is an ambiguous home.
2. **Passed at least three times** — it appears in >= 3 distinct lessons,
   counting its home, across ``introduces`` + ``revisits`` + ``capstones``.
3. **Rising, never falling** — ordered by the lessons' phase / sequence /
   depth, the demand rungs are non-decreasing.
4. **Reaches ``perform``** — the last pass is ``perform``, and the pack
   supplies a ``perform``-tier item carrying it.

Plus per-axis obligations on the home lesson (a grammar point's home owes
it a reference page and drills; a function's owes it a speaking prompt).

Everything is reported as counts with a bounded sample, because during
the spec fill the honest answer is "816 things have no home yet" and a
wall of 816 lines helps nobody. The counts are the countdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from authoring.spec_schemas import DEMAND_RANK, Spec

IN_SCOPE = ("A0", "A1", "A2")
MIN_PASSES = 3
# Mirrors folds.rs CANDO_FRACTION: a can-do closes on 80%% of its
# decomposition, so coverage has to hold the pack to the same bar.
CANDO_FRACTION = 0.8

# What a home lesson owes the thing it introduces.
DRILLS_PER_GRAMMAR_POINT = 6


@dataclass
class Pass:
    """One lesson's encounter with one spec id."""

    lesson_id: str
    order: tuple
    demand: str
    kind: str  # introduces | revisits | capstones


@dataclass
class Finding:
    """One violated rule, for one id."""

    rule: str
    axis: str
    id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.axis} {self.id}: {self.detail}"


@dataclass
class CoverageReport:
    findings: list[Finding] = field(default_factory=list)
    # axis -> total ids in scope
    totals: dict[str, int] = field(default_factory=dict)
    # axis -> ids meeting the whole contract
    covered: dict[str, int] = field(default_factory=dict)
    lessons: int = 0

    def by_rule(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.rule, []).append(f)
        return out

    @property
    def ok(self) -> bool:
        return not self.findings

    def summary(self) -> str:
        rows = [
            f"  {axis:<9} {self.covered.get(axis, 0):>4} / {total:<4} covered"
            for axis, total in sorted(self.totals.items())
        ]
        head = f"{self.lessons} lessons; A0-A2 coverage:"
        return "\n".join([head, *rows])


def _lesson_order(scenario, depth: int) -> tuple:
    """Curriculum order: phase, then the author's sequence, then depth.

    Scenarios without a `sequence` sort after those with one, by id, so
    the order is total and stable — rule 3 compares rungs along it.
    """
    return (
        scenario.phase,
        scenario.sequence if scenario.sequence is not None else 10**6,
        scenario.id,
        depth,
    )


def _collect_passes(spec: Spec) -> tuple[dict[str, dict[str, list[Pass]]], int]:
    """Every lesson's declared encounters, grouped axis -> id -> passes."""
    passes: dict[str, dict[str, list[Pass]]] = {
        "grammar": {},
        "function": {},
        "vocab": {},
        "cando": {},
    }
    n_lessons = 0

    def add(axis: str, spec_id: str, p: Pass) -> None:
        passes[axis].setdefault(spec_id, []).append(p)

    for scenario in spec.scenarios:
        for depth, lesson in enumerate(scenario.depths, 1):
            n_lessons += 1
            order = _lesson_order(scenario, depth)
            # An introduction is the first pass and always the bottom rung
            # for grammar and vocab; a function is introduced by being
            # used, which is why it enters one rung higher.
            for axis, ids, rung in (
                ("grammar", lesson.introduces.grammar, "meet"),
                ("function", lesson.introduces.functions, "use"),
                ("vocab", lesson.introduces.vocab, "meet"),
            ):
                for spec_id in ids:
                    add(axis, spec_id, Pass(lesson.id, order, rung, "introduces"))
            for axis, revisits in (
                ("grammar", lesson.revisits.grammar),
                ("function", lesson.revisits.functions),
                ("vocab", lesson.revisits.vocab),
            ):
                for r in revisits:
                    add(axis, r.id, Pass(lesson.id, order, r.demand, "revisits"))
            for c in lesson.capstones:
                add("cando", c.cando, Pass(lesson.id, order, c.demand, "capstones"))

    for axis in passes:
        for spec_id in passes[axis]:
            passes[axis][spec_id].sort(key=lambda p: p.order)
    return passes, n_lessons


def _index_items(items, statuses: frozenset[str]):
    """Pack supply, indexed the two ways the contract asks about it."""
    # (axis, id) -> set of demand rungs any item carrying it offers
    rungs: dict[tuple[str, str], set[str]] = {}
    # lesson_id -> item_type -> [(axis, id)] for the required-set clauses
    by_lesson: dict[str, dict[str, list[tuple[str, str]]]] = {}

    for item in items:
        if item.status not in statuses:
            continue
        demand = getattr(item, "demand", None)
        item_type = getattr(item, "item_type", None) or item.id.split(".", 1)[0]
        lesson_id = getattr(item, "lesson_id", None)
        for ev in item.evidence:
            key = (ev.axis, ev.id)
            if demand:
                rungs.setdefault(key, set()).add(demand)
            if lesson_id:
                by_lesson.setdefault(lesson_id, {}).setdefault(item_type, []).append(
                    key
                )
        # Questions inside a passage are `meet` supply for the passage's
        # own evidence; they are built as separate items but authored here.
        for _ in getattr(item, "questions", []) or []:
            for ev in item.evidence:
                rungs.setdefault((ev.axis, ev.id), set()).add("meet")
    return rungs, by_lesson


def check_coverage(
    spec: Spec,
    items: list,
    *,
    statuses: frozenset[str] = frozenset({"reviewed"}),
    in_scope: tuple[str, ...] = IN_SCOPE,
    min_passes: int = MIN_PASSES,
) -> CoverageReport:
    report = CoverageReport()
    passes, report.lessons = _collect_passes(spec)
    rungs, by_lesson = _index_items(items, statuses)

    inventory = {
        "grammar": [g for g in spec.grammar_points if g.cefr_level in in_scope],
        "function": [
            c for c in spec.communicative_functions if c.cefr_level in in_scope
        ],
        "vocab": [v for v in spec.vocab if v.cefr_level in in_scope],
        "cando": [c for c in spec.can_dos if c.cefr_level in in_scope],
    }

    for axis, entries in inventory.items():
        report.totals[axis] = len(entries)
        covered = 0
        for entry in entries:
            findings = _check_one(
                axis, entry.id, passes[axis].get(entry.id, []), rungs, min_passes
            )
            # A can-do is capstoned, never "introduced" — rule 1 doesn't
            # apply to it, and rule 2 counts capstones instead.
            report.findings.extend(findings)
            if not findings:
                covered += 1
        report.covered[axis] = covered

    report.findings.extend(_check_home_obligations(spec, by_lesson))
    report.findings.extend(_check_cando_decomposition(spec, passes, in_scope))
    return report


def _check_cando_decomposition(spec: Spec, passes, in_scope) -> list[Finding]:
    """A can-do closes on evidence, not on its capstone alone.

    ``folds.rs`` also requires 80% of the descriptor's grammar mastered
    and 80% of its functions demonstrated, so a lesson can ship a perfect
    capstone for a can-do whose decomposition nothing has taught yet and
    the learner still never sees it achieved. That is a coverage gap, not
    a runtime one: it has to be visible here.
    """
    homes = {
        axis: {
            spec_id: min(p.order for p in ps if p.kind == "introduces")
            for spec_id, ps in by_id.items()
            if any(p.kind == "introduces" for p in ps)
        }
        for axis, by_id in passes.items()
    }
    out: list[Finding] = []
    for cd in spec.can_dos:
        if cd.cefr_level not in in_scope:
            continue
        capstones = passes["cando"].get(cd.id, [])
        if not capstones:
            continue  # already reported as an orphan
        by = max(p.order for p in capstones)
        missing = [
            f"{axis} {spec_id}"
            for axis, ids in (
                ("grammar", cd.grammar_ids),
                ("function", cd.function_ids),
            )
            for spec_id in ids
            if homes[axis].get(spec_id, (float("inf"),)) > by
        ]
        total = len(cd.grammar_ids) + len(cd.function_ids)
        taught = total - len(missing)
        if total and taught < total * CANDO_FRACTION:
            out.append(
                Finding(
                    "decomposition-untaught",
                    "cando",
                    cd.id,
                    f"capstoned by {capstones[-1].lesson_id} but {taught}/{total} of "
                    f"its decomposition is taught by then — missing: "
                    + ", ".join(missing),
                )
            )
    return out


def _check_one(
    axis: str,
    spec_id: str,
    my_passes: list[Pass],
    rungs: dict[tuple[str, str], set[str]],
    min_passes: int,
) -> list[Finding]:
    out: list[Finding] = []

    if axis != "cando":
        homes = [p for p in my_passes if p.kind == "introduces"]
        if not homes:
            out.append(Finding("orphan", axis, spec_id, "no lesson introduces it"))
        elif len(homes) > 1:
            out.append(
                Finding(
                    "ambiguous-home",
                    axis,
                    spec_id,
                    "introduced by " + ", ".join(p.lesson_id for p in homes),
                )
            )

    if not my_passes:
        # Already reported as an orphan for the other axes; for can-dos
        # this is the equivalent finding.
        if axis == "cando":
            out.append(Finding("orphan", axis, spec_id, "no lesson capstones it"))
        return out

    if len(my_passes) < min_passes:
        out.append(
            Finding(
                "too-few-passes",
                axis,
                spec_id,
                f"met in {len(my_passes)} lesson(s), needs {min_passes}: "
                + ", ".join(p.lesson_id for p in my_passes),
            )
        )

    ranks = [DEMAND_RANK[p.demand] for p in my_passes]
    if any(b < a for a, b in zip(ranks, ranks[1:])):
        out.append(
            Finding(
                "falling-demand",
                axis,
                spec_id,
                "rungs go backwards: "
                + " -> ".join(f"{p.lesson_id}:{p.demand}" for p in my_passes),
            )
        )

    if my_passes[-1].demand != "perform":
        out.append(
            Finding(
                "never-performed",
                axis,
                spec_id,
                f"last pass is {my_passes[-1].demand} in {my_passes[-1].lesson_id} — "
                "nothing ever asks the learner to produce it unaided",
            )
        )
    elif "perform" not in rungs.get((axis, spec_id), set()):
        out.append(
            Finding(
                "no-perform-supply",
                axis,
                spec_id,
                f"{my_passes[-1].lesson_id} revisits it at perform, but the pack "
                "has no perform-tier item carrying it",
            )
        )
    return out


def _check_home_obligations(spec: Spec, by_lesson) -> list[Finding]:
    """What a lesson owes the things it introduces (docs/plans/07 §2).

    Only the home lesson's obligations are checked here. Revisit slots
    draw pack-wide by (axis id x rung), so their supply is rule 4's
    `no-perform-supply` rather than anything lesson-local — that is the
    economy that keeps the spiral from tripling the content bill.
    """
    out: list[Finding] = []
    for scenario in spec.scenarios:
        for lesson in scenario.depths:
            supply = by_lesson.get(lesson.id, {})
            refs = {gid for _, gid in supply.get("grammar_ref", [])}
            drills = [
                gid
                for t, keys in supply.items()
                if t.startswith("drill_")
                for axis, gid in keys
                if axis == "grammar"
            ]
            speaking = {
                fid
                for axis, fid in supply.get("speaking_prompt", [])
                if axis == "function"
            }
            cards = {
                lemma for axis, lemma in supply.get("vocab_card", []) if axis == "vocab"
            }

            for gid in lesson.introduces.grammar:
                if gid not in refs:
                    out.append(
                        Finding(
                            "home-missing-reference",
                            "grammar",
                            gid,
                            f"{lesson.id} introduces it with no grammar_ref",
                        )
                    )
                if drills.count(gid) < DRILLS_PER_GRAMMAR_POINT:
                    out.append(
                        Finding(
                            "home-missing-drills",
                            "grammar",
                            gid,
                            f"{lesson.id} has {drills.count(gid)} drills for it, "
                            f"needs {DRILLS_PER_GRAMMAR_POINT}",
                        )
                    )
            for fid in lesson.introduces.functions:
                if fid not in speaking:
                    out.append(
                        Finding(
                            "home-missing-speaking",
                            "function",
                            fid,
                            f"{lesson.id} introduces it with no speaking prompt",
                        )
                    )
            for lemma in lesson.introduces.vocab:
                if lemma not in cards:
                    out.append(
                        Finding(
                            "home-missing-card",
                            "vocab",
                            lemma,
                            f"{lesson.id} introduces it with no vocab card",
                        )
                    )
            for capstone in lesson.capstones:
                tasks = {cid for axis, cid in supply.get("task", []) if axis == "cando"}
                if capstone.cando not in tasks:
                    out.append(
                        Finding(
                            "missing-capstone-task",
                            "cando",
                            capstone.cando,
                            f"{lesson.id} capstones it with no task item — "
                            "nothing can move it to achieved",
                        )
                    )
    return out


def format_report(report: CoverageReport, *, sample: int = 5) -> str:
    """Counts first, a few examples per rule, never the whole wall."""
    lines = [report.summary()]
    by_rule = report.by_rule()
    if not by_rule:
        lines.append("  contract satisfied")
        return "\n".join(lines)
    lines.append("")
    for rule, findings in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {rule}: {len(findings)}")
        for f in findings[:sample]:
            lines.append(f"      {f}")
        if len(findings) > sample:
            lines.append(f"      ... and {len(findings) - sample} more")
    return "\n".join(lines)
