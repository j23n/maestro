#!/usr/bin/env python3
"""CLI for reviewing and exporting LLM critique records.

Usage:
    uv run python scripts/critique.py list [--call-type scorer_multi] [--unexported]
    uv run python scripts/critique.py review <id>
    uv run python scripts/critique.py annotate <id> --expected '{"objective_correct": false}'
    uv run python scripts/critique.py export [--call-type scorer_multi]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pprint
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURE_MAP = {
    "scorer_multi": "tests/eval/fixtures/scoring_cases.json",
    "scorer_single": "tests/eval/fixtures/scoring_cases.json",
    "analyzer": "tests/eval/fixtures/analyzer_cases.json",
    "vocab_definition": "tests/eval/fixtures/vocab_cases.json",
    "grammar_explanation": "tests/eval/fixtures/grammar_explanation_cases.json",
    "lesson_feedback": "tests/eval/fixtures/writing_cases.json",
    "lesson_plan": "tests/eval/fixtures/planner_content_cases.json",
}

EVAL_TEST_MAP = {
    "analyzer": "test_analyzer_eval.py::test_analyzer_grammar_tagging",
    "scorer_multi": "test_scoring_eval.py",
    "scorer_single": "test_scoring_eval.py",
    "lesson_feedback": "test_writing_eval.py",
    "vocab_definition": "test_vocab_eval.py",
    "grammar_explanation": "test_grammar_explanations_eval.py",
    "lesson_plan": "test_planner_eval.py",
}


def _short_ts(dt) -> str:
    if dt is None:
        return "-"
    return str(dt)[:16].replace("T", " ")


def _truncate(s: str, n: int = 60) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def _print_review(critique) -> None:
    print(f"\n{'─' * 60}")
    ct_val = (
        critique.call_type.value
        if hasattr(critique.call_type, "value")
        else str(critique.call_type)
    )
    eval_test = EVAL_TEST_MAP.get(ct_val, "(unknown)")
    print(f"ID:             {critique.id}")
    print(f"call_type:      {critique.call_type}")
    print(f"eval_test:      {eval_test}")
    print(f"url:            {critique.url}")
    print(f"prompt_version: {critique.prompt_version}")
    print(f"created_at:     {critique.created_at}")
    print(f"exported:       {critique.exported}")
    print(f"refs:           {json.dumps(critique.refs)}")
    print("\nINPUT:")
    pprint.pprint(critique.input_snapshot, indent=2)
    print("\nACTUAL OUTPUT:")
    pprint.pprint(critique.actual_output, indent=2)
    expected = critique.expected_output or "(not set)"
    print(f"\nEXPECTED OUTPUT: {expected}")
    issue = critique.issue_description or "(none)"
    print(f"ISSUE:           {issue}")
    print(f"{'─' * 60}")


def _build_fixture_case(critique) -> dict | None:
    """Build a fixture case from the critique. Returns None if expected_output is not set."""
    if not critique.expected_output:
        return None

    try:
        expected = json.loads(critique.expected_output)
    except (json.JSONDecodeError, TypeError):
        expected = critique.expected_output

    case_id = f"critique_{str(critique.id)[:8]}"
    call_type_val = (
        critique.call_type.value
        if hasattr(critique.call_type, "value")
        else str(critique.call_type)
    )

    if call_type_val in ("scorer_multi", "scorer_single"):
        case = {
            "id": case_id,
            "exercise_type": critique.input_snapshot.get("exercise_type", ""),
            "grammar_point_code": critique.input_snapshot.get("grammar_point_code", ""),
            "prompt": critique.input_snapshot.get("prompt", ""),
            "correct_answer": critique.input_snapshot.get("correct_answer", ""),
            "student_answer": critique.input_snapshot.get("student_answer", ""),
            "expected_output": expected,
        }
        if isinstance(expected, dict) and "objective_correct" in expected:
            case["expected_objective_correct"] = expected["objective_correct"]
    elif call_type_val == "analyzer":
        case = {
            "id": case_id,
            "text": critique.input_snapshot.get("student_text", ""),
        }
        if isinstance(expected, dict):
            if "grammar_errors" in expected:
                case["must_appear_in_errors"] = expected.get("grammar_errors", [])
            if "grammar_correct" in expected:
                case["must_appear_in_correct"] = expected.get("grammar_correct", [])
                case["must_not_appear_in_errors"] = expected.get("grammar_correct", [])
    elif call_type_val == "vocab_definition":
        case = {
            "id": case_id,
            "word": critique.input_snapshot.get("word", ""),
            "part_of_speech": critique.input_snapshot.get("pos", ""),
            "senses": critique.input_snapshot.get("senses", []),
            "expected_output": expected,
        }
    elif call_type_val == "grammar_explanation":
        case = {
            "id": case_id,
            "code": critique.input_snapshot.get("code", ""),
            "label": critique.input_snapshot.get("label", ""),
            "description": critique.input_snapshot.get("description", ""),
            "expected_output": expected,
        }
    elif call_type_val == "lesson_feedback":
        case = {
            "id": case_id,
            "prompt": critique.input_snapshot.get("topic_title", ""),
            "student_text": " ".join(
                critique.input_snapshot.get("student_responses", [])
            ),
            "expected_objective_correct": True,
            "expected_output": expected,
        }
    elif call_type_val == "lesson_plan":
        case = {
            "id": case_id,
            "cefr_level": critique.input_snapshot.get("cefr_at_start", ""),
            "expected_output": expected,
        }
    else:
        case = {
            "id": case_id,
            "input_snapshot": critique.input_snapshot,
            "expected_output": expected,
        }

    return case


async def cmd_list(call_type: str | None, unexported: bool) -> None:
    from maestro.models import LLMCritique

    query: dict = {}
    if call_type:
        query["call_type"] = call_type
    if unexported:
        query["exported"] = False

    critiques = await LLMCritique.find(query).sort("-created_at").to_list()

    if not critiques:
        print("No critiques found.")
        return

    id_w = 24
    ct_w = 18
    ts_w = 16
    exp_w = 8
    has_exp_w = 8
    eval_w = 36
    issue_w = 40

    header = (
        f"{'ID':<{id_w}}  {'call_type':<{ct_w}}  {'created':<{ts_w}}  "
        f"{'exported':<{exp_w}}  {'has_expected':<{has_exp_w}}  "
        f"{'eval_test':<{eval_w}}  issue"
    )
    print(header)
    print("-" * len(header))

    for c in critiques:
        cid = str(c.id)
        ct = c.call_type.value if hasattr(c.call_type, "value") else str(c.call_type)
        ts = _short_ts(c.created_at)
        exp = "yes" if c.exported else "no"
        has_exp = "yes" if c.expected_output else "no"
        eval_test = _truncate(EVAL_TEST_MAP.get(ct, "(unknown)"), eval_w)
        issue = _truncate(c.issue_description or "", issue_w)
        print(
            f"{cid:<{id_w}}  {ct:<{ct_w}}  {ts:<{ts_w}}  "
            f"{exp:<{exp_w}}  {has_exp:<{has_exp_w}}  "
            f"{eval_test:<{eval_w}}  {issue}"
        )

    print(f"\nTotal: {len(critiques)}")


async def cmd_review(critique_id: str) -> None:
    from beanie import PydanticObjectId
    from maestro.models import LLMCritique

    try:
        oid = PydanticObjectId(critique_id)
    except Exception:
        print(f"Invalid ID: {critique_id}", file=sys.stderr)
        sys.exit(1)

    critique = await LLMCritique.get(oid)
    if critique is None:
        print(f"Not found: {critique_id}", file=sys.stderr)
        sys.exit(1)

    _print_review(critique)


async def cmd_annotate(critique_id: str, expected: str) -> None:
    from beanie import PydanticObjectId
    from maestro.models import LLMCritique

    try:
        oid = PydanticObjectId(critique_id)
    except Exception:
        print(f"Invalid ID: {critique_id}", file=sys.stderr)
        sys.exit(1)

    critique = await LLMCritique.get(oid)
    if critique is None:
        print(f"Not found: {critique_id}", file=sys.stderr)
        sys.exit(1)

    # Validate JSON
    try:
        json.loads(expected)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON for --expected: {exc}", file=sys.stderr)
        sys.exit(1)

    await critique.update({"$set": {"expected_output": expected}})
    print(f"Updated expected_output on {critique_id}")


async def cmd_export(call_type: str | None) -> None:
    from maestro.models import LLMCritique

    query: dict = {"exported": False}
    if call_type:
        query["call_type"] = call_type

    critiques = await LLMCritique.find(query).sort("-created_at").to_list()

    if not critiques:
        print("No unexported critiques found.")
        return

    for critique in critiques:
        _print_review(critique)

        if not critique.expected_output:
            print("Skipping — no expected_output. Use 'annotate' first.")
            continue

        answer = input("Export this as a test case? [y/N/q(uit)]: ").strip().lower()
        if answer == "q":
            print("Stopped.")
            break
        if answer != "y":
            print("Skipped.")
            continue

        ct_val = (
            critique.call_type.value
            if hasattr(critique.call_type, "value")
            else str(critique.call_type)
        )
        fixture_rel = FIXTURE_MAP.get(ct_val)
        if not fixture_rel:
            print(f"No fixture file mapped for call_type={ct_val}. Skipping.")
            continue

        fixture_path = REPO_ROOT / fixture_rel
        if not fixture_path.exists():
            print(f"Fixture file not found: {fixture_path}. Skipping.")
            continue

        case = _build_fixture_case(critique)
        if case is None:
            print("Skipping — no expected_output. Use 'annotate' first.")
            continue

        try:
            existing = json.loads(fixture_path.read_text())
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Could not read {fixture_path}: {exc}. Skipping.")
            continue

        existing.append(case)
        fixture_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"Appended case '{case['id']}' to {fixture_rel}")

        await critique.update({"$set": {"exported": True}})
        print(f"Marked {critique.id} as exported.")


async def main_async(args: argparse.Namespace) -> None:
    from maestro.db import init_db

    await init_db()

    if args.command == "list":
        await cmd_list(args.call_type, args.unexported)
    elif args.command == "review":
        await cmd_review(args.id)
    elif args.command == "annotate":
        await cmd_annotate(args.id, args.expected)
    elif args.command == "export":
        await cmd_export(args.call_type)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review and export LLM critique records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List critique records")
    p_list.add_argument("--call-type", help="Filter by call type (e.g. scorer_multi)")
    p_list.add_argument(
        "--unexported", action="store_true", help="Show only unexported records"
    )

    # review
    p_review = sub.add_parser("review", help="Show full details of a critique")
    p_review.add_argument("id", help="LLMCritique document ID")

    # annotate
    p_annotate = sub.add_parser("annotate", help="Set expected_output on a critique")
    p_annotate.add_argument("id", help="LLMCritique document ID")
    p_annotate.add_argument(
        "--expected",
        required=True,
        help="Expected output as JSON string",
    )

    # export
    p_export = sub.add_parser(
        "export", help="Interactively export critiques as test cases"
    )
    p_export.add_argument("--call-type", help="Filter by call type")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
