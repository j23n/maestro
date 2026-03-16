"""Compare scoring accuracy between models (e.g. Sonnet vs Haiku).

Runs the same fixture cases through each model and records per-model metrics
so results can be compared side-by-side in evals/results.jsonl.
"""

import json
import logging
import os
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from maestro.config import settings

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"

MODELS = [
    m.strip()
    for m in os.environ.get(
        "SCORING_COMPARE_MODELS",
        "claude-sonnet-4-6,claude-haiku-4-5-20251001",
    ).split(",")
    if m.strip()
]


def _make_item(prompt: str, correct_answer: str) -> MagicMock:
    item = MagicMock()
    item.prompt = prompt
    item.correct_answer = correct_answer
    return item


@pytest.fixture(autouse=True)
def seed_cache_for_scoring():
    """Seed taxonomy cache with all A1 GPs.

    Scoring cases reference specific GPs, but reading/writing subtests also
    build a system prompt with _grammar_code_list("A1"), so we seed the full
    A1 set rather than just the codes from scoring_cases.json.

    Note: the standalone test_scoring_eval seeds only fixture-referenced GPs
    (1 GP) to keep the prompt small and maximise accuracy.  Here we use the
    full A1 set (48 GPs) — accuracy numbers are therefore not directly
    comparable across the two tests, but the model-vs-model comparison
    within this test is valid since all models see the same prompt.
    """
    from maestro import taxonomy

    gps = yaml.safe_load((_DATA_DIR / "grammar_points.yaml").read_text())
    a1_gps = [g for g in gps if g.get("cefr_level") == "A1"]

    taxonomy.seed(gps=[SimpleNamespace(**g) for g in a1_gps])
    yield
    taxonomy.invalidate()


def _compute_metrics(results: list[dict]) -> dict:
    tp = fp = fn = tn = 0
    for r in results:
        expected, got = r["expected"], r["got"]
        if expected and got:
            tp += 1
        elif not expected and got:
            fp += 1
        elif expected and not got:
            fn += 1
        else:
            tn += 1
    n = len(results)
    return {
        "n": n,
        "accuracy": round((tp + tn) / max(1, n), 4),
        "precision": round(tp / max(1, tp + fp), 4),
        "recall": round(tp / max(1, tp + fn), 4),
        "fp_rate": round(fp / max(1, fp + tn), 4),
        "failed": [r["id"] for r in results if not r["pass"]],
    }


async def _run_scoring_cases(cases: list[dict]) -> tuple[list[dict], list[tuple]]:
    """Run fill-blank/error-correction scoring cases. Returns (results, case_scores)."""
    from maestro.learning.scorer import score_multi_item_drill

    results = []
    case_scores = []
    for case in cases:
        item = _make_item(case["prompt"], case["correct_answer"])
        raw = await score_multi_item_drill(
            exercise_type=case["exercise_type"],
            grammar_point_code=case["grammar_point_code"],
            items=[item],
            student_answers=[case["student_answer"]],
        )
        got = raw[0]["objective_correct"] if raw else False
        expected = case["expected_objective_correct"]
        results.append(
            {
                "id": case["id"],
                "got": got,
                "expected": expected,
                "pass": got == expected,
            }
        )
        case_scores.append((case, raw[0] if raw else {}))
    return results, case_scores


async def _run_reading_cases(cases: list[dict]) -> list[dict]:
    """Run reading comprehension cases. Returns flat results list."""
    from maestro.learning.scorer import score_reading_answers

    results = []
    for case in cases:
        scored = await score_reading_answers(
            questions=case["questions"],
            correct_answers=case["correct_answers"],
            student_answers=case["student_answers"],
        )
        for i, (item, expected) in enumerate(zip(scored, case["expected_results"])):
            got = (
                item.get("objective_correct", False)
                if isinstance(item, dict)
                else False
            )
            results.append(
                {
                    "id": f"{case['id']}_q{i + 1}",
                    "got": got,
                    "expected": expected,
                    "pass": got == expected,
                }
            )
    return results


async def _run_writing_cases(cases: list[dict]) -> list[dict]:
    """Run writing feedback cases. Returns results list."""
    from maestro.learning.scorer import generate_writing_feedback

    results = []
    for case in cases:
        feedback = await generate_writing_feedback(
            prompt=case["prompt"],
            student_text=case["student_text"],
            cefr_level="A1",
        )
        got = (
            feedback.get("objective_correct", True)
            if isinstance(feedback, dict)
            else True
        )
        expected = case["expected_objective_correct"]
        results.append(
            {
                "id": case["id"],
                "got": got,
                "expected": expected,
                "pass": got == expected,
            }
        )
    return results


def _judge_scoring_cases(case_scores: list[tuple]) -> float:
    """Run LLM-as-judge on scoring case feedback. Returns content_quality ratio."""
    import json as _json
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    passed = total = 0
    for case, scored in case_scores:
        total += 1
        correct_mark = "correct" if scored.get("objective_correct") else "incorrect"
        tips = scored.get("tips", [])
        note = scored.get("objective_note", "") or scored.get("explanation", "")
        generated = f"scored={correct_mark}, tips={tips}, note={note!r}"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f'{case["exercise_type"]} — student: "{case["student_answer"]}", correct: "{case["correct_answer"]}"',
            )
        else:
            prompt = (
                f'Exercise: {case["exercise_type"]} — "{case["prompt"]}" correct: "{case["correct_answer"]}"\n'
                f'Student answer: "{case["student_answer"]}"\n'
                f'Scored: {correct_mark}\nTips: {tips}\nNote: "{note}"\n\n'
                f"Is this feedback helpful and accurate for an Italian learner?"
            )
            ok, reason = _judge(prompt)
        if ok:
            passed += 1
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")
    return passed / max(1, total)


