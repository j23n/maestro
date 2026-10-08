"""`content build [--release] [--allow-partial] [--mini] [--out PATH]` and `content pack-hash` (docs/04 § Pack build).

- **dev** (default): every unit, drafts included (`steps.draft = 1` for unapproved files), missing audio is a
  warning; writes `App/Italiano/Resources/Content/content.sqlite` (gitignored) with `meta.review_files` for the app's
  review mode.
- **--release**: only approved content. Every unit in `course.yaml` must be complete (all lessons, task and check)
  and approved, as must its items file and the course-wide files the content lead signs off (syllabus, grammar
  points, story bible, countries); `--allow-partial` ships the longest prefix of such units instead. Missing audio is
  an error. Writes `build/release/content.sqlite` and records the released IDs in `content/ids.lock`.
- **--mini**: the golden sample (Unit 2 Lesson 1 with its task and check, the catalog of Units 0–2, no assessments) as
  `fixtures/packs/mini.sqlite` plus `fixtures/packs/mini-payloads.json` (every step, exercise and note payload),
  both committed. It leaves out `meta.git_sha`, so the fixture changes only when its content does.

Every build first runs `content lint` (schema violations stop it), reads the annotation lock files (a stale one stops
it), validates every payload against `schemas/pack-payloads.schema.json` and checks every foreign key.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from itcontent import __version__, approval, paths
from itcontent.course import Course, Doc, load_course
from itcontent.pack import db
from itcontent.pack.common import BuildError, Report, cjson, mapping, pretty_json, seq
from itcontent.pack.compile import Compiler, PackData, Scope
from itcontent.pack.locks import Locks

MODES = ("dev", "release", "mini")
MINI_UNIT = "u02"
MINI_LESSONS = ("u02.l1",)
AUDIO_BUDGET_BYTES = 150 * 1024 * 1024
SIGNED_OFF = ("syllabus", "points", "story_bible", "countries")  # course-wide files with a review block
PAYLOAD_DEFS = {
    "exercises": "exercise",
    "steps": "stepPayload",
    "notes": "noteBody",
    "assessments": "assessment",
    "layouts": "layout",
}


def default_out(mode: str, root: Path) -> Path:
    return {
        "dev": root / "App" / "Italiano" / "Resources" / "Content" / "content.sqlite",
        "release": root / "build" / "release" / "content.sqlite",
        "mini": root / "fixtures" / "packs" / "mini.sqlite",
    }[mode]


@dataclass
class BuildResult:
    path: Path
    content_hash: str
    counts: dict[str, int]
    report: Report
    payloads_path: Path | None = None
    released_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- scope


def is_approved(doc: Doc | None) -> bool:
    return doc is not None and mapping(mapping(doc.data).get("review")).get("status") == "approved"


def unit_files(u) -> list[Doc]:
    return [d for d in (u.spec, *u.lessons, u.task, u.check, u.items) if d is not None]


def select_scope(course: Course, mode: str, *, allow_partial: bool, report: Report) -> Scope:
    docs = [*course.singles.values(), *course.assessments.values()]
    for u in course.units:
        docs += unit_files(u)
    approved = {d.rel: is_approved(d) for d in docs}
    units = [u for u in course.units if u.spec is not None]
    if mode == "dev":
        return Scope(
            "dev",
            units,
            {u.id: list(u.lessons) for u in units},
            {u.id: u.task for u in units if u.task},
            {u.id: u.check for u in units if u.check},
            dict(course.assessments),
            approved,
        )
    if mode == "mini":
        order = course.unit_order()
        catalog = [u for u in units if order[u.id] <= order[MINI_UNIT]]
        unit = course.unit(MINI_UNIT)
        if unit is None:
            raise BuildError(f"the mini pack needs unit {MINI_UNIT}")
        lessons = [d for d in unit.lessons if mapping(d.data).get("id") in MINI_LESSONS]
        if len(lessons) != len(MINI_LESSONS) or unit.task is None or unit.check is None:
            raise BuildError(f"the mini pack needs {', '.join(MINI_LESSONS)} and the task and check of {MINI_UNIT}")
        return Scope(
            "mini",
            catalog,
            {MINI_UNIT: lessons},
            {MINI_UNIT: unit.task},
            {MINI_UNIT: unit.check},
            {},  # the golden sample only: no placement or final check
            approved,
            frozenset({MINI_UNIT}),
        )
    # release
    for key in SIGNED_OFF:
        doc = course.singles.get(key)
        if doc is None or not approved[doc.rel]:
            raise BuildError(f"release: {doc.rel if doc else key} is not approved (the content lead signs it off)")
    shipped = []
    for u in units:
        why = []
        if not u.complete:
            why.append("incomplete (every lesson, the task and the check must exist)")
        if u.items is None:
            why.append("no items file")
        why += [f"{d.rel} is not approved" for d in unit_files(u) if not approved[d.rel]]
        if why:
            if allow_partial:
                report.note(
                    f"release: shipping Units up to {shipped[-1].id if shipped else '(none)'}; {u.id}: {why[0]}"
                )
                break
            raise BuildError(f"release: {u.id} can't ship: {'; '.join(why)} (or pass --allow-partial)")
        shipped.append(u)
    if not shipped:
        raise BuildError("release: no unit is complete and approved")
    assessments = {}
    for key, doc in course.assessments.items():
        if approved[doc.rel]:
            assessments[key] = doc
        elif allow_partial:
            report.warn(f"release: {doc.rel} is not approved and is left out")
        else:
            raise BuildError(f"release: {doc.rel} is not approved (or pass --allow-partial)")
    if "final" in assessments and not any(u.is_final_review for u in shipped):
        del assessments["final"]
        report.warn("release: the final check is left out until the final review unit ships")
    return Scope(
        "release",
        shipped,
        {u.id: list(u.lessons) for u in shipped},
        {u.id: u.task for u in shipped if u.task},
        {u.id: u.check for u in shipped if u.check},
        assessments,
        approved,
    )


# ---------------------------------------------------------------- checks and extras


@cache
def _validators() -> dict[str, Draft202012Validator]:
    schema = json.loads((paths.SCHEMAS / "pack-payloads.schema.json").read_text(encoding="utf-8"))
    return {
        key: Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]})
        for key, name in PAYLOAD_DEFS.items()
    }


def validate_payloads(data: PackData) -> int:
    """Every payload against the contract (`schemas/pack-payloads.schema.json`); returns how many were checked."""
    problems = []
    n = 0
    for key, payloads in data.payloads.items():
        v = _validators()[key]
        for pid, payload in sorted(payloads.items()):
            n += 1
            for err in sorted(v.iter_errors(payload), key=lambda e: list(e.path))[:1]:
                where = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err.path)
                problems.append(f"{key} {pid}{where}: {err.message}")
    if problems:
        shown = "\n  ".join(problems[:20])
        raise BuildError(f"{len(problems)} payload(s) break schemas/pack-payloads.schema.json:\n  {shown}")
    return n


def review_files(course: Course, scope: Scope, root: Path) -> dict[str, dict[str, str]]:
    """`meta.review_files`: the content file and approval hash behind each ID prefix (unit, lesson, task, check,
    placement, final) and each item and grammar point, for the app's review mode (docs/04 § Pack build)."""
    out: dict[str, dict[str, str]] = {}

    def add(key: str, doc: Doc | None) -> None:
        if doc is not None and key:
            out[key] = {"file": doc.rel, "hash": approval.file_hash(root / doc.rel)}

    for u in scope.units:
        add(u.id, u.spec)
        for d in scope.lessons.get(u.id, []):
            add(str(mapping(d.data).get("id", "")), d)
        add(str(mapping(scope.tasks[u.id].data).get("id", "")) if u.id in scope.tasks else "", scope.tasks.get(u.id))
        add(str(mapping(scope.checks[u.id].data).get("id", "")) if u.id in scope.checks else "", scope.checks.get(u.id))
        if u.items is not None:
            for item in map(mapping, seq(mapping(u.items.data).get("items"))):
                add(str(item.get("id", "")), u.items)
    for key, doc in scope.assessments.items():
        add(key, doc)
    points = course.singles.get("points")
    units = {u.id for u in scope.units}
    for p in course.grammar_points():
        if str(p.get("unit")) in units:
            add(str(p.get("id", "")), points)
    return out


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


