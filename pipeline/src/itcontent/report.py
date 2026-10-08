"""`content report [--unit uNN]` (docs/04 § Commands): the content dashboard, as Markdown on stdout and in
`build/reports/report.md`. It never fails.

The report is a list of **section providers** (`SECTIONS`): functions that take the `ReportContext` (the repository
root, the unit filter and one run of `content check`) and return a `Section`, or None to leave it out. Register a new
one with `@section`; the order of registration is the order on the page. The built-in sections: overview, new words
per lesson, retrievals and encounters, strand split, syllabus coverage, budgets and exemptions, open review comments
(from the ledgers `reviews/<scope>.yaml`, read as documented in docs/04 § Content review loop), the audio budget (MB
per unit now and projected, M5.4) and the pronunciation overrides in use (M5.4).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths
from itcontent.checks import CheckResult, run_checks
from itcontent.checks.output import coverage_json, level_json, recycling_json, summary_line


def _map(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _seq(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def _natural(text: str) -> list[Any]:
    """Sort key that orders `#7` before `#13`."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def _md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


@dataclass
class Section:
    key: str
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ReportContext:
    root: Path
    unit: str | None
    check: CheckResult
    memo: dict[str, Any] = field(default_factory=dict)  # shared by sections (the compiled audio plan)

    def keep(self, unit: str | None) -> bool:
        return self.unit is None or unit == self.unit


SectionProvider = Callable[[ReportContext], Section | None]
SECTIONS: list[SectionProvider] = []


def section(fn: SectionProvider) -> SectionProvider:
    SECTIONS.append(fn)
    return fn


# ---------------------------------------------------------------- built-in sections


@section
def overview(rc: ReportContext) -> Section:
    ctx = rc.check.ctx
    lines = [summary_line(rc.check), ""]
    lines += [
        "| Unit | Lessons | Task | Check | Items (spec) | Status |",
        "|---|---|---|---|---|---|",
    ]
    for u in ctx.course.units:
        if not rc.keep(u.id):
            continue
        n_items = sum(1 for i, unit in ctx.item_unit.items() if unit == u.id and not i.startswith("s:"))
        want = _map(_map(u.spec.data).get("items")).get("new_words", "?") if u.spec else "?"
        status = "complete" if u.complete else "pending"
        lines.append(
            f"| {u.id} | {len(u.lessons)}/{u.lesson_count} | {'✓' if u.task else '—'} | {'✓' if u.check else '—'} "
            f"| {n_items} ({want}) | {status} |"
        )
    return Section("overview", "Overview", lines)


@section
def new_words(rc: ReportContext) -> Section:
    ctx = rc.check.ctx
    per_step: dict[str, list[str]] = {}
    for ref, intros in sorted(ctx.intros.by_ref.items()):
        if not ref.startswith(("w:", "c:")):
            continue
        written = [x for x in intros if not x.fallback]
        if written:
            per_step.setdefault(written[0].step, []).append(ref)
    lines: list[str] = []
    for step in sorted(per_step, key=lambda s: ctx.steps[s].pos if s in ctx.steps else (0, 0, 0)):
        st = ctx.steps.get(step)
        if st is None or not rc.keep(st.unit):
            continue
        refs = per_step[step]
        lines.append(f"- **{step}** ({len(refs)}): {', '.join(refs)}")
    return Section("new-words", "New words per step", lines or ["No written step introduces items yet."])


@section
def retrievals_and_encounters(rc: ReportContext) -> Section:
    data = recycling_json(rc.check) or {"items": []}
    items = [i for i in data["items"] if rc.keep(i["unit"])]
    if not items:
        return Section("encounters", "Retrievals and encounters", ["No item is introduced in a written lesson yet."])
    lines = [
        "Lowest first. Retrievals count in the introducing lesson (P items need 4); encounters run from the "
        "introduction to course end (P items need 10, R items 6) and are judged once the course is complete from the "
        "item's unit on.",
        "",
        "| Item | Status | Lesson | Retrievals | Encounters |",
        "|---|---|---|---|---|",
    ]
    for i in sorted(items, key=lambda i: (i["retrievals"] if i["retrievals"] is not None else 99, i["encounters"])):
        r = "—" if i["retrievals"] is None else i["retrievals"]
        lines.append(f"| {i['id']} | {i['status']} | {i['lesson'] or '—'} | {r} | {i['encounters']} |")
    return Section("encounters", "Retrievals and encounters", lines)


