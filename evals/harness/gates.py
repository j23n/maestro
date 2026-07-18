"""Promotion gates: the scorecard, not optimism, decides what runs
on-device. Resolves evals/gates.yaml + scorecards into a config the app
build bundles (gates_resolved.json)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from evals.harness.schema import Scorecard


def resolve_gates(
    gates_path: Path,
    scorecards: list[Scorecard],
) -> dict:
    """Return {task: {backend: {"enabled": bool, "reason": str}}}."""
    gates = yaml.safe_load(gates_path.read_text())
    by_key = {(s.task, s.runner): s for s in scorecards}
    resolved: dict = {}
    for task, rule in gates["tasks"].items():
        resolved[task] = {}
        reference = by_key.get((task, rule.get("reference", "anthropic")))
        for backend in rule.get("backends", []):
            card = by_key.get((task, backend))
            if card is None:
                resolved[task][backend] = {
                    "enabled": False,
                    "reason": "no scorecard",
                }
                continue
            floor = rule.get("floor", 0.8)
            ratio = rule.get("reference_ratio", 0.85)
            max_hallucination = rule.get("max_hallucination_rate", 0.05)
            reasons = []
            if card.mean_total < floor:
                reasons.append(f"score {card.mean_total:.2f} < floor {floor}")
            if card.hallucination_rate > max_hallucination:
                reasons.append(
                    f"hallucination {card.hallucination_rate:.2f} > {max_hallucination}"
                )
            if reference and card.mean_total < ratio * reference.mean_total:
                reasons.append(
                    f"score {card.mean_total:.2f} < {ratio} × reference "
                    f"{reference.mean_total:.2f}"
                )
            resolved[task][backend] = {
                "enabled": not reasons,
                "reason": "; ".join(reasons) or "passed",
                "score": round(card.mean_total, 4),
                "prompt_version": card.prompt_version,
            }
    return resolved


def write_resolved(resolved: dict, out: Path) -> None:
    out.write_text(json.dumps(resolved, indent=2) + "\n")
