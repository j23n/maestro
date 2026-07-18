"""The content_generation eval task: measure the authoring generator.

Unlike the runtime tasks (writing_feedback, ...), which consume
prompts/runtime/ templates, this task consumes the REAL authoring
prompt (authoring/generate.py builds it) — the eval measures exactly
what `maestro-pack generate` sends, or it measures nothing.

Deterministic layer per case (a spec cell + item family + count):
- the batch parses (fenced YAML list of the right shape)  — hard gate
- the requested item count arrived
- every item passes schema + spec-reference validation
- every item is clean under the authoring quality validators
  (vocab level, solvability, near-duplicates, orthography)

The judge layer grades pedagogy: do these items actually exercise the
scope, at the level? Scores feed the same scorecard/gate machinery, so
"which model drafts acceptable content, with which prompt" becomes a
measured, re-checkable question — for cloud models and (via the
apple_fm runner) on-device ones.
"""

from __future__ import annotations

from pathlib import Path

from evals.harness.schema import Case, CaseResult
from evals.harness.scoring import (
    JUDGE_WEIGHT,
    _InlinePrompt,
    extract_json,
    judge_score,
)

# The authoring prompt has its own version so scorecards stay honest
# when the drafting prompt changes.
GENERATOR_PROMPT_VERSION = 1


class AuthoringPrompt:
    """Adapter presenting the real authoring prompt as a PromptTemplate."""

    version = GENERATOR_PROMPT_VERSION
    system = ""
    defaults: dict = {}

    def __init__(self, rendered: str):
        self._rendered = rendered

    def render(self, _case: Case) -> str:
        return self._rendered


def _spec():
    from authoring.validate_spec import load_spec

    return load_spec(Path("spec/it"))


def build_case_prompt(case: Case) -> tuple[AuthoringPrompt, object, object]:
    """(prompt adapter, scope, kind) for a content_generation case."""
    from authoring.generate import KINDS, build_prompt, resolve_scope

    spec = _spec()
    extra = case.input.model_dump()
    scope = resolve_scope(
        spec,
        gp=extra.get("gp"),
        scenario=extra.get("scenario"),
        cando=extra.get("cando"),
        theme=extra.get("theme"),
        level=extra.get("scope_level") or case.input.level,
    )
    kind = KINDS[extra.get("kind", "drill")]
    count = int(extra.get("count", 5))
    rendered = build_prompt(spec, scope, kind, count, [])
    return AuthoringPrompt(rendered), scope, kind


def deterministic_checks(case: Case, raw: str) -> tuple[float, list[str]]:
    from authoring.generate import parse_response
    from authoring.quality import validate_quality

    spec = _spec()
    _prompt, scope, kind = build_case_prompt(case)
    count = int(case.input.model_dump().get("count", 5))

    try:
        items = parse_response(raw, spec, kind, scope, set())
    except Exception as exc:
        return 0.0, [f"batch rejected: {exc}"]

    checks, passed = 0, 0
    failures: list[str] = []

    checks += 1
    if len(items) == count:
        passed += 1
    else:
        failures.append(f"asked for {count} items, got {len(items)}")

    warnings = validate_quality(items, spec)
    for item in items:
        checks += 1
        item_warnings = warnings.get(item.id, [])
        if not item_warnings:
            passed += 1
        else:
            failures.append(f"{item.id}: {'; '.join(item_warnings)}")

    return (passed / checks if checks else 0.0), failures


JUDGE_TEMPLATE = """You are grading a batch of drafted Italian course items.

They were drafted for: {scope_title} (target level {level}).
The batch (YAML):
---
{raw}
---
Grade each criterion 0 or 1 and respond ONLY with JSON:
{{
  "exercises_the_scope": 0 or 1,
  "italian_is_natural": 0 or 1,
  "difficulty_fits_level": 0 or 1,
  "feedback_is_pedagogical": 0 or 1
}}"""


def run_content_case(case: Case, runner, judge=None) -> CaseResult:
    prompt, scope, _kind = build_case_prompt(case)
    raw = runner.run(case, prompt)
    det, failures = deterministic_checks(case, raw)
    j = None
    if judge is not None:
        rendered = JUDGE_TEMPLATE.format(
            scope_title=scope.title, level=scope.level, raw=raw
        )
        j = judge_score(judge.run(case, _InlinePrompt(rendered)))
    total = det if j is None else (1 - JUDGE_WEIGHT) * det + JUDGE_WEIGHT * j
    return CaseResult(
        case_id=case.id,
        ok_json=extract_json(raw) is not None or det > 0,
        deterministic_score=det,
        judge_score=j,
        total=total,
        failures=failures,
        raw_output=raw,
    )