@section
def strands(rc: ReportContext) -> Section:
    data = recycling_json(rc.check) or {"units": []}
    units = [u for u in data["units"] if rc.keep(u["id"])]
    if not units:
        return Section("strands", "Strand split", ["No unit has written steps yet."])
    lines = [
        "Estimated minutes per strand (checker.yaml durations; the check is not counted). Each strand should be "
        "15–35% of a complete unit.",
        "",
        "| Unit | Input | Language focus | Output | Fluency | Total | Earlier-unit content words |",
        "|---|---|---|---|---|---|---|",
    ]
    for u in units:
        cells = [
            f"{u['minutes'][k]:.0f} ({u['shares'][k]:.0%})" for k in ("input", "language-focus", "output", "fluency")
        ]
        rec = "—" if u["recycled"] is None else f"{u['recycled']:.0%}"
        total = sum(u["minutes"].values())
        lines.append(f"| {u['id']}{'' if u['complete'] else '*'} | {' | '.join(cells)} | {total:.0f} | {rec} |")
    lines += ["", "\\* incomplete unit: estimates only."]
    return Section("strands", "Strand split", lines)


@section
def coverage(rc: ReportContext) -> Section:
    data = coverage_json(rc.check)
    if data is None:
        return Section("coverage", "Syllabus coverage", ["Not computed."])
    entries = [e for e in data["entries"] if not rc.unit or e["units"] == "all" or rc.unit in e["units"]]
    by_area: dict[str, dict[str, int]] = {}
    for e in entries:
        by_area.setdefault(e["area"], {"covered": 0, "gap": 0, "pending": 0, "info": 0})[e["status"]] += 1
    lines = [
        f"{data['percent']:.0f}% of the course's entries are traced to introduced, practised and assessed "
        f"(`coverage_mode: {data['mode']}`). The full table is in `build/reports/check.md`.",
        "",
        "| Area | Covered | Gaps | Pending | Information |",
        "|---|---|---|---|---|",
    ]
    for area, c in sorted(by_area.items()):
        lines.append(f"| {area} | {c['covered']} | {c['gap']} | {c['pending']} | {c['info']} |")
    gaps = [e for e in entries if e["status"] == "gap"]
    if gaps:
        lines += ["", "Gaps:", *[f"- {e['id']}: not {' or '.join(e['missing'])}" for e in gaps]]
    return Section("coverage", "Syllabus coverage", lines)


@section
def budgets(rc: ReportContext) -> Section:
    lv = level_json(rc.check)
    rec = recycling_json(rc.check) or {"stories": []}
    ctx = rc.check.ctx
    lines = ["| Text | Kind | Words | New + recognise | Share | Max |", "|---|---|---|---|---|---|"]
    rows = [b for b in lv["budgets"] if rc.keep(ctx.unit_of_file(b["file"]))]
    for b in rows:
        lines.append(
            f"| {b['text']} | {b['kind']} | {b['words']} | {b['new']} + {b['recognise']} | {b['share']:.1%} "
            f"| {b['max']:.0%} |"
        )
    if not rows:
        lines = ["No texts yet."]
    stories = [s for s in rec["stories"] if rc.keep(s["unit"])]
    if stories:
        lines += ["", "Story length: " + "; ".join(f"{s['text']} {s['words']} words" for s in stories)]
    ex = [x for x in lv["exemptions"] if rc.keep(ctx.unit_of_file(x["file"]))]
    lines += ["", "Exempt lines (`allow`, `recognise`):", ""]
    lines += [f"- {x['kind']} · {x['ref']}: “{_md(x['text'])}” — {_md(x['detail'])}" for x in ex] or ["- none"]
    return Section("budgets", "Budgets and exemptions", lines)


@section
def open_comments(rc: ReportContext) -> Section:
    """Unresolved comments (`open`, `owner`) from the review ledgers, read by the review loop's own module."""
    from itcontent.ledger import report_lines

    return Section("comments", "Open review comments", report_lines(rc.root, rc.unit)[2:])  # minus its heading


def audio_plan(rc: ReportContext) -> Any:
    """The dev pack's audio needs, resolved against the render caches (compiled once per report), or the error."""
    if "audio" not in rc.memo:
        from itcontent.audio_assets import AudioPlan, AudioResolver
        from itcontent.pack.build import AudioOptions, select_scope
        from itcontent.pack.common import Report
        from itcontent.pack.compile import Compiler
        from itcontent.pack.locks import Locks

        course = rc.check.ctx.course
        options = AudioOptions.default(rc.root, "dev")
        plan = AudioPlan(AudioResolver(options.caches, options.encode_dir))
        try:
            report = Report()
            scope = select_scope(course, "dev", allow_partial=False, report=report)
            Compiler(course, Locks(rc.root), scope, report, plan).compile()
            rc.memo["audio"] = plan
        except Exception as exc:  # the report never fails
            rc.memo["audio"] = f"{type(exc).__name__}: {exc}"
    return rc.memo["audio"]


