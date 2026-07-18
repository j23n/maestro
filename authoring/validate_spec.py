"""Load and validate a curriculum spec directory (``spec/<lang>/``).

Checks, beyond per-model schema validation:

- unique IDs within each inventory
- scenario ``grammar_ids`` / ``function_ids`` resolve
- grammar ``prerequisites`` resolve and form an acyclic graph
- warnings (non-fatal): scenario referencing a grammar point or function
  above the scenario's own CEFR level

Usage: ``uv run python -m authoring.validate_spec spec/it``
"""

from __future__ import annotations

import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import yaml

from authoring.spec_schemas import (
    CanDo,
    CommunicativeFunction,
    GrammarPoint,
    Scenario,
    Spec,
    VocabEntry,
)

_LEVEL_ORDER = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]


def load_spec(spec_dir: Path) -> Spec:
    def read(name: str) -> list[dict]:
        path = spec_dir / name
        if not path.exists():
            return []
        return yaml.safe_load(path.read_text()) or []

    return Spec(
        language=spec_dir.name,
        grammar_points=[GrammarPoint(**e) for e in read("grammar_points.yaml")],
        communicative_functions=[
            CommunicativeFunction(**e) for e in read("comm_functions.yaml")
        ],
        scenarios=[Scenario(**e) for e in read("scenarios.yaml")],
        can_dos=[CanDo(**e) for e in read("can_do.yaml")],
        vocab=[VocabEntry(**e) for e in read("vocab.yaml")],
    )


def validate(spec: Spec) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    def check_unique(kind: str, ids: list[str]) -> None:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                errors.append(f"duplicate {kind} id: {i}")
            seen.add(i)

    gp_ids = [g.id for g in spec.grammar_points]
    cf_ids = [c.id for c in spec.communicative_functions]
    check_unique("grammar", gp_ids)
    check_unique("function", cf_ids)
    check_unique("scenario", [s.id for s in spec.scenarios])
    check_unique("can-do", [c.id for c in spec.can_dos])
    check_unique("vocab", [v.id for v in spec.vocab])

    gp_by_id = {g.id: g for g in spec.grammar_points}
    cf_by_id = {c.id: c for c in spec.communicative_functions}

    graph: dict[str, list[str]] = {}
    for g in spec.grammar_points:
        for p in g.prerequisites:
            if p not in gp_by_id:
                errors.append(f"grammar {g.id}: unknown prerequisite {p}")
            elif p == g.id:
                errors.append(f"grammar {g.id}: is its own prerequisite")
        graph[g.id] = [p for p in g.prerequisites if p in gp_by_id]
    try:
        TopologicalSorter(graph).static_order()
    except CycleError as e:
        errors.append(f"prerequisite cycle: {e.args[1]}")

    for s in spec.scenarios:
        s_rank = _LEVEL_ORDER.index(s.cefr_level)
        for gid in s.grammar_ids:
            gp = gp_by_id.get(gid)
            if gp is None:
                errors.append(f"scenario {s.id}: unknown grammar id {gid}")
            elif _LEVEL_ORDER.index(gp.cefr_level) > s_rank:
                warnings.append(
                    f"scenario {s.id} ({s.cefr_level}) references "
                    f"{gid} ({gp.cefr_level})"
                )
        for fid in s.function_ids:
            cf = cf_by_id.get(fid)
            if cf is None:
                errors.append(f"scenario {s.id}: unknown function id {fid}")
            elif _LEVEL_ORDER.index(cf.cefr_level) > s_rank:
                warnings.append(
                    f"scenario {s.id} ({s.cefr_level}) references "
                    f"{fid} ({cf.cefr_level})"
                )

    scenario_ids = {s.id for s in spec.scenarios}
    for cd in spec.can_dos:
        cd_rank = _LEVEL_ORDER.index(cd.cefr_level)
        if not cd.label.startswith("Can "):
            errors.append(f"can-do {cd.id}: label must start with 'Can '")
        if not cd.function_ids and not cd.grammar_ids:
            errors.append(f"can-do {cd.id}: decomposes to no functions or grammar")
        for gid in cd.grammar_ids:
            gp = gp_by_id.get(gid)
            if gp is None:
                errors.append(f"can-do {cd.id}: unknown grammar id {gid}")
            elif _LEVEL_ORDER.index(gp.cefr_level) > cd_rank:
                warnings.append(
                    f"can-do {cd.id} ({cd.cefr_level}) references "
                    f"{gid} ({gp.cefr_level})"
                )
        for fid in cd.function_ids:
            cf = cf_by_id.get(fid)
            if cf is None:
                errors.append(f"can-do {cd.id}: unknown function id {fid}")
            elif _LEVEL_ORDER.index(cf.cefr_level) > cd_rank:
                warnings.append(
                    f"can-do {cd.id} ({cd.cefr_level}) references "
                    f"{fid} ({cf.cefr_level})"
                )
        for sid in cd.scenario_ids:
            if sid not in scenario_ids:
                errors.append(f"can-do {cd.id}: unknown scenario id {sid}")

    return errors, warnings


def main() -> int:
    spec_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "spec/it")
    spec = load_spec(spec_dir)
    errors, warnings = validate(spec)
    print(
        f"{spec_dir}: {len(spec.grammar_points)} grammar points, "
        f"{len(spec.communicative_functions)} functions, "
        f"{len(spec.scenarios)} scenarios, {len(spec.can_dos)} can-dos, "
        f"{len(spec.vocab)} vocab entries"
    )
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
