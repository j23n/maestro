"""The audio budget and its projection (docs/04 § Pack build › Audio, M5.4; ADR-17: ≤ 150 MB at 48 kbps, 40 kbps if
Units 0–1 project above budget).

Per unit, from the needs the compiler found (`AudioPlan`):

- **now**: the encoded files of the needs that have audio (their real size when encoded, else an estimate from the
  duration at the bitrate): what the bundle holds;
- **written**: the written content as real speech: Azure audio as it is, and an estimate for needs without audio or
  with mock audio (characters at the speaking rate, per voice rate, plus the gaps between lines);
- **projected**: plus the content the unit spec still expects: each missing lesson at the course's average per written
  lesson, a missing task or check at the average task or check, and the items the spec's `items.new_words` (the top of
  its range) still lacks at the average per item.

The speaking rate starts at `CHARS_PER_SECOND` and is recalibrated from Azure renders once there are enough of them;
mock renders never calibrate it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from itcontent import audio_pcm
from itcontent.audio_assets import AudioPlan, Resolved
from itcontent.course import Course
from itcontent.tts_needs import Need

BUDGET_BYTES = 150 * 1024 * 1024
FALLBACK_BITRATE = "40k"
CHARS_PER_SECOND = 13.0  # Italian neural voices at rate 0%, punctuation pauses included (an estimate)
RENDER_PADDING_MS = 300  # leading and trailing silence of one render
CALIBRATE_MIN_CHARS = 500
MB = 1024 * 1024


def _rate(value: str) -> float:
    m = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)%\s*", value or "")
    return 1 + float(m.group(1)) / 100 if m else 1.0


def part_kind(part: str) -> str:
    name = part.rsplit("/", 1)[-1]
    if part.startswith("content/items/"):
        return "items"
    if name.startswith("lesson-"):
        return "lesson"
    if name in ("task.yaml", "check.yaml"):
        return name[:-5]
    return "other"


def _range_top(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    nums = [int(n) for n in re.findall(r"\d+", str(value or ""))]
    return max(nums) if nums else 0


@dataclass
class UnitBudget:
    unit: str
    needs: int = 0
    voiced: int = 0
    seconds: float = 0.0  # every need: its Azure audio's length, or the estimate
    now: int = 0  # bytes of the needs that have audio
    written: int = 0  # now + estimates for the written content without audio
    projected: int = 0  # written + the content the spec still expects
    missing: list[str] = field(default_factory=list)  # what the projection adds

    @property
    def mb_now(self) -> float:
        return self.now / MB

    @property
    def mb_projected(self) -> float:
        return self.projected / MB


@dataclass
class Projection:
    units: list[UnitBudget]
    chars_per_second: float
    calibrated: bool
    bitrate: str = audio_pcm.ENCODE.bitrate

    @property
    def now(self) -> int:
        return sum(u.now for u in self.units)

    @property
    def projected(self) -> int:
        return sum(u.projected for u in self.units)

    @property
    def projected_fallback(self) -> int:
        """The projection at 40 kbps (ADR-17's fallback)."""
        fallback = audio_pcm.EncodeSettings(bitrate=FALLBACK_BITRATE).bits_per_second
        return round(self.projected * fallback / audio_pcm.ENCODE.bits_per_second)

    @property
    def over_budget(self) -> bool:
        return self.projected > BUDGET_BYTES


def estimate_ms(need: Need, cps: float) -> int:
    """How long a need will be once rendered: characters at the speaking rate, per line, plus gaps."""
    total = 0
    gaps = audio_pcm.gaps([ln.speaker for ln in need.lines], [ln.pause_ms for ln in need.lines])
    for line, gap in zip(need.lines, gaps, strict=True):
        speed = cps * _rate(line.speech.voice.rate)
        total += gap + RENDER_PADDING_MS + round(1000 * line.speech.characters / max(speed, 1.0))
    return total


def calibrate(resolved: list[Resolved]) -> tuple[float, bool]:
    chars = 0
    ms = 0
    for r in resolved:
        for line, (_, meta) in zip(r.need.lines, r.renders, strict=True):
            if meta.provider != "azure":
                continue
            chars += round(line.speech.characters / _rate(line.speech.voice.rate))
            ms += max(meta.duration_ms - RENDER_PADDING_MS, 1)
    if chars >= CALIBRATE_MIN_CHARS and ms > 0:
        return chars * 1000 / ms, True
    return CHARS_PER_SECOND, False


def project(course: Course, plan: AudioPlan, files: Mapping[str, Path] | None = None) -> Projection:
    files = files or {}
    resolver = plan.resolver
    results = {k: resolver.resolve(n) if resolver else None for k, n in plan.needs.items()}
    resolved = [r for r in results.values() if isinstance(r, Resolved)]
    cps, calibrated = calibrate(resolved)
    order = course.unit_order()
    budgets = {u.id: UnitBudget(u.id) for u in sorted(course.units, key=lambda u: order.get(u.id, 99)) if u.spec}
    by_kind: dict[str, int] = {}  # bytes per part kind (lesson, task, check, items), for the averages
    item_count = 0
    counted: set[str] = set()
    for key, need in plan.needs.items():
        b = budgets.setdefault(need.unit, UnitBudget(need.unit))
        r = results[key]
        b.needs += 1
        if need.kind == "item":
            item_count += 1
        if isinstance(r, Resolved):
            b.voiced += 1
            if r.file in counted:
                continue  # one file, counted once (in the unit that met it first)
            counted.add(r.file)
            path = files.get(r.file)
            size = path.stat().st_size if path is not None and path.is_file() else None
            size = size if size is not None else audio_pcm.estimated_m4a_bytes(r.duration_ms)
            b.now += size
            if "mock" in r.providers:  # synthetic: its length says nothing about real speech
                ms = estimate_ms(need, cps)
                size = audio_pcm.estimated_m4a_bytes(ms)
            else:
                ms = r.duration_ms
        else:
            if need.problem is not None:
                continue
            ms = estimate_ms(need, cps)
            size = audio_pcm.estimated_m4a_bytes(ms)
        b.seconds += ms / 1000
        b.written += size
        kind = part_kind(need.part)
        by_kind[kind] = by_kind.get(kind, 0) + size
    written_lessons = sum(len(u.lessons) for u in course.units)
    tasks = sum(1 for u in course.units if u.task)
    checks = sum(1 for u in course.units if u.check)
    avg = {
        "lesson": by_kind.get("lesson", 0) / written_lessons if written_lessons else 0,
        "task": by_kind.get("task", 0) / tasks if tasks else 0,
        "check": by_kind.get("check", 0) / checks if checks else 0,
        "item": by_kind.get("items", 0) / item_count if item_count else 0,
    }
    items_per_unit: dict[str, int] = {}
    for need in plan.needs.values():
        if need.kind == "item":
            items_per_unit[need.unit] = items_per_unit.get(need.unit, 0) + 1
    for u in course.units:
        b = budgets.get(u.id)
        if b is None:
            continue
        extra = 0.0
        lessons = max(0, u.lesson_count - len(u.lessons))
        if lessons:
            extra += lessons * avg["lesson"]
            b.missing.append(f"{lessons} lesson{'s' if lessons != 1 else ''}")
        if u.task is None and not u.is_final_review:
            extra += avg["task"]
            b.missing.append("task")
        if u.check is None and not u.is_final_review:
            extra += avg["check"]
            b.missing.append("check")
        spec = u.spec.data if u.spec is not None and isinstance(u.spec.data, dict) else {}
        want = _range_top((spec.get("items") or {}).get("new_words") if isinstance(spec.get("items"), dict) else 0)
        lacking = max(0, want - items_per_unit.get(u.id, 0))
        if lacking:
            extra += lacking * avg["item"]
            b.missing.append(f"{lacking} items")
        b.projected = b.written + round(extra)
    for b in budgets.values():
        b.projected = max(b.projected, b.written)
    return Projection(list(budgets.values()), cps, calibrated)


def build_line(p: Projection) -> str:
    """One line for `content build`: the bundle now, and the projection per unit."""
    units = " · ".join(f"{u.unit} {u.mb_now:.1f}/{u.mb_projected:.1f}" for u in p.units)
    return (
        f"audio budget (MB now/projected): {units}; total {p.now / MB:.1f}/{p.projected / MB:.1f} of "
        f"{BUDGET_BYTES // MB} at {p.bitrate}bps ({p.projected_fallback / MB:.1f} at {FALLBACK_BITRATE}bps)"
    )


def report_lines(p: Projection, unit: str | None = None) -> list[str]:
    """The `content report` section: MB per unit now and projected."""
    how = "calibrated on the Azure renders" if p.calibrated else "a first guess until Azure renders exist"
    rate = f"{p.chars_per_second:.1f} characters/s, {how}"
    lines = [
        f"AAC {p.bitrate}bps, 24 kHz mono; budget {BUDGET_BYTES // MB} MB for the bundle (ADR-17). *Now* is the audio "
        f"that exists (encoded size, or its duration at the bitrate); *written* is the written content as real speech "
        f"(Azure audio, else estimated at {rate}); *projected* adds what each unit spec still expects, at the "
        "course's averages.",
        "",
        "| Unit | Needs | Voiced | Minutes | MB now | MB written | MB projected | Still expected |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for u in p.units:
        if unit is not None and u.unit != unit:
            continue
        lines.append(
            f"| {u.unit} | {u.needs} | {u.voiced} | {u.seconds / 60:.1f} | {u.now / MB:.2f} | {u.written / MB:.2f} "
            f"| {u.projected / MB:.2f} | {', '.join(u.missing) or '—'} |"
        )
    lines += [
        "",
        f"Course: {p.now / MB:.1f} MB now, {p.projected / MB:.1f} MB projected of {BUDGET_BYTES // MB} MB "
        f"({p.projected_fallback / MB:.1f} MB at {FALLBACK_BITRATE}bps).",
    ]
    if p.over_budget:
        lines.append(
            f"**Over budget:** the projection exceeds {BUDGET_BYTES // MB} MB. ADR-17: once Units 0–1 are rendered "
            f"and still project above budget, drop the bitrate to {FALLBACK_BITRATE}bps (`audio_pcm.ENCODE`)."
        )
    return lines