@section
def audio_budget(rc: ReportContext) -> Section:
    """MB per unit: the audio that exists, and the projection for the complete course (docs/04, M5.4)."""
    from itcontent import audio_budget as budget
    from itcontent.pack.build import ENCODE_CACHE

    plan = audio_plan(rc)
    if isinstance(plan, str):
        return Section("audio", "Audio budget", [f"Not computed: the pack doesn't compile ({_md(plan)})."])
    encoded = rc.root / ENCODE_CACHE
    files = {p.name: p for p in encoded.glob("*.m4a")} if encoded.is_dir() else {}
    projection = budget.project(rc.check.ctx.course, plan, files)
    return Section("audio", "Audio budget", budget.report_lines(projection, rc.unit))


@section
def pronunciation(rc: ReportContext) -> Section:
    """IPA overrides (docs/04 § Audio › Pronunciation): lexicon entries and line `say:` overrides, where they apply,
    and symbols that look wrong."""
    from itcontent.tts_needs import ipa_problem

    plan = audio_plan(rc)
    if isinstance(plan, str):
        return Section("pronunciation", "Pronunciation overrides", [f"Not computed ({_md(plan)})."])
    course = rc.check.ctx.course
    pron = course.singles.get("pronunciation")
    lexicon = _map(_map(pron.data if pron else None).get("lexicon"))
    by_word = {str(k).lower(): str(v) for k, v in lexicon.items()}
    used: dict[str, list[str]] = {}
    say_lines: list[str] = []
    for need in plan.needs.values():
        if not rc.keep(need.unit):
            continue
        for line in need.lines:
            for word, ipa in line.speech.overrides:
                if by_word.get(word.lower()) == ipa:
                    used.setdefault(word.lower(), []).append(line.label)
                else:
                    say_lines.append(f"- {line.label}: *{_md(word)}* → /{_md(ipa)}/ (line `say`)")
    lines = [
        "Words in `content/pronunciation.yaml` get their IPA wherever they are voiced; a line's `say:` overrides "
        "one line only. Changing either re-renders just the lines concerned (`content tts`).",
        "",
        "| Word | IPA | Voiced in | Check |",
        "|---|---|---|---|",
    ]
    for word, ipa in sorted(lexicon.items(), key=lambda kv: str(kv[0]).lower()):
        where = sorted(set(used.get(str(word).lower(), [])), key=_natural)
        shown = ", ".join(where[:5]) + (f" (+{len(where) - 5})" if len(where) > 5 else "") if where else "not used yet"
        lines.append(f"| {_md(word)} | /{_md(ipa)}/ | {shown} | {_md(ipa_problem(str(ipa)) or 'ok')} |")
    if not lexicon:
        lines.append("| — | — | — | — |")
    lines += ["", "Line overrides:", ""] + (sorted(set(say_lines)) or ["- none"])
    return Section("pronunciation", "Pronunciation overrides", lines)


# ---------------------------------------------------------------- the command


def build_report(root: Path | None = None, *, unit: str | None = None) -> list[Section]:
    root = (root or paths.ROOT).resolve()
    rc = ReportContext(root, unit, run_checks(root, unit=unit))
    return [s for fn in SECTIONS if (s := fn(rc)) is not None]


def render(sections: list[Section], unit: str | None = None) -> str:
    out = [f"# Content report{f' · {unit}' if unit else ''}", ""]
    for s in sections:
        out += [f"## {s.title}", "", *s.lines, ""]
    return "\n".join(out).rstrip() + "\n"


def run_report(
    root: Path | None = None, *, unit: str | None = None, echo: Callable[[str], Any] = print, write: bool = True
) -> int:
    from itcontent.course import load_course

    root = (root or paths.ROOT).resolve()
    # specs and assessments are review scopes: only their open review comments apply.
    if (
        unit is not None
        and unit not in ("specs", "assessments")
        and unit not in [u.id for u in load_course(root).units]
    ):
        echo(f"error: unknown unit {unit}")
        return 2
    text = render(build_report(root, unit=unit), unit)
    if write:
        reports = root / "build" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "report.md").write_text(text, encoding="utf-8")
    echo(text.rstrip("\n"))
    return 0
