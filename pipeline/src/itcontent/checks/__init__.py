"""`content check [--unit uNN] [--json]` (docs/04 § Commands, § The ten quality checks): automatic checks 1–5.

The checks read the course and its annotation lock files (`checks.context`), then run in order: 2 (level gate,
`level`), 4 (alignment, `alignment`) and 5 (story consistency, `story`). Every run writes
`build/reports/check.json` and `build/reports/check.md` (`output`); `--json` also prints the JSON. Errors fail the
command; warnings and pending lines never do. `--unit uNN` keeps the findings about that unit (the checks still read
the whole course, because positions and introductions depend on earlier units).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths
from itcontent.checks.alignment import check_alignment
from itcontent.checks.context import CheckContext, CheckFinding, load_context
from itcontent.checks.level import LevelResult, check_level
from itcontent.checks.story import check_story

LEVELS = ("error", "warning", "pending")


@dataclass
class CheckResult:
    ctx: CheckContext
    findings: list[CheckFinding]
    unit: str | None = None
    level: LevelResult = field(default_factory=LevelResult)

    @property
    def errors(self) -> list[CheckFinding]:
        return [f for f in self.findings if f.level == "error"]

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {lv: sum(1 for f in self.findings if f.level == lv) for lv in LEVELS}
        by_check: dict[str, dict[str, int]] = {}
        for f in self.findings:
            by = by_check.setdefault(str(f.check), dict.fromkeys(LEVELS, 0))
            by[f.level] += 1
        out["by_check"] = dict(sorted(by_check.items()))
        return out


def in_scope(f: CheckFinding, unit: str | None) -> bool:
    return unit is None or f.unit == unit


def run_checks(root: Path | None = None, *, unit: str | None = None) -> CheckResult:
    ctx = load_context(root)
    level = check_level(ctx)
    check_alignment(ctx)
    check_story(ctx)
    findings = [f for f in ctx.with_lines(ctx.findings) if in_scope(f, unit)]
    return CheckResult(ctx, findings, unit, level)


def check_errors_for(root: Path, rel: str) -> list[CheckFinding]:
    """The check errors about one file (`content approve` refuses while there are any)."""
    return [f for f in run_checks(root).findings if f.level == "error" and f.file == rel]


def run_check(
    root: Path | None = None,
    *,
    unit: str | None = None,
    as_json: bool = False,
    echo: Callable[[str], Any] = print,
    write: bool = True,
) -> int:
    from itcontent.checks import output

    root = (root or paths.ROOT).resolve()
    if unit is not None:
        from itcontent.course import load_course

        known = [u.id for u in load_course(root).units]
        if unit not in known:
            echo(f"error: unknown unit {unit} (course units: {', '.join(known)})")
            return 2
    result = run_checks(root, unit=unit)
    data = output.to_json(result)
    if write:
        reports = root / "build" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "check.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (reports / "check.md").write_text(output.to_markdown(result), encoding="utf-8")
    if as_json:
        echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for f in result.findings:
            echo(str(f))
        echo(output.summary_line(result))
    return 1 if result.errors else 0