@pytest.mark.llm_eval
async def test_scoring_model_comparison(db, record_eval, record_item, monkeypatch):
    """Compare scoring accuracy and content quality across models."""
    scoring_cases = json.loads((FIXTURES_DIR / "scoring_cases.json").read_text())
    reading_cases = json.loads((FIXTURES_DIR / "reading_cases.json").read_text())
    writing_cases = json.loads((FIXTURES_DIR / "writing_cases.json").read_text())

    all_model_metrics = {}

    for model in MODELS:
        monkeypatch.setattr(settings, "SCORING_MODEL", model)
        logger.info(f"[eval] === Running scoring comparison with model: {model} ===")

        # --- Scoring (fill-blank + error-correction) ---
        scoring_results, scoring_case_scores = await _run_scoring_cases(scoring_cases)
        scoring_metrics = _compute_metrics(scoring_results)
        scoring_quality = _judge_scoring_cases(scoring_case_scores)

        logger.info(
            f"[eval] {model} scoring: accuracy={scoring_metrics['accuracy']:.2%}, "
            f"content_quality={scoring_quality:.2%}, failed={scoring_metrics['failed']}"
        )

        record_eval(
            "scorer",
            {
                **scoring_metrics,
                "content_quality": round(scoring_quality, 4),
                "test": "scoring_compare",
                "model": model,
                "subtest": "scoring",
            },
        )
        for r in scoring_results:
            record_item(
                "scorer",
                {
                    "test": "scoring_compare",
                    "model": model,
                    "subtest": "scoring",
                    "case_id": r["id"],
                    "pass": r["pass"],
                    "got": r["got"],
                    "expected": r["expected"],
                },
            )

        # --- Reading comprehension ---
        reading_results = await _run_reading_cases(reading_cases)
        reading_metrics = _compute_metrics(reading_results)

        logger.info(
            f"[eval] {model} reading: accuracy={reading_metrics['accuracy']:.2%}, "
            f"failed={reading_metrics['failed']}"
        )

        record_eval(
            "scorer",
            {
                **reading_metrics,
                "test": "scoring_compare",
                "model": model,
                "subtest": "reading",
            },
        )
        for r in reading_results:
            record_item(
                "scorer",
                {
                    "test": "scoring_compare",
                    "model": model,
                    "subtest": "reading",
                    "case_id": r["id"],
                    "pass": r["pass"],
                    "got": r["got"],
                    "expected": r["expected"],
                },
            )

        # --- Writing ---
        writing_results = await _run_writing_cases(writing_cases)
        writing_metrics = _compute_metrics(writing_results)

        logger.info(
            f"[eval] {model} writing: accuracy={writing_metrics['accuracy']:.2%}, "
            f"failed={writing_metrics['failed']}"
        )

        record_eval(
            "scorer",
            {
                **writing_metrics,
                "test": "scoring_compare",
                "model": model,
                "subtest": "writing",
            },
        )
        for r in writing_results:
            record_item(
                "scorer",
                {
                    "test": "scoring_compare",
                    "model": model,
                    "subtest": "writing",
                    "case_id": r["id"],
                    "pass": r["pass"],
                    "got": r["got"],
                    "expected": r["expected"],
                },
            )

        all_model_metrics[model] = {
            "scoring": {
                **scoring_metrics,
                "content_quality": round(scoring_quality, 4),
            },
            "reading": reading_metrics,
            "writing": writing_metrics,
        }

    # --- Pairwise agreement: how often each pair of models agrees vs golden truth ---
    for m1, m2 in combinations(MODELS, 2):
        for subtest in ("scoring", "reading", "writing"):
            m1_failed = set(all_model_metrics[m1][subtest]["failed"])
            m2_failed = set(all_model_metrics[m2][subtest]["failed"])
            n = all_model_metrics[m1][subtest]["n"]
            disagree = m1_failed.symmetric_difference(m2_failed)
            agreement = round((n - len(disagree)) / max(1, n), 4)
            logger.info(
                f"[eval] {subtest} agreement ({m1} vs {m2}): {agreement:.2%}, "
                f"disagree_ids={disagree or 'none'}"
            )

            record_eval(
                "scorer",
                {
                    "test": "scoring_compare",
                    "subtest": f"{subtest}_agreement",
                    "agreement": agreement,
                    "n": n,
                    "model": f"{m1}_vs_{m2}",
                },
            )

    # --- Summary log ---
    for model, metrics in all_model_metrics.items():
        logger.info(
            f"[eval] SUMMARY {model}: "
            f"scoring={metrics['scoring']['accuracy']:.2%} (quality={metrics['scoring']['content_quality']:.2%}), "
            f"reading={metrics['reading']['accuracy']:.2%}, "
            f"writing={metrics['writing']['accuracy']:.2%}"
        )

    # --- Floor assertions: each model must meet minimum thresholds ---
    for model, metrics in all_model_metrics.items():
        scoring_acc = metrics["scoring"]["accuracy"]
        reading_acc = metrics["reading"]["accuracy"]
        writing_acc = metrics["writing"]["accuracy"]
        content_q = metrics["scoring"]["content_quality"]

        assert scoring_acc >= 0.80, (
            f"{model} scoring accuracy too low: {scoring_acc:.2%} "
            f"(failed: {metrics['scoring']['failed']})"
        )
        assert reading_acc >= 0.80, (
            f"{model} reading accuracy too low: {reading_acc:.2%} "
            f"(failed: {metrics['reading']['failed']})"
        )
        assert writing_acc >= 0.80, (
            f"{model} writing accuracy too low: {writing_acc:.2%} "
            f"(failed: {metrics['writing']['failed']})"
        )
        assert content_q >= 0.50, (
            f"{model} scoring content quality too low: {content_q:.2%}"
        )
