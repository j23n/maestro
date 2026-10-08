"""`build/reports/check.json` and `check.md`: the findings plus what the checks measured (docs/04 § Commands).

Both are deterministic (no timestamps; rows sorted), so two runs on the same content give the same bytes. The JSON is
`{format, scope, summary, units, findings, level_gate, coverage, recycling}`; each check that measures something adds
its own key (`JSON_EXTRAS`) and Markdown section (`SECTIONS`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from itcontent.checks.alignment import missing_parts
from itcontent.findings import format_path

if TYPE_CHECKING:
    from itcontent.checks import CheckResult

FORMAT = 1
CHECK_NAMES = {
    0: "Inputs (parse errors, annotation lock files)",
    1: "Check 1 · Syllabus coverage",
    2: "Check 2 · Level gate",
    3: "Check 3 · Recycling and balance",
    4: "Check 4 · Alignment",
    5: "Check 5 · Story consistency",
}


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def summary_line(result: CheckResult) -> str:
    s = result.summary()
    scope = f" ({result.unit})" if result.unit else ""
    extra = "".join(f"; {fn(result)}" for fn in SUMMARY_EXTRAS if fn(result))
    return f"check{scope}: {s['error']} error(s), {s['warning']} warning(s), {s['pending']} pending{extra}"


# ---------------------------------------------------------------- JSON


def units_json(result: CheckResult) -> list[dict[str, Any]]:
    out = []
    for u in result.ctx.course.units:
        if result.unit and u.id != result.unit:
            continue
        out.append(
            {
                "id": u.id,
                "complete": u.complete,
                "lessons": {"written": len(u.lessons), "planned": u.lesson_count},
                "task": u.task is not None,
                "check": u.check is not None,
                "missing": [] if u.complete else missing_parts(u),
            }
        )
    return out


def level_json(result: CheckResult) -> dict[str, Any]:
    unit = result.unit
    ctx = result.ctx
    return {
        "budgets": [
            {
                "text": b.text,
                "file": b.file,
                "path": format_path(b.path),
                "kind": b.kind,
                "words": b.words,
                "new": b.new,
                "recognise": b.recognise,
                "share": round(b.share, 4),
                "max": b.limit,
            }
            for b in result.level.budgets
            if not unit or ctx.unit_of_file(b.file) == unit
        ],
        "exemptions": [
            {
                "kind": x.kind,
                "ref": x.ref,
                "file": x.file,
                "path": format_path(x.path),
                "text": x.text,
                "detail": x.detail,
            }
            for x in result.level.exemptions
            if not unit or ctx.unit_of_file(x.file) == unit
        ],
    }


def _hit(hits: list[Any]) -> dict[str, Any] | None:
    if not hits:
        return None
    return {"ref": hits[0].ref, "unit": hits[0].unit, "via": hits[0].via, "count": len(hits)}


def coverage_entries(result: CheckResult) -> list[Any]:
    cov = result.coverage
    if cov is None:
        return []
    unit = result.unit
    return [e for e in cov.entries if not unit or e.units == "all" or unit in e.units]


def coverage_json(result: CheckResult) -> dict[str, Any] | None:
    cov = result.coverage
    if cov is None:
        return None
    return {
        "mode": cov.mode,
        "percent": round(cov.percent, 1),
        "counts": cov.counts(),
        "entries": [
            {
                "id": e.id,
                "label": e.label,
                "area": e.area,
                "units": e.units,
                "roles": list(e.roles),
                "status": e.status,
                "missing": e.missing,
                **{role: _hit(e.hits.get(role, [])) for role in ("introduced", "practised", "assessed")},
            }
            for e in coverage_entries(result)
        ],
    }


def recycling_json(result: CheckResult) -> dict[str, Any] | None:
    rec = result.recycling
    if rec is None:
        return None
    unit = result.unit

    def keep(u: str) -> bool:
        return not unit or u == unit

    return {
        "items": [
            {
                "id": i.id,
                "unit": i.unit,
                "status": i.status,
                "lesson": i.lesson,
                "encounters": i.encounters,
                "encounters_judged": i.judged,
                "retrievals": i.retrievals,
            }
            for i in rec.items
            if keep(i.unit)
        ],
        "units": [
            {
                "id": u.id,
                "complete": u.complete,
                "minutes": {k: round(v / 60, 1) for k, v in u.seconds.items()},
                "shares": {k: round(u.share(k), 3) for k in u.seconds},
                "content_tokens": u.content_tokens,
                "earlier_unit_tokens": u.earlier_tokens,
                "recycled": None if u.recycled is None else round(u.recycled, 3),
            }
            for u in rec.units
            if keep(u.id) and u.total
        ],
        "stories": [
            {"text": st.text, "unit": st.unit, "words": st.words, "range": [st.low, st.high]}
            for st in rec.stories
            if keep(st.unit)
        ],
        "spiral": {
            p: later for p, later in rec.spiral.items() if keep(result.ctx.point_unit(p)) and (later or not unit)
        },
    }


def coverage_summary(result: CheckResult) -> str:
    cov = result.coverage
    return f"syllabus coverage {cov.percent:.0f}% ({cov.mode} mode)" if cov else ""


JSON_EXTRAS: list[tuple[str, Callable[[CheckResult], Any]]] = [
    ("level_gate", level_json),
    ("coverage", coverage_json),
    ("recycling", recycling_json),
]
SUMMARY_EXTRAS: list[Callable[[CheckResult], str]] = [coverage_summary]


def to_json(result: CheckResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "format": FORMAT,
        "scope": result.unit or "all",
        "summary": result.summary(),
        "units": units_json(result),
        "findings": [f.as_dict() for f in result.findings],
    }
    for key, fn in JSON_EXTRAS:
        out[key] = fn(result)
    return out


# ---------------------------------------------------------------- Markdown


def findings_md(result: CheckResult) -> list[str]:
    lines: list[str] = []
    by_check: dict[int, list[Any]] = {}
    for f in result.findings:
        by_check.setdefault(f.check, []).append(f)
    if not by_check:
        return ["No findings."]
    for check in sorted(by_check):
        fs = by_check[check]
        counts = ", ".join(f"{sum(1 for f in fs if f.level == lv)} {lv}" for lv in ("error", "warning", "pending"))
        lines += [f"### {CHECK_NAMES.get(check, f'Check {check}')} ({counts})", ""]
        for f in sorted(fs, key=lambda f: (("error", "warning", "pending").index(f.level), *f.sort_key())):
            where = f"`{f.file}`" + (f" › `{f.where}`" if f.where else "") + (f" (line {f.line})" if f.line else "")
            lines.append(f"- **{f.level}** · {f.rule} · {where}: {_md(f.message)}")
        lines.append("")
    return lines


def units_md(result: CheckResult) -> list[str]:
    lines = ["| Unit | Lessons | Task | Check | Status |", "|---|---|---|---|---|"]
    for u in units_json(result):
        status = "complete" if u["complete"] else "pending: missing " + ", ".join(u["missing"])
        lines.append(
            f"| {u['id']} | {u['lessons']['written']}/{u['lessons']['planned']} | {'✓' if u['task'] else '—'} "
            f"| {'✓' if u['check'] else '—'} | {status} |"
        )
    return lines


def level_md(result: CheckResult) -> list[str]:
    data = level_json(result)
    lines = ["**New-token budget** (new in this step + recognise, over word tokens)", ""]
    if data["budgets"]:
        lines += ["| Text | Kind | Words | New | Recognise | Share | Max |", "|---|---|---|---|---|---|---|"]
        for b in data["budgets"]:
            flag = " ⚠" if b["share"] > b["max"] else ""
            lines.append(
                f"| {b['text']} | {b['kind']} | {b['words']} | {b['new']} | {b['recognise']} "
                f"| {b['share']:.1%}{flag} | {b['max']:.0%} |"
            )
    else:
        lines.append("No texts.")
    lines += ["", "**Exempt lines** (`allow:` skips the morphology gate; `recognise` forms skip every gate)", ""]
    if data["exemptions"]:
        for x in data["exemptions"]:
            lines.append(f"- {x['kind']} · {x['ref']}: “{_md(x['text'])}” — {_md(x['detail'])}")
    else:
        lines.append("None.")
    return lines


def coverage_md(result: CheckResult) -> list[str]:
    data = coverage_json(result)
    if data is None:
        return ["Not computed."]
    c = data["counts"]
    lines = [
        f"{data['percent']:.0f}% of the entries with roles are fully traced ({c['covered']} covered, {c['gap']} gaps, "
        f"{c['pending']} pending on incomplete units, {c['info']} information only); mode `{data['mode']}`. Each "
        "cell is the first step, exercise or item that satisfies the role (course order), with the number of others.",
        "",
        "| Entry | Label | Introduced | Practised | Assessed | Status |",
        "|---|---|---|---|---|---|",
    ]
    for e in data["entries"]:
        cells = []
        for role in ("introduced", "practised", "assessed"):
            h = e[role]
            if role not in e["roles"]:
                cells.append("n/a")
            elif h is None:
                cells.append("—")
            else:
                cells.append(f"{h['ref']}" + (f" (+{h['count'] - 1})" if h["count"] > 1 else ""))
        lines.append(f"| {e['id']} | {_md(e['label'])} | {' | '.join(cells)} | {e['status']} |")
    return lines


def recycling_md(result: CheckResult) -> list[str]:
    data = recycling_json(result)
    if data is None:
        return ["Not computed."]
    lines = ["**Retrievals in the introducing lesson** (P items need 4; preview counts 2)", ""]
    rows = sorted((i for i in data["items"] if i["retrievals"] is not None), key=lambda i: (i["retrievals"], i["id"]))
    if rows:
        lines += ["| Item | Status | Lesson | Retrievals |", "|---|---|---|---|"]
        lines += [f"| {i['id']} | {i['status']} | {i['lesson']} | {i['retrievals']} |" for i in rows]
    else:
        lines.append("No item's lesson is written yet.")
    lines += ["", "**Encounters** (introduction to course end; judged once the rest of the course is complete)", ""]
    rows = sorted(data["items"], key=lambda i: (i["encounters"], i["id"]))
    if rows:
        lines += ["| Item | Status | Encounters | Judged |", "|---|---|---|---|"]
        lines += [
            f"| {i['id']} | {i['status']} | {i['encounters']} | {'yes' if i['encounters_judged'] else 'not yet'} |"
            for i in rows
        ]
    else:
        lines.append("No item is introduced in a written lesson yet.")
    lines += ["", "**Strand balance and recycling** (estimated minutes; the check is not counted)", ""]
    if data["units"]:
        lines += [
            "| Unit | Input | Language focus | Output | Fluency | Earlier-unit content words |",
            "|---|---|---|---|---|---|",
        ]
        for u in data["units"]:
            cells = [f"{u['minutes'][k]:.0f} min ({u['shares'][k]:.0%})" for k in STRAND_ORDER]
            rec = "—" if u["recycled"] is None else f"{u['recycled']:.0%} of {u['content_tokens']}"
            lines.append(f"| {u['id']}{'' if u['complete'] else ' (incomplete)'} | {' | '.join(cells)} | {rec} |")
    else:
        lines.append("No unit has written steps yet.")
    lines += ["", "**Story length**", ""]
    if data["stories"]:
        for st in data["stories"]:
            rng = f"{st['range'][0]}–{st['range'][1]}" if st["range"][0] is not None else "no range in the spec"
            lines.append(f"- {st['text']}: {st['words']} words ({rng})")
    else:
        lines.append("No stories yet.")
    returning = {p: later for p, later in data["spiral"].items() if later}
    lines += ["", "**Grammar spiral** (later units where a point returns)", ""]
    lines += [f"- {p}: {', '.join(later)}" for p, later in sorted(returning.items())] or ["No point returns yet."]
    return lines


STRAND_ORDER = ("input", "language-focus", "output", "fluency")

SECTIONS: list[tuple[str, Callable[[CheckResult], list[str]]]] = [
    ("Findings", findings_md),
    ("Units", units_md),
    ("Syllabus coverage (check 1)", coverage_md),
    ("Level gate (check 2)", level_md),
    ("Recycling and balance (check 3)", recycling_md),
]


def to_markdown(result: CheckResult) -> str:
    s = result.summary()
    scope = result.unit or "all units"
    head = [
        "# Content check",
        "",
        f"Scope: {scope} · {s['error']} error(s) · {s['warning']} warning(s) · {s['pending']} pending"
        + "".join(f" · {fn(result)}" for fn in SUMMARY_EXTRAS if fn(result)),
        "",
        "Generated by `content check` (docs/04 § The ten quality checks). Errors fail the build; warnings and pending "
        "lines never do.",
        "",
    ]
    body: list[str] = []
    for title, fn in SECTIONS:
        body += [f"## {title}", "", *fn(result), ""]
    return "\n".join(head + body).rstrip() + "\n"
