"""`content beta-import <events.jsonl>`: item statistics and rejected typed answers from study telemetry.

docs/04 § Commands and checks 7 and 10, docs/12 § Beta and study data loop, task M6.7. The input is the server's
JSONL export (`server/README.md`): one line per event, `{installId, app, receivedAt, event}` where `event` is the
uploaded event envelope (`docs/12` § The endpoint contract). Bare event objects with an `installId` are accepted
too. Outputs go to `build/reports/beta/`: `items.md` (outliers first) and `items.json`, `rejected.md` and
`rejected.json` (the input of "Answers to adjudicate", task M8.3). Outputs are deterministic.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from itcontent.normalize import normalize as _normalize
except ImportError:  # pragma: no cover - the shared normaliser lands with M1.4
    _normalize = None

CORRECT = {"correct", "correctWithNote"}
MIN_ATTEMPTS_FOR_OUTLIER = 5


def norm(text: str) -> str:
    if _normalize is not None:
        return _normalize(text)
    return " ".join(text.lower().split())


@dataclass
class Stat:
    """First-attempt statistics for one key (an item+skill or an exercise)."""

    first_attempts: int = 0
    first_errors: int = 0
    skips: int = 0
    latencies: list[int] = field(default_factory=list)
    learners: set[str] = field(default_factory=set)

    def add(self, outcome: str, latency: int | None, install: str) -> None:
        self.learners.add(install)
        if outcome == "skipped":
            self.skips += 1
            return
        self.first_attempts += 1
        if outcome not in CORRECT:
            self.first_errors += 1
        if isinstance(latency, int) and latency >= 0:
            self.latencies.append(latency)

    @property
    def error_rate(self) -> float:
        return self.first_errors / self.first_attempts if self.first_attempts else 0.0

    @property
    def median_latency_ms(self) -> int | None:
        return int(statistics.median(self.latencies)) if self.latencies else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "firstAttempts": self.first_attempts,
            "firstTryErrorRate": round(self.error_rate, 4),
            "medianLatencyMs": self.median_latency_ms,
            "skips": self.skips,
            "learners": len(self.learners),
        }


@dataclass
class BetaReport:
    items: dict[str, Stat]
    exercises: dict[str, Stat]
    gloss_taps: dict[str, int]  # item id (or textId#line:token when no item) → taps
    rejected: dict[str, Counter[str]]  # exercise id (or exercise/turn) → normalised response → count
    events: int
    learners: int


def read_events(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """(installId, event) pairs, deduplicated by event ID, sorted by (at, id)."""
    seen: dict[str, tuple[str, dict[str, Any]]] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: not JSON ({exc})") from exc
        event = obj.get("event", obj)
        install = obj.get("installId") or event.get("installId")
        if not isinstance(event, dict) or not install or "id" not in event or "type" not in event:
            raise ValueError(f"{path}:{n}: expected {{installId, event: {{id, at, type, payload}}}}")
        seen.setdefault(str(event["id"]), (str(install), event))
    return sorted(seen.values(), key=lambda p: (p[1].get("at", 0), str(p[1]["id"])))


def analyse(pairs: list[tuple[str, dict[str, Any]]]) -> BetaReport:
    items: dict[str, Stat] = defaultdict(Stat)
    exercises: dict[str, Stat] = defaultdict(Stat)
    gloss: Counter[str] = Counter()
    rejected: dict[str, Counter[str]] = defaultdict(Counter)
    for install, ev in pairs:
        p = ev.get("payload") or {}
        if ev["type"] == "attempt":
            ex = str(p.get("exerciseId", ""))
            key = f"{ex}/{p['turnId']}" if p.get("turnId") else ex
            outcome = str(p.get("outcome", ""))
            if p.get("attemptIndex") == 1 and p.get("context") != "placement":
                exercises[key].add(outcome, p.get("latencyMs"), install)
                for t in p.get("targets") or []:
                    items[f"{t.get('itemId')}|{t.get('skill')}"].add(
                        str(t.get("outcome", outcome)), p.get("latencyMs"), install
                    )
            resp = p.get("response")
            if outcome == "wrong" and p.get("mode") == "typed" and isinstance(resp, str) and resp.strip():
                rejected[key][norm(resp)] += 1
        elif ev["type"] == "glossTapped":
            key = p.get("itemId") or f"{p.get('textId')}#{p.get('line')}:{p.get('token')}"
            gloss[str(key)] += 1
    return BetaReport(dict(items), dict(exercises), dict(gloss), dict(rejected), len(pairs), len({i for i, _ in pairs}))


def _sorted_stats(stats: dict[str, Stat]) -> list[tuple[str, Stat]]:
    """Outliers first: enough data and a high error rate, then slow, then by key."""

    def key(kv: tuple[str, Stat]) -> tuple[int, float, int, str]:
        k, s = kv
        enough = 0 if s.first_attempts >= MIN_ATTEMPTS_FOR_OUTLIER else 1
        return (enough, -s.error_rate, -(s.median_latency_ms or 0), k)

    return sorted(stats.items(), key=key)


def write_reports(report: BetaReport, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    items_json = {
        "events": report.events,
        "learners": report.learners,
        "items": {k: v.as_dict() for k, v in sorted(report.items.items())},
        "exercises": {k: v.as_dict() for k, v in sorted(report.exercises.items())},
        "glossTaps": dict(sorted(report.gloss_taps.items())),
    }
    rejected_json = {
        ex: [{"response": r, "count": c} for r, c in sorted(cnt.items(), key=lambda rc: (-rc[1], rc[0]))]
        for ex, cnt in sorted(report.rejected.items())
    }
    lines = [
        "# Beta item statistics",
        "",
        f"{report.events} events from {report.learners} learners. First attempts only; placement excluded.",
        f"Outliers first (≥ {MIN_ATTEMPTS_FOR_OUTLIER} first attempts, highest first-try error rate).",
        "",
        "## Items (item | skill)",
        "",
        "| Item | Skill | First attempts | First-try error | Median latency | Skips | Gloss taps |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, s in _sorted_stats(report.items):
        item, skill = k.split("|", 1)
        lat = f"{s.median_latency_ms / 1000:.1f} s" if s.median_latency_ms is not None else "–"
        lines.append(
            f"| `{item}` | {skill} | {s.first_attempts} | {s.error_rate:.0%} | {lat} | {s.skips} | "
            f"{report.gloss_taps.get(item, 0)} |"
        )
    lines += [
        "",
        "## Exercises",
        "",
        "| Exercise | First attempts | First-try error | Median latency | Skips |",
        "|---|---|---|---|---|",
    ]
    for k, s in _sorted_stats(report.exercises):
        lat = f"{s.median_latency_ms / 1000:.1f} s" if s.median_latency_ms is not None else "–"
        lines.append(f"| `{k}` | {s.first_attempts} | {s.error_rate:.0%} | {lat} | {s.skips} |")
    rej = [
        "# Rejected typed answers",
        "",
        "Answers the app graded `wrong`, grouped by exercise (and conversation turn),",
        "most frequent first. The content lead adjudicates them (docs/04 check 7, task M8.3).",
        "",
    ]
    for ex, answers in rejected_json.items():
        rej.append(f"## `{ex}`")
        rej.append("")
        rej += [f"- {a['count']} × *{a['response']}*" for a in answers]
        rej.append("")
    paths = [out / "items.json", out / "items.md", out / "rejected.json", out / "rejected.md"]
    paths[0].write_text(json.dumps(items_json, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    paths[1].write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths[2].write_text(
        json.dumps(rejected_json, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    paths[3].write_text("\n".join(rej).rstrip() + "\n", encoding="utf-8")
    return paths


def run_beta_import(path: Path, out: Path) -> BetaReport:
    report = analyse(read_events(path))
    write_reports(report, out)
    return report