RELEASED_TABLES = ("units", "can_dos", "items", "lessons", "steps", "texts", "grammar_notes", "exercises", "characters")


def released_ids(rows: dict[str, list[tuple[Any, ...]]], data: PackData) -> list[str]:
    """IDs a release build makes permanent (ADR-14): those of the ID tables, plus task and check files."""
    found = {str(r[0]) for t in RELEASED_TABLES for r in rows.get(t, ())}
    for payload in data.payloads["steps"].values():
        if payload.get("kind") == "check":
            found.add(str(payload["checkId"]))
    task_ids = {e.rsplit(".", 1)[0] for e in data.payloads["exercises"] if ".task." in e}
    return sorted(found | task_ids | set(data.payloads["assessments"]))


def update_ids_lock(root: Path, new_ids: list[str], version: str) -> int:
    """Add the IDs this release compiled to `content/ids.lock` (sorted; comments and earlier entries kept)."""
    path = root / "content" / "ids.lock"
    comments: list[str] = []
    entries: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                comments.append(raw)
            else:
                entries.setdefault(line.split()[0], raw)
    added = [i for i in new_ids if i not in entries]
    for i in added:
        entries[i] = f"{i} {version}"
    if not comments:
        comments = ["# Released IDs (docs/03 § IDs, ADR-14): written by `content build --release`; never edit by hand."]
    path.write_text("\n".join([*comments, *(entries[k] for k in sorted(entries))]) + "\n", encoding="utf-8")
    return len(added)


