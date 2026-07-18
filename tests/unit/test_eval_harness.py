"""Eval harness end-to-end with mock runners: a good model outscores a
hallucinating one, and the gates flip accordingly."""

import json
from pathlib import Path

import pytest

from evals.harness.gates import resolve_gates
from evals.harness.run import load_cases
from evals.harness.runners import MockRunner, PromptTemplate
from evals.harness.schema import Scorecard
from evals.harness.scoring import make_scorecard, run_case

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CASES = load_cases("writing_feedback", ROOT / "evals" / "cases")
PROMPT = PromptTemplate("writing_feedback", ROOT / "prompts" / "runtime")


def good_output(case) -> str:
    errors = [
        {
            "tag": tag,
            "quote": "…",
            "correction": " / ".join(case.expect.must_contain) or "ok",
            "explanation": "seeded error corrected",
        }
        for tag in case.expect.must_identify
    ]
    return json.dumps(
        {
            "errors": errors,
            "model_answer": " ".join(case.expect.must_contain) or "Va bene così.",
            "strengths": "Clear structure.",
        },
        ensure_ascii=False,
    )


def bad_output(case) -> str:
    # Misses every seeded error and invents one from the forbidden list.
    invented = case.expect.must_not_claim[:1]
    return json.dumps(
        {
            "errors": [
                {"tag": t, "quote": "x", "correction": "y", "explanation": "wrong"}
                for t in invented
            ],
            "model_answer": "Boh.",
            "strengths": "",
        }
    )


def test_cases_load_and_prompt_renders():
    assert len(CASES) >= 10
    rendered = PROMPT.render(CASES[0])
    assert CASES[0].input.submission in rendered
    assert "JSON" in rendered


def test_good_model_beats_hallucinating_model_and_gates_flip(tmp_path):
    good = MockRunner({c.id: good_output(c) for c in CASES})
    bad = MockRunner({c.id: bad_output(c) for c in CASES})

    good_card = make_scorecard(
        "writing_feedback",
        "anthropic",
        PROMPT.version,
        CASES,
        [run_case(c, good, PROMPT) for c in CASES],
    )
    bad_card = make_scorecard(
        "writing_feedback",
        "apple_fm",
        PROMPT.version,
        CASES,
        [run_case(c, bad, PROMPT) for c in CASES],
    )

    assert good_card.mean_total > 0.95
    assert good_card.hallucination_rate == 0.0
    assert bad_card.mean_total < 0.6
    assert bad_card.hallucination_rate > 0.5

    resolved = resolve_gates(ROOT / "evals" / "gates.yaml", [good_card, bad_card])
    verdict = resolved["writing_feedback"]["apple_fm"]
    assert verdict["enabled"] is False
    assert "hallucination" in verdict["reason"] or "floor" in verdict["reason"]

    # A passing on-device card flips the gate on.
    passing = Scorecard(
        task="writing_feedback",
        runner="apple_fm",
        prompt_version=PROMPT.version,
        cases=len(CASES),
        mean_total=0.9,
        mean_deterministic=0.9,
        mean_judge=None,
        hallucination_rate=0.0,
        results=[],
    )
    resolved = resolve_gates(ROOT / "evals" / "gates.yaml", [good_card, passing])
    assert resolved["writing_feedback"]["apple_fm"]["enabled"] is True


def test_mistake_explanation_cases_load():
    cases = load_cases("mistake_explanation", ROOT / "evals" / "cases")
    assert len(cases) >= 4
    prompt = PromptTemplate("mistake_explanation", ROOT / "prompts" / "runtime")
    rendered = prompt.render(cases[0])
    assert "sono mangiato" in rendered
