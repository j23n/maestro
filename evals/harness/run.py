"""Eval harness CLI.

Examples (repo root):
    python -m evals.harness.run --task writing_feedback --runner anthropic --judge anthropic
    python -m evals.harness.run --task writing_feedback --runner apple_fm
    python -m evals.harness.run --task writing_feedback --runner mock --mock-outputs out.json
    python -m evals.harness.run --resolve-gates

Scorecards land in evals/results/<task>.<runner>.json (+ .md summary);
--resolve-gates combines all present scorecards with evals/gates.yaml
into build/gates_resolved.json for the app to bundle.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from evals.harness.gates import resolve_gates, write_resolved
from evals.harness.runners import (
    AnthropicRunner,
    AppleFMRunner,
    MockRunner,
    PromptTemplate,
)
from evals.harness.schema import Case, Scorecard
from evals.harness.scoring import JUDGE_MODEL, make_scorecard, run_case

RESULTS_DIR = Path("evals/results")


def load_cases(task: str, cases_root: Path = Path("evals/cases")) -> list[Case]:
    cases: list[Case] = []
    for f in sorted((cases_root / task).glob("*.yaml")):
        cases.extend(Case(**e) for e in yaml.safe_load(f.read_text()) or [])
    return cases


def make_runner(name: str, mock_outputs: Path | None):
    if name == "mock":
        if mock_outputs is None:
            raise SystemExit(
                "--runner mock requires --mock-outputs: a JSON file mapping "
                "case id -> canned model output (see tests/unit/test_eval_harness.py)"
            )
        return MockRunner(json.loads(mock_outputs.read_text()))
    if name == "anthropic":
        return AnthropicRunner()
    if name == "apple_fm":
        return AppleFMRunner()
    raise SystemExit(f"unknown runner: {name}")


def scorecard_markdown(card: Scorecard) -> str:
    lines = [
        f"# {card.task} × {card.runner} (prompt v{card.prompt_version})",
        "",
        f"- cases: {card.cases}",
        f"- mean total: **{card.mean_total:.3f}**",
        f"- mean deterministic: {card.mean_deterministic:.3f}",
        f"- mean judge: {card.mean_judge:.3f}"
        if card.mean_judge is not None
        else "- judge: not run",
        f"- hallucination rate: {card.hallucination_rate:.3f}",
        "",
        "| case | total | failures |",
        "| --- | --- | --- |",
    ]
    for r in card.results:
        lines.append(
            f"| {r.case_id} | {r.total:.2f} | {'; '.join(r.failures) or '—'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="evals")
    parser.add_argument("--task")
    parser.add_argument("--runner")
    parser.add_argument("--judge", default=None, help="anthropic, or omit for none")
    parser.add_argument(
        "--judge-model",
        default=None,
        help=f"override the pinned judge model ({JUDGE_MODEL}) — scorecards "
        "record it either way",
    )
    parser.add_argument("--mock-outputs", type=Path, default=None)
    parser.add_argument("--resolve-gates", action="store_true")
    parser.add_argument(
        "--allow-no-scorecards",
        action="store_true",
        help="let --resolve-gates emit an all-disabled file with no scorecards",
    )
    args = parser.parse_args()

    if args.resolve_gates:
        cards = [
            Scorecard(**json.loads(f.read_text())) for f in RESULTS_DIR.glob("*.json")
        ]
        if not cards and not args.allow_no_scorecards:
            raise SystemExit(
                "no scorecards under evals/results/ — run the harness first, "
                "or pass --allow-no-scorecards to emit an all-disabled gates "
                "file on purpose"
            )
        resolved = resolve_gates(Path("evals/gates.yaml"), cards)
        out = Path("build/gates_resolved.json")
        out.parent.mkdir(exist_ok=True)
        write_resolved(resolved, out)
        print(json.dumps(resolved, indent=2))
        return 0

    if not args.task or not args.runner:
        parser.error("--task and --runner required (or --resolve-gates)")
    cases = load_cases(args.task)
    if not cases:
        raise SystemExit(f"no cases for task {args.task}")
    runner = make_runner(args.runner, args.mock_outputs)
    judge_model = args.judge_model or JUDGE_MODEL
    judge = AnthropicRunner(model=judge_model) if args.judge == "anthropic" else None

    if args.task == "content_generation":
        from evals.harness.content_gen import GENERATOR_PROMPT_VERSION, run_content_case

        results = [run_content_case(c, runner, judge) for c in cases]
        prompt_version = GENERATOR_PROMPT_VERSION
    else:
        prompt = PromptTemplate(args.task)
        results = [run_case(c, runner, prompt, judge) for c in cases]
        prompt_version = prompt.version
    card = make_scorecard(
        args.task,
        runner.name,
        prompt_version,
        cases,
        results,
        judge_model=judge_model if judge else None,
        judge_prompt_version=1 if judge else None,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    base = RESULTS_DIR / f"{args.task}.{runner.name}"
    base.with_suffix(".json").write_text(card.model_dump_json(indent=2) + "\n")
    base.with_suffix(".md").write_text(scorecard_markdown(card))
    print(
        f"{card.task} × {card.runner}: mean {card.mean_total:.3f} over "
        f"{card.cases} cases, hallucination {card.hallucination_rate:.2f} "
        f"-> {base}.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