def sync_audio(dest_dir: Path, referenced: dict[str, Path]) -> int:
    """Copy referenced audio into `Audio/` next to the pack and drop files nothing references; returns bytes."""
    total = sum(p.stat().st_size for p in referenced.values())
    if total > AUDIO_BUDGET_BYTES:
        raise BuildError(f"audio is {total / 2**20:.1f} MB, over the {AUDIO_BUDGET_BYTES // 2**20} MB budget")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("*.m4a"):
        if old.name not in referenced:
            old.unlink()
    for name, src in sorted(referenced.items()):
        target = dest_dir / name
        if not target.is_file() or target.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, target)
    return total


# ---------------------------------------------------------------- the build


def build_pack(
    root: Path | None = None,
    *,
    mode: str = "dev",
    allow_partial: bool = False,
    out: Path | None = None,
    lint: bool = True,
    echo: Callable[[str], Any] = print,
) -> BuildResult:
    if mode not in MODES:
        raise BuildError(f"unknown build mode {mode!r}")
    root = (root or paths.ROOT).resolve()
    report = Report()
    if lint:
        from itcontent.lint import lint_findings

        errors = [f for f in lint_findings(root) if f.level == "error"]
        if errors:
            for f in errors:
                echo(str(f))
            raise BuildError(f"content lint: {len(errors)} error(s); fix them before building")
    course = load_course(root)
    for rel, msg in course.load_errors:
        raise BuildError(f"{rel}: {msg}")
    scope = select_scope(course, mode, allow_partial=allow_partial, report=report)
    data = Compiler(course, Locks(root), scope, report).compile()
    n_payloads = validate_payloads(data)

    # audio: no TTS yet (M5.1), so every need is missing
    if data.audio_needs:
        kinds: dict[str, int] = {}
        for kind, _ in data.audio_needs:
            kinds[kind] = kinds.get(kind, 0) + 1
        summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        if mode == "release":
            raise BuildError(
                f"release: {len(data.audio_needs)} audio need(s) have no audio ({summary}); run content tts"
            )
        report.warn(
            f"missing audio: {len(data.audio_needs)} need(s) ({summary}); audio IDs stay null until content tts"
        )

    course_data = mapping(course.course.data)
    version = str(course_data.get("version", "0.0.0"))
    meta = {
        "schema_version": str(db.schema_version()),
        "pack_version": version,
        "course_id": str(course_data.get("course", "")),
        "locale": str(course_data.get("locale", "it-IT")),
        "release": "1" if mode == "release" else "0",
        "built_with": f"itcontent {__version__}",
    }
    if mode != "mini":
        meta["git_sha"] = git_sha(root)
    if mode != "release":
        meta["review_files"] = cjson(review_files(course, scope, root))
    con = db.create(data.tables, meta)
    try:
        content_hash = db.canonical_hash(con)
        con.execute("INSERT INTO meta VALUES ('content_hash', ?)", (content_hash,))
        con.commit()
        dest = out or default_out(mode, root)
        db.write(con, dest)
        counts = db.counts(con)
    finally:
        con.close()
    result = BuildResult(dest, content_hash, counts, report)
    report.note(f"{n_payloads} payloads validated")
    if mode != "mini":
        sync_audio(dest.parent / "Audio", {})
    if mode == "mini":
        mini = {k: data.payloads[k] for k in ("exercises", "steps", "notes")}
        result.payloads_path = dest.with_name("mini-payloads.json")
        result.payloads_path.write_text(pretty_json(mini), encoding="utf-8")
    if mode == "release":
        result.released_ids = released_ids(data.tables, data)
        added = update_ids_lock(root, result.released_ids, version)
        report.note(f"content/ids.lock: {added} new released ID(s)")
    return result


def run_build(
    root: Path | None = None,
    *,
    mode: str = "dev",
    allow_partial: bool = False,
    out: Path | None = None,
    echo: Callable[[str], Any] = print,
) -> int:
    root = (root or paths.ROOT).resolve()
    try:
        result = build_pack(root, mode=mode, allow_partial=allow_partial, out=out, echo=echo)
    except BuildError as exc:
        echo(f"error: {exc}")
        return 1
    for w in result.report.warnings:
        echo(f"warning: {w}")
    for n in result.report.notes:
        echo(f"note: {n}")
    try:
        shown = result.path.relative_to(root)
    except ValueError:
        shown = result.path
    rows = ", ".join(f"{t} {n}" for t, n in sorted(result.counts.items()))
    echo(f"pack ({mode}): {shown}; pack hash {result.content_hash}")
    echo(f"rows: {rows}")
    if result.payloads_path:
        p = result.payloads_path
        echo(f"payloads: {p.relative_to(root) if p.is_relative_to(root) else p}")
    return 0


def run_pack_hash(pack: Path | None = None, echo: Callable[[str], Any] = print) -> int:
    path = pack or default_out("dev", paths.ROOT)
    try:
        echo(db.pack_hash(path))
    except BuildError as exc:
        echo(f"error: {exc}")
        return 1
    return 0
