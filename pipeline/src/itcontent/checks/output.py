"""`build/reports/check.json` and `check.md`: the findings plus what the checks measured (docs/04 § Commands).

Both are deterministic (no timestamps; rows sorted), so two runs on the same content give the same bytes. The JSON is
`{format, scope, summary, units, findings, level_gate, …}`; each check that measures something adds its own key and
Markdown section through `SECTIONS`.
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
            {"kind": x.kind, "ref": x.ref, "file": x.file, "path": format_path(x.path), "text": x.text, "detail": x.detail}
            for x in result.level.exemptions
            if not unit or ctx.unit_of_file(x.file) == unit
        ],
    }


JSON_EXTRAS: list[tuple[str, Callable[[CheckResult], Any]]] = [("level_gate", level_json)]
SUMMARY_EXTRAS: list[Callable[[CheckResult], str]] = []


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


SECTIONS: list[tuple[str, Callable[[CheckResult], list[str]]]] = [
    ("Findings", findings_md),
    ("Units", units_md),
    ("Level gate (check 2)", level_md),
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
