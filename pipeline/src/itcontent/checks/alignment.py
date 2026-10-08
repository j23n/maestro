"""Check 4 · Alignment (docs/04), errors.

Rules about one written object apply as soon as its file exists:

- every exercise has at least one `cd:` or `sy:` tag;
- every `match` has as many `targets` as `pairs`;
- every note has at least two `examples` that are lines of its lesson's own texts (its story, or a listening or
  reading text of the lesson).

Rules about a whole unit apply only to **complete** units (every lesson, the task and the check written; docs/04
§ Partial content); an incomplete unit gets one *pending* line instead:

- every can-do of the unit has at least one learn exercise in the unit (lessons and task) and at least one exercise in
  the unit check tagged with it (the final review unit: the final check);
- the unit check covers listening, reading, writing and speaking (a non-empty section of each);
- every P grammar point of the unit is introduced by a note (docs/05 § Introductions).
"""

from __future__ import annotations

from typing import Any

from itcontent import ids
from itcontent.checks.context import TEXT_STEPS, CheckContext
from itcontent.course import ExerciseRef, Loc, UnitFiles, exercises, lesson_steps, walk_check, walk_notes

SKILL_SECTIONS = ("listening", "reading", "writing", "speaking")


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def tags(x: ExerciseRef) -> list[str]:
    return [t for t in _seq(x.data.get("tags")) if isinstance(t, str)]


def missing_parts(u: UnitFiles) -> list[str]:
    """What an incomplete unit still lacks, for its pending line."""
    have = {d.path.name for d in u.lessons}
    out = [f"lesson-{k}" for k in range(1, u.lesson_count + 1) if f"lesson-{k}.yaml" not in have]
    if not u.is_final_review:
        out += [name for name, doc in (("task", u.task), ("check", u.check)) if doc is None]
    return out


def pending_line(ctx: CheckContext, check: int, u: UnitFiles, what: str) -> None:
    loc = u.spec.loc if u.spec else Loc(f"content/units/{u.slug}/unit.yaml")
    missing = ", ".join(missing_parts(u)) or "its files"
    ctx.add("pending", check, "partial", loc, f"{u.id} is incomplete (missing {missing}): {what} once it is written")


class Alignment:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx

    def exercises(self) -> None:
        for x in exercises(self.ctx.course):
            if not any(t.startswith(("cd:", "sy:")) for t in tags(x)):
                self.ctx.add(
                    "error",
                    4,
                    "tags",
                    x.loc.child("tags") if "tags" in x.data else x.loc,
                    f"{x.id or 'this exercise'} has no cd: or sy: tag: tag the can-do or syllabus entry it trains",
                )
            if x.format == "match":
                targets, pairs = x.data.get("targets"), x.data.get("pairs")
                if isinstance(targets, list) and isinstance(pairs, list) and len(targets) != len(pairs):
                    self.ctx.add(
                        "error",
                        4,
                        "match",
                        x.loc.child("targets"),
                        f"{x.id}: {len(targets)} targets for {len(pairs)} pairs; targets[i] belongs to pairs[i]",
                    )

    def notes(self) -> None:
        for u in self.ctx.course.units:
            for doc in u.lessons:
                own: set[str] = set()
                for _, step in lesson_steps(doc):
                    if step.get("kind") in TEXT_STEPS and isinstance(_map(step.get("text")).get("id"), str):
                        own.add(step["text"]["id"])
                for note in walk_notes(doc, u.id):
                    refs: set[str] = set()
                    for block in _seq(note.data.get("body")):
                        for ex in _seq(_map(block).get("examples")):
                            line = ids.split_line_ref(ex) if isinstance(ex, str) else None
                            if line and line[0] in own:
                                refs.add(ex)
                    if len(refs) < 2:
                        where = ", ".join(sorted(own)) or "no text yet"
                        self.ctx.add(
                            "error",
                            4,
                            "note",
                            note.loc.child("body"),
                            f"note {note.id or '?'} has {len(refs)} example(s) from its lesson's story ({where}); it "
                            "needs at least 2 `examples: [<text>#n, …]`",
                        )

    def units(self) -> None:
        for u in self.ctx.course.units:
            if not u.spec:
                continue
            if not u.complete:
                pending_line(self.ctx, 4, u, "can-do coverage, the check's four skills and its notes are checked")
                continue
            self.can_dos(u)
            self.check_sections(u)
            self.notes_for_points(u)

    def unit_check(self, u: UnitFiles) -> list[ExerciseRef]:
        if u.is_final_review:
            final = self.ctx.course.assessments.get("final")
            return [x for x in walk_check(final, u.id, "final") if isinstance(x, ExerciseRef)] if final else []
        return [x for x in walk_check(u.check, u.id) if isinstance(x, ExerciseRef)] if u.check else []

    def can_dos(self, u: UnitFiles) -> None:
        assert u.spec is not None
        learn = [x for x in exercises(self.ctx.course) if x.unit_id == u.id and x.container in ("lesson", "task")]
        check = self.unit_check(u)
        for i, cd in enumerate(_seq(_map(u.spec.data).get("can_do"))):
            cid = _map(cd).get("id")
            if not isinstance(cid, str):
                continue
            loc = u.spec.loc.child("can_do", i, "id")
            if not any(cid in tags(x) for x in learn):
                self.ctx.add("error", 4, "can-do", loc, f"{cid} has no learn exercise in {u.id} tagged with it")
            if not any(cid in tags(x) for x in check):
                what = "the final check" if u.is_final_review else f"the {u.id} check"
                self.ctx.add("error", 4, "can-do", loc, f"{cid} has no exercise in {what} tagged with it")

    def check_sections(self, u: UnitFiles) -> None:
        doc = self.ctx.course.assessments.get("final") if u.is_final_review else u.check
        if doc is None:
            return
        have = {str(_map(s).get("id")) for s in _seq(_map(doc.data).get("sections")) if _seq(_map(s).get("exercises"))}
        missing = [s for s in SKILL_SECTIONS if s not in have]
        if missing:
            self.ctx.add(
                "error",
                4,
                "check",
                doc.loc.child("sections"),
                f"the {u.id} check doesn't cover {', '.join(missing)}: a unit check has listening, reading, writing "
                "and speaking items",
            )

    def notes_for_points(self, u: UnitFiles) -> None:
        for pid in sorted(self.ctx.points):
            if self.ctx.point_unit(pid) != u.id or self.ctx.point_status(pid) != "P":
                continue
            if not any(x.via == "note" for x in self.ctx.intros.written(pid)):
                self.ctx.add(
                    "error",
                    4,
                    "note",
                    self.ctx.point_loc.get(pid, Loc("content/grammar/points.yaml")),
                    f"{pid} is a P point of {u.id}, but no note in {u.id} introduces it "
                    "(list it in a note's `grammar`)",
                    unit=u.id,
                )

    def run(self) -> None:
        self.exercises()
        self.notes()
        self.units()


def check_alignment(ctx: CheckContext) -> None:
    Alignment(ctx).run()
