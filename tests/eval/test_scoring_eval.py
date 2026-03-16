"""LLM eval tests for drill scoring accuracy."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"


def _make_item(prompt: str, correct_answer: str) -> MagicMock:
    item = MagicMock()
    item.prompt = prompt
    item.correct_answer = correct_answer
    return item


@pytest.fixture(autouse=True)
def seed_cache_for_scoring():
    """Seed taxonomy cache with only the GPs referenced in the scoring fixtures.

    Using the full 231-GP list makes the grammar_code_list section of the
    score_multi_item_drill prompt enormous and degrades model accuracy.
    """
    from maestro import taxonomy

    cases = json.loads((FIXTURES_DIR / "scoring_cases.json").read_text())
    codes = {c["grammar_point_code"] for c in cases}

    gps = yaml.safe_load((_DATA_DIR / "grammar_points.yaml").read_text())
    relevant = [g for g in gps if g["code"] in codes]

    taxonomy.seed(gps=[SimpleNamespace(**g) for g in relevant])

    yield

    taxonomy.invalidate()


@pytest.mark.llm_eval
async def test_scoring_accuracy(db, record_eval, record_item):
    """Measure accuracy of fill_blank and error_correction scoring against golden cases."""
    import json as _json
    from maestro.learning.scorer import score_multi_item_drill
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "scoring_cases.json").read_text())

    tp = fp = fn = tn = 0
    results = []
    case_scores = []  # store (case, raw_result) for judging

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
        passed = got == expected

        if expected and got:
            tp += 1
        elif not expected and got:
            fp += 1
        elif expected and not got:
            fn += 1
        else:
            tn += 1

        results.append(
            {
                "id": case["id"],
                "got": got,
                "expected": expected,
                "pass": passed,
            }
        )
        case_scores.append((case, raw[0] if raw else {}))
        logger.info(
            f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} got={got} expected={expected}"
        )

    item_data: dict[str, dict] = {}
    for r in results:
        item_data[r["id"]] = {
            "pass": r["pass"],
            "got": r.get("got"),
            "expected": r.get("expected"),
        }

    n = len(cases)
    accuracy = (tp + tn) / max(1, n)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    fp_rate = fp / max(1, fp + tn)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Scoring: accuracy={accuracy:.2%}, precision={precision:.2%}, "
        f"recall={recall:.2%}, fp_rate={fp_rate:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate feedback quality per case
    judge_passed = 0
    judge_total = 0
    for case, scored in case_scores:
        judge_total += 1
        correct_mark = "correct ✓" if scored.get("objective_correct") else "incorrect ✗"
        tips = scored.get("tips", [])
        tips_str = str(tips) if tips else "(none)"
        note = scored.get("objective_note", "") or scored.get("explanation", "")
        generated = f"scored={correct_mark}, tips={tips_str}, note={note!r}"
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
                f"Scored: {correct_mark}\n"
                f"Tips: {tips_str}\n"
                f'Note: "{note}"\n\n'
                f"Is this feedback helpful and accurate for an Italian learner?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        if case["id"] in item_data:
            item_data[case["id"]]["judge_pass"] = ok
            item_data[case["id"]]["judge_reason"] = reason
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    for case_id, data in item_data.items():
        record_item("analyzer", {"test": "scoring", "case_id": case_id, **data})

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Scoring content_quality={content_quality:.2%}")

    record_eval(
        "analyzer",
        {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fp_rate": round(fp_rate, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "scoring",
        },
    )

    assert accuracy >= 0.98, (
        f"Scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Scoring feedback content quality too low: {content_quality:.2%}"
    )
