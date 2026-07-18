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
    assert len(cases) >= 8
    prompt = PromptTemplate("mistake_explanation", ROOT / "prompts" / "runtime")
    rendered = prompt.render(cases[0])
    assert "sono mangiato" in rendered


def test_hallucination_is_a_typed_flag():
    case = next(c for c in CASES if c.expect.must_not_claim)
    bad = MockRunner({case.id: bad_output(case)})
    result = run_case(case, bad, PROMPT)
    assert result.hallucinated is True
    good = MockRunner({case.id: good_output(case)})
    assert run_case(case, good, PROMPT).hallucinated is False


def test_judge_metadata_recorded_on_scorecard():
    case = CASES[0]
    runner = MockRunner({case.id: good_output(case)})

    # The judge consumes the versioned prompt file, not an f-string.
    from evals.harness.scoring import judge_prompt, load_judge_prompt

    assert load_judge_prompt(1)["version"] == 1
    assert "grading" in judge_prompt(case, "output")

    class JudgeMock:
        name = "mock-judge"

        def run(self, case, prompt):
            return '{"corrections_are_correct": 1, "explanations_clear": 1}'

    results = [run_case(case, runner, PROMPT, JudgeMock())]
    card = make_scorecard(
        "writing_feedback",
        "anthropic",
        PROMPT.version,
        [case],
        results,
        judge_model="claude-opus-4-8",
        judge_prompt_version=1,
    )
    assert card.judge_model == "claude-opus-4-8"
    assert card.judge_prompt_version == 1
    assert card.mean_judge == 1.0


def test_speaking_feedback_cases_and_prompt():
    cases = load_cases("speaking_feedback", ROOT / "evals" / "cases")
    assert len(cases) >= 6
    prompt = PromptTemplate("speaking_feedback", ROOT / "prompts" / "runtime")
    rendered = prompt.render(cases[0])
    assert "vada" in rendered  # transcript reaches the template
    assert "Oggi vado al mare" in rendered  # target reaches the template
    # The clean canary exists.
    assert any(not c.expect.must_identify for c in cases)


def test_must_not_contain_counts_as_hallucination():
    cases = load_cases("mistake_explanation", ROOT / "evals" / "cases")
    case = next(c for c in cases if c.expect.must_not_contain)
    prompt = PromptTemplate("mistake_explanation", ROOT / "prompts" / "runtime")
    bad = MockRunner(
        {
            case.id: json.dumps(
                {
                    "explanation": f"Use {case.expect.must_not_contain[0]}!",
                    "contrast_example": "x",
                    "rule_reminder": " ".join(case.expect.must_contain),
                }
            )
        }
    )
    result = run_case(case, bad, prompt)
    assert result.hallucinated is True


CANNED_DRILL_BATCH = """\
```yaml
- item_type: drill_cloze
  cefr_level: A0
  prompt: "Io ___ Marco."
  answers:
    - { text: "sono", canonical: true }
  distractor_feedback:
    "sei": "«Sei» is the *tu* form. With «io», use «sono»."
  explanation: "Essere: io sono."
  evidence:
    - { axis: grammar, id: essere_pre, weight: 1.0 }
- item_type: drill_cloze
  cefr_level: A0
  prompt: "Tu ___ italiana?"
  answers:
    - { text: "sei", canonical: true }
  explanation: "Essere: tu sei."
  evidence:
    - { axis: grammar, id: essere_pre, weight: 1.0 }
```
"""


def test_content_generation_task_scores_real_batches():
    from evals.harness.content_gen import build_case_prompt, run_content_case

    cases = load_cases("content_generation", ROOT / "evals" / "cases")
    assert len(cases) >= 4
    case = next(c for c in cases if c.id == "cg.drill.essere")

    # The eval consumes the REAL authoring prompt.
    prompt, scope, kind = build_case_prompt(case)
    assert "essere_pre" in prompt.render(case)
    assert kind.name == "drill"

    good = MockRunner({case.id: CANNED_DRILL_BATCH})
    result = run_content_case(case, good)
    assert result.deterministic_score == 1.0, result.failures

    # A batch that violates the vocab constraint is penalized, not passed.
    dirty = MockRunner(
        {case.id: CANNED_DRILL_BATCH.replace("italiana", "velenosissima")}
    )
    result = run_content_case(case, dirty)
    assert result.deterministic_score < 1.0
    assert any("velenosissima" in f for f in result.failures)

    # A batch that doesn't parse scores zero.
    broken = MockRunner({case.id: "not yaml at all"})
    assert run_content_case(case, broken).deterministic_score == 0.0


def test_seed_cases_produces_hand_checkable_drafts():
    from evals.seed_cases import seed_cases

    cases = seed_cases(ROOT / "packs" / "it", limit=10)
    assert len(cases) >= 2
    for c in cases:
        assert c["expect"]["must_identify"], c["id"]
        assert "HAND-CHECK" in c["seeding_note"]
        # The seeded text differs from any pack sentence by construction.
        assert c["input"]["submission"]
