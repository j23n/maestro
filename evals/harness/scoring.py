"""Scoring: deterministic checks first, then an optional judge model.

The deterministic layer needs no API and catches the failure modes that
matter most for small models: broken JSON, missed seeded errors,
hallucinated errors, missing required content, runaway length. The judge
layer grades quality (is the explanation actually good?) as a weighted
checklist — see judge_prompt().
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from evals.harness.runners import PromptTemplate, Runner
from evals.harness.schema import Case, CaseResult, Scorecard

JUDGE_WEIGHT = 0.4

# The pinned judge (plan §11.4): a fixed strong model, deliberately
# separate from whatever runner is being graded. Changing it invalidates
# scorecard comparisons, so it changes here, on purpose, not per run.
JUDGE_MODEL = "claude-opus-4-8"

JUDGE_PROMPTS_DIR = Path("evals/judge_prompts")
_judge_prompt_cache: dict = {}


def load_judge_prompt(version: int = 1) -> dict:
    if version not in _judge_prompt_cache:
        _judge_prompt_cache[version] = yaml.safe_load(
            (JUDGE_PROMPTS_DIR / f"default.v{version}.yaml").read_text()
        )
    return _judge_prompt_cache[version]


def extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _claimed_tags(parsed: dict) -> list[str]:
    errors = parsed.get("errors")
    if not isinstance(errors, list):
        return []
    return [e.get("tag", "") for e in errors if isinstance(e, dict)]


def deterministic_checks(case: Case, raw: str) -> tuple[float, list[str], bool]:
    """Return (score 0-1, failure notes, hallucinated?)."""
    failures: list[str] = []
    parsed = extract_json(raw)
    if parsed is None:
        return 0.0, ["output is not a JSON object"], False

    checks = 0
    passed = 0
    hallucinated = False
    claimed = _claimed_tags(parsed)

    for tag in case.expect.must_identify:
        checks += 1
        if tag in claimed:
            passed += 1
        else:
            failures.append(f"missed seeded error: {tag}")
    for tag in case.expect.must_not_claim:
        checks += 1
        if tag in claimed:
            hallucinated = True
            failures.append(f"hallucinated error: {tag}")
        else:
            passed += 1
    flat = json.dumps(parsed, ensure_ascii=False).lower()
    for needle in case.expect.must_contain:
        checks += 1
        if needle.lower() in flat:
            passed += 1
        else:
            failures.append(f"missing required content: {needle}")
    for needle in case.expect.must_not_contain:
        checks += 1
        if needle.lower() in flat:
            hallucinated = True
            failures.append(f"forbidden content present: {needle}")
        else:
            passed += 1

    checks += 1
    too_long = [
        k
        for k, v in parsed.items()
        if isinstance(v, str) and len(v.split()) > case.expect.max_field_words
    ]
    if too_long:
        failures.append(f"over-long fields: {too_long}")
    else:
        passed += 1

    return (passed / checks if checks else 1.0), failures, hallucinated


def judge_prompt(case: Case, raw: str, version: int = 1) -> str:
    """Render the versioned judge prompt (evals/judge_prompts/)."""
    tpl = load_judge_prompt(version)
    return tpl["template"].format(
        level=case.input.level,
        task_prompt=case.input.prompt or "(drill)",
        submission=case.input.submission or "(n/a)",
        raw=raw,
    )


def judge_score(judge_output: str) -> float | None:
    parsed = extract_json(judge_output)
    if not parsed:
        return None
    values = [v for v in parsed.values() if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def run_case(
    case: Case,
    runner: Runner,
    prompt: PromptTemplate,
    judge: Runner | None = None,
) -> CaseResult:
    raw = runner.run(case, prompt)
    det, failures, hallucinated = deterministic_checks(case, raw)
    j: float | None = None
    if judge is not None:
        judge_case = case.model_copy()
        j = judge_score(judge.run(judge_case, _InlinePrompt(judge_prompt(case, raw))))
    total = det if j is None else (1 - JUDGE_WEIGHT) * det + JUDGE_WEIGHT * j
    return CaseResult(
        case_id=case.id,
        ok_json=extract_json(raw) is not None,
        deterministic_score=det,
        judge_score=j,
        total=total,
        hallucinated=hallucinated,
        failures=failures,
        raw_output=raw,
    )


class _InlinePrompt:
    """Adapter: hand a runner a fully-rendered prompt."""

    version = 0
    system = "You are a strict grader."
    defaults: dict = {}

    def __init__(self, rendered: str):
        self._rendered = rendered

    def render(self, _case: Case) -> str:
        return self._rendered


def make_scorecard(
    task: str,
    runner_name: str,
    prompt_version: int,
    cases: list[Case],
    results: list[CaseResult],
    judge_model: str | None = None,
    judge_prompt_version: int | None = None,
) -> Scorecard:
    n = len(results) or 1
    judged = [r.judge_score for r in results if r.judge_score is not None]
    hallucinations = sum(1 for r in results if r.hallucinated)
    return Scorecard(
        task=task,
        runner=runner_name,
        prompt_version=prompt_version,
        cases=len(results),
        mean_total=sum(r.total for r in results) / n,
        mean_deterministic=sum(r.deterministic_score for r in results) / n,
        mean_judge=(sum(judged) / len(judged)) if judged else None,
        judge_model=judge_model if judged else None,
        judge_prompt_version=judge_prompt_version if judged else None,
        hallucination_rate=hallucinations / n,
        results=results,
    )
