#!/usr/bin/env python3
"""Eval results analysis tool.

Subcommands:
    (none)     Summary: latest run per group                    [default]
    history    Full run history with regression warnings
    diff       Version-to-version or run-to-run metric delta
    models     Model side-by-side comparison
    failures   Per-item failures (from items.jsonl, or 'failed' lists in results)

Filters (work on all subcommands):
    --prompt NAME   Filter by prompt  (e.g. analyzer, scorer)
    --test NAME     Filter by test    (e.g. grammar_tagging, scoring_compare)
    --model NAME    Filter by model   (e.g. claude-sonnet-4-6)

Examples:
    python evals/compare.py
    python evals/compare.py --prompt analyzer
    python evals/compare.py history --prompt analyzer --last 5
    python evals/compare.py diff --prompt analyzer --test grammar_tagging
    python evals/compare.py diff --prompt analyzer --from 1 --to 2
    python evals/compare.py models --prompt scorer
    python evals/compare.py failures --prompt scorer --test scoring_compare
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "results.jsonl"
ITEMS_FILE = Path(__file__).parent / "items.jsonl"

# Ordered display list of numeric metrics
METRICS = [
    "precision",
    "recall",
    "fp_rate",
    "accuracy",
    "output_syntax",
    "content_quality",
    "agreement",
    "pass_rate",
]
HIGHER_IS_WORSE = frozenset({"fp_rate"})


# ── Data loading ──────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_results(
    prompt: str | None = None,
    model: str | None = None,
    test: str | None = None,
) -> list[dict]:
    rows = _read_jsonl(RESULTS_FILE)
    if prompt:
        rows = [r for r in rows if r.get("prompt") == prompt]
    if model:
        rows = [r for r in rows if r.get("model") == model]
    if test:
        rows = [r for r in rows if r.get("test") == test]
    return rows


def load_items(
    prompt: str | None = None,
    model: str | None = None,
    test: str | None = None,
) -> list[dict]:
    rows = _read_jsonl(ITEMS_FILE)
    if prompt:
        rows = [r for r in rows if r.get("prompt") == prompt]
    if model:
        rows = [r for r in rows if r.get("model") == model]
    if test:
        rows = [r for r in rows if r.get("test") == test]
    return rows


# ── Grouping ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, order=True)
class GroupKey:
    prompt: str
    version: str
    test: str  # "" when absent
    model: str  # "" when absent
    subtest: str  # "" when absent


def _key(row: dict) -> GroupKey:
    return GroupKey(
        prompt=row.get("prompt") or "?",
        version=row.get("version") or "?",
        test=row.get("test") or "",
        model=row.get("model") or "",
        subtest=row.get("subtest") or "",
    )


def group_runs(rows: list[dict]) -> dict[GroupKey, list[dict]]:
    """Group rows by GroupKey, sorted by timestamp within each group."""
    groups: dict[GroupKey, list[dict]] = defaultdict(list)
    for row in rows:
        groups[_key(row)].append(row)
    return {k: sorted(v, key=lambda r: r.get("ts", "")) for k, v in groups.items()}


# ── Formatting ────────────────────────────────────────────────────────────────


def _fmt(val: object) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.2%}"
    return str(val)


def _delta(before: object, after: object, metric: str) -> str:
    """Format a before→after delta with direction marker."""
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "-"
    d = float(after) - float(before)
    if abs(d) < 0.0005:
        return "~0%"
    worse = (d > 0) if metric in HIGHER_IS_WORSE else (d < 0)
    sign = "+" if d > 0 else ""
    suffix = " ⚠" if worse else ""
    return f"{sign}{d:.2%}{suffix}"


def _present(rows: list[dict]) -> list[str]:
    """Return metrics that appear in at least one row."""
    return [m for m in METRICS if any(m in r for r in rows)]


def _ts(row: dict) -> str:
    ts = row.get("ts", "")
    return ts[:16].replace("T", " ") if ts else "-"


def _short_model(model: str) -> str:
    """claude-haiku-4-5-20251001 → haiku, compound names preserved."""
    parts = [n for n in ("haiku", "sonnet", "opus") if n in model.lower()]
    return "_vs_".join(parts) if parts else model


def _regressions(prev: dict, curr: dict, metrics: list[str]) -> list[str]:
    """Return regression warning lines comparing two consecutive runs."""
    out = []
    for m in metrics:
        p, c = prev.get(m), curr.get(m)
        if not isinstance(p, (int, float)) or not isinstance(c, (int, float)):
            continue
        worse = (c > p) if m in HIGHER_IS_WORSE else (c < p)
        if worse:
            out.append(f"     ⚠  {m}  {_fmt(p)} → {_fmt(c)}")
    return out


def _section(title: str) -> str:
    pad = max(0, 56 - len(title))
    return f"── {title} {'─' * pad}"


def _no_results() -> None:
    print("No results found. Run eval tests first:")
    print("  uv run pytest -m llm_eval tests/eval/")


# ── Summary ───────────────────────────────────────────────────────────────────


def cmd_summary(rows: list[dict]) -> None:
    """Latest snapshot per group — answers 'where are we right now?'"""
    if not rows:
        _no_results()
        return

    groups = group_runs(rows)
    present = _present(rows)
    has_subtests = any(key.subtest for key in groups)

    # Build one display row per group (latest run)
    cols = ["prompt", "v", "test"]
    if has_subtests:
        cols.append("subtest")
    cols += ["model"] + present + ["n", "ts"]
    widths = {c: len(c) for c in cols}

    table: list[tuple[GroupKey, dict[str, str]]] = []
    for key in sorted(groups):
        row = groups[key][-1]
        tr: dict[str, str] = {
            "prompt": key.prompt,
            "v": key.version,
            "test": key.test or "—",
            "subtest": key.subtest or "",
            "model": _short_model(key.model) if key.model else "—",
        }
        for m in present:
            tr[m] = _fmt(row.get(m))
        tr["n"] = str(row.get("n", "?"))
        tr["ts"] = _ts(row)
        table.append((key, tr))
        for c in cols:
            widths[c] = max(widths[c], len(tr[c]))

    sep = "  "
    print(sep.join(c.ljust(widths[c]) for c in cols))
    print(sep.join("-" * widths[c] for c in cols))

    prev_prompt = None
    for key, tr in table:
        if prev_prompt and key.prompt != prev_prompt:
            print()
        prev_prompt = key.prompt
        print(sep.join(tr[c].ljust(widths[c]) for c in cols))

    print(f"\n{len(groups)} groups  |  {RESULTS_FILE}")
    print("Subcommands: history | diff | models | failures")


# ── History ───────────────────────────────────────────────────────────────────


def cmd_history(rows: list[dict], last: int | None) -> None:
    """Full run history per group with regression warnings between consecutive runs."""
    if not rows:
        _no_results()
        return

    # Group by (prompt, test, model, subtest) — omit version so runs across
    # all versions appear together in one chronological timeline.
    cross_version: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        k = (
            row.get("prompt") or "?",
            row.get("test") or "",
            row.get("model") or "",
            row.get("subtest") or "",
        )
        cross_version[k].append(row)
    cross_version = {
        k: sorted(v, key=lambda r: r.get("ts", "")) for k, v in cross_version.items()
    }

    present = _present(rows)

    for prompt, test, model, subtest in sorted(cross_version):
        runs = cross_version[(prompt, test, model, subtest)]
        runs = runs[-last:] if last else runs

        parts = [prompt]
        if test:
            parts.append(test)
        if model:
            parts.append(_short_model(model))
        if subtest:
            parts.append(subtest)
        print(f"\n{_section('  '.join(parts))}")

        has_judge = any("judge_model" in r for r in runs)
        sub_cols = ["ts", "v"] + present + ["n"]
        if has_judge:
            sub_cols.append("judge")
        widths = {m: max(len(m), 7) for m in sub_cols}
        widths["ts"] = 16
        widths["v"] = max(1, max(len(r.get("version") or "?") for r in runs))
        widths["n"] = max(3, len(str(max((r.get("n", 0) or 0) for r in runs))))
        if has_judge:

            def _judge_label(r: dict) -> str:
                m = _short_model(r.get("judge_model", "") or "") or "-"
                v = r.get("judge_version", "")
                return f"{m} v{v}" if v else m

            widths["judge"] = max(len("judge"), max(len(_judge_label(r)) for r in runs))

        print("  " + "  ".join(c.ljust(widths[c]) for c in sub_cols))
        print("  " + "  ".join("-" * widths[c] for c in sub_cols))

        prev = None
        for run in runs:
            vals = {
                "ts": _ts(run),
                "v": run.get("version") or "?",
                "n": str(run.get("n", "?")),
            }
            for m in present:
                vals[m] = _fmt(run.get(m))
            if has_judge:
                vals["judge"] = _judge_label(run)
            print("  " + "  ".join(vals[c].ljust(widths[c]) for c in sub_cols))
            if prev:
                for warn in _regressions(prev, run, present):
                    print(warn)
            prev = run

    print(f"\nTotal groups: {len(cross_version)}  |  {RESULTS_FILE}")


# ── Diff ──────────────────────────────────────────────────────────────────────


def cmd_diff(
    rows: list[dict],
    from_ver: str | None,
    to_ver: str | None,
) -> None:
    """Compare two versions (or last two runs of same version) per group."""
    if bool(from_ver) != bool(to_ver):
        print("Provide both --from and --to, or neither.")
        return
    if from_ver and to_ver and from_ver == to_ver:
        print("--from and --to are the same version; nothing to compare.")
        return
    if not rows:
        _no_results()
        return

    groups = group_runs(rows)
    present = _present(rows)
    printed = False

    for key in sorted(groups):
        all_runs = groups[key]

        if from_ver or to_ver:
            fv = from_ver or to_ver
            tv = to_ver or from_ver
            before_runs = [r for r in all_runs if r.get("version") == fv]
            after_runs = [r for r in all_runs if r.get("version") == tv]
            if not before_runs or not after_runs:
                continue
            before, after = before_runs[-1], after_runs[-1]
        else:
            if len(all_runs) < 2:
                continue
            before, after = all_runs[-2], all_runs[-1]

        parts = [f"{key.prompt}"]
        if key.test:
            parts.append(key.test)
        if key.model:
            parts.append(_short_model(key.model))
        if key.subtest:
            parts.append(key.subtest)
        bv, av = before.get("version", "?"), after.get("version", "?")
        ver_label = f"v{bv} → v{av}" if bv != av else f"v{bv} run-to-run"
        print(f"\n{_section('  '.join(parts) + '  ' + ver_label)}")
        print(f"  {_ts(before)}  →  {_ts(after)}\n")

        mw, vw, dw = 16, 9, 14
        print(f"  {'metric':<{mw}}  {'before':>{vw}}  {'after':>{vw}}  delta")
        print(f"  {'-' * mw}  {'-' * vw}  {'-' * vw}  {'-' * dw}")

        for m in present:
            bval, aval = before.get(m), after.get(m)
            if bval is None and aval is None:
                continue
            d = _delta(bval, aval, m)
            print(f"  {m:<{mw}}  {_fmt(bval):>{vw}}  {_fmt(aval):>{vw}}  {d}")

        bn, an = str(before.get("n", "?")), str(after.get("n", "?"))
        print(f"  {'n':<{mw}}  {bn:>{vw}}  {an:>{vw}}")
        printed = True

    if not printed:
        hint = " (need ≥2 runs per group, or specify --from V --to V)"
        print(f"No comparable pairs found{hint}.")

    print(f"\n{RESULTS_FILE}")


# ── Models ────────────────────────────────────────────────────────────────────


def cmd_models(rows: list[dict]) -> None:
    """Side-by-side model comparison for same prompt+test+subtest."""
    if not rows:
        _no_results()
        return

    # Exclude compound-model rows (agreement rows like "sonnet_vs_haiku")
    rows = [r for r in rows if "_vs_" not in (r.get("model") or "")]

    models = sorted({r.get("model", "") for r in rows if r.get("model")})
    if len(models) < 2:
        print(
            f"Need ≥2 models to compare. Found: {models or ['(none — try without --model filter)']}"
        )
        return

    # Group by (prompt, version, test, subtest), model is the column
    @dataclass(frozen=True, order=True)
    class SliceKey:
        prompt: str
        version: str
        test: str
        subtest: str

    slices: dict[SliceKey, dict[str, dict]] = defaultdict(dict)
    for key, group_rows in group_runs(rows).items():
        if not key.model:
            continue
        sk = SliceKey(key.prompt, key.version, key.test, key.subtest)
        slices[sk][key.model] = group_rows[-1]  # latest run per model

    present = _present(rows)
    short = [_short_model(m) for m in models]
    model_w = max(9, max(len(s) for s in short))

    for sk in sorted(slices):
        model_rows = slices[sk]
        if len(model_rows) < 2:
            continue

        parts = [f"{sk.prompt} v{sk.version}"]
        if sk.test:
            parts.append(sk.test)
        if sk.subtest:
            parts.append(sk.subtest)
        print(f"\n{_section('  '.join(parts))}")

        delta_col = len(models) == 2
        delta_label = f"Δ {short[0]}→{short[-1]}" if delta_col else ""
        header = f"  {'metric':<16}  " + "  ".join(s.ljust(model_w) for s in short)
        if delta_col:
            header += f"  {delta_label}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        for m in present + ["n"]:
            vals = {mod: model_rows.get(mod, {}).get(m) for mod in models}
            if all(v is None for v in vals.values()):
                continue
            line = f"  {m:<16}  " + "  ".join(
                _fmt(vals[mod]).ljust(model_w) for mod in models
            )
            if delta_col and m != "n":
                bval, aval = vals[models[0]], vals[models[1]]
                line += f"  {_delta(bval, aval, m)}"
            print(line)

    print(f"\nModels compared: {', '.join(short)}")
    print(RESULTS_FILE)


# ── Failures ──────────────────────────────────────────────────────────────────


def _is_failure(item: dict) -> bool:
    """True if item failed on objective check OR content-quality judge."""
    return (not item.get("pass", True)) or (item.get("judge_pass") is False)


def _fail_type(item: dict) -> str:
    obj = not item.get("pass", True)
    qual = item.get("judge_pass") is False
    if obj and qual:
        return "obj+quality"
    if obj:
        return "objective"
    return "quality"


def cmd_failures(rows: list[dict], items: list[dict], latest: bool = False) -> None:
    """Per-item failures: objective failures + content-quality failures.

    Uses items.jsonl when available (written by record_item fixture).
    Falls back to 'failed' case ID lists embedded in results.jsonl.

    For items with a 'model' field (e.g. scoring_compare), shows a
    side-by-side multi-model comparison table.
    """
    if latest and items:
        # Find the max version per (prompt, test, model, subtest) group
        max_version: dict[tuple, str] = {}
        for item in items:
            gk = (
                item.get("prompt", ""),
                item.get("test", ""),
                item.get("model", ""),
                item.get("subtest", ""),
            )
            v = item.get("version") or ""
            if gk not in max_version or v > max_version[gk]:
                max_version[gk] = v
        items = [
            i
            for i in items
            if (i.get("version") or "")
            == max_version.get(
                (
                    i.get("prompt", ""),
                    i.get("test", ""),
                    i.get("model", ""),
                    i.get("subtest", ""),
                ),
                "",
            )
        ]

    printed = False

    # ── Per-item view from items.jsonl ────────────────────────────────────────
    if items:
        # Group items by run (run_ts or ts as fallback)
        run_groups: dict[tuple, list[dict]] = defaultdict(list)
        for item in items:
            rk = (
                item.get("prompt", "?"),
                item.get("version", "?"),
                item.get("test", ""),
                item.get("model", ""),
                item.get("subtest", ""),
                item.get("run_ts") or item.get("ts", ""),
            )
            run_groups[rk].append(item)

        # Keep only the latest run per (prompt, version, test, model, subtest)
        latest_run_by_group: dict[tuple, tuple[str, list[dict]]] = {}
        for rk, rk_items in run_groups.items():
            group = rk[:5]
            ts = rk[5]
            if group not in latest_run_by_group or ts > latest_run_by_group[group][0]:
                latest_run_by_group[group] = (ts, rk_items)

        for group_key in sorted(latest_run_by_group):
            ts, run_items = latest_run_by_group[group_key]
            prompt, version, test, model, subtest = group_key
            failed = [i for i in run_items if _is_failure(i)]
            n = len(run_items)

            parts = [f"{prompt} v{version}"]
            if test:
                parts.append(test)
            if model:
                parts.append(_short_model(model))
            if subtest:
                parts.append(subtest)
            print(f"\n{_section('  '.join(parts))}")
            print(
                f"  run: {ts[:16].replace('T', ' ')}  |  {len(failed)} / {n} failed\n"
            )

            if not failed:
                print("  All cases passed ✓")
                printed = True
                continue

            # ── Multi-model side-by-side view ─────────────────────────────────
            multi_models = sorted({i.get("model") for i in run_items if i.get("model")})
            if len(multi_models) >= 2:
                # Group items by case_id across models
                by_case: dict[str, dict[str, dict]] = defaultdict(dict)
                for item in run_items:
                    cid = str(item.get("case_id", "?"))
                    mod = item.get("model") or ""
                    by_case[cid][mod] = item

                failed_cases = sorted(
                    cid
                    for cid, model_map in by_case.items()
                    if any(_is_failure(item) for item in model_map.values())
                )

                short_models = [_short_model(m) for m in multi_models]
                id_w = max(len("case_id"), max(len(c) for c in failed_cases))
                col_w = max(9, max(len(s) for s in short_models))
                type_w = len("obj+quality")

                hdr = f"  {'case_id':<{id_w}}  {'type':<{type_w}}"
                for sm in short_models:
                    hdr += f"  {sm:<{col_w}}"
                # Only show judge_reason if any item has one
                has_reason = any(
                    i.get("judge_reason")
                    for items_by_model in by_case.values()
                    for i in items_by_model.values()
                )
                if has_reason:
                    hdr += "  judge_reason"
                print(hdr)
                print("  " + "-" * (len(hdr) - 2))

                for cid in failed_cases:
                    model_map = by_case[cid]
                    # Determine failure type across models
                    all_types = {
                        _fail_type(item)
                        for item in model_map.values()
                        if _is_failure(item)
                    }
                    ftype = "+".join(sorted(all_types)) if all_types else "—"

                    line = f"  {cid:<{id_w}}  {ftype:<{type_w}}"
                    for mod in multi_models:
                        item = model_map.get(mod, {})
                        got_val = item.get("got", "—") if item else "—"
                        status = (
                            "✗"
                            if item and _is_failure(item)
                            else ("✓" if item else "—")
                        )
                        cell = f"{status} {got_val}"
                        line += f"  {cell:<{col_w}}"
                    if has_reason:
                        # Use first non-empty reason
                        reason = next(
                            (
                                item.get("judge_reason", "")
                                for item in model_map.values()
                                if item.get("judge_reason")
                            ),
                            "",
                        )
                        line += f"  {reason}"
                    print(line)
                printed = True

            else:
                # ── Single-model table ────────────────────────────────────────
                has_got = any("got" in i for i in failed)
                has_exp = any("expected" in i for i in failed)
                has_failures_list = any(i.get("failures") for i in failed)
                has_reason = any(i.get("judge_reason") for i in failed)

                id_w = max(
                    len("case_id"), max(len(str(i.get("case_id", "?"))) for i in failed)
                )
                type_w = len("obj+quality")
                hdr = f"  {'case_id':<{id_w}}  {'type':<{type_w}}"
                if has_got:
                    hdr += "  got            "
                if has_exp:
                    hdr += "  expected       "
                if has_failures_list:
                    hdr += "  failures"
                if has_reason:
                    hdr += "  judge_reason"
                print(hdr)
                print("  " + "-" * (len(hdr) - 2))

                for item in sorted(failed, key=lambda i: str(i.get("case_id", ""))):
                    ftype = _fail_type(item)
                    line = (
                        f"  {str(item.get('case_id', '?')):<{id_w}}  {ftype:<{type_w}}"
                    )
                    if has_got:
                        line += f"  {str(item.get('got', '-')):<16}"
                    if has_exp:
                        line += f"  {str(item.get('expected', '-')):<16}"
                    if has_failures_list:
                        failure_strs = item.get("failures") or []
                        line += f"  {'; '.join(str(f) for f in failure_strs)}"
                    if has_reason and not has_failures_list:
                        line += f"  {item.get('judge_reason', '')}"
                    elif has_reason:
                        reason = item.get("judge_reason", "")
                        if reason:
                            line += f"  [{reason}]"
                    print(line)
                printed = True

    # ── Fallback: 'failed' lists embedded in results.jsonl ───────────────────
    if not printed and rows:
        rows_with_failed = [r for r in rows if r.get("failed")]
        if rows_with_failed:
            groups = group_runs(rows_with_failed)
            for key in sorted(groups):
                latest_run = groups[key][-1]
                failed_ids = latest_run.get("failed", [])
                if not failed_ids:
                    continue

                parts = [f"{key.prompt} v{key.version}"]
                if key.test:
                    parts.append(key.test)
                if key.model:
                    parts.append(_short_model(key.model))
                if key.subtest:
                    parts.append(key.subtest)
                print(f"\n{_section('  '.join(parts))}")
                n = latest_run.get("n", "?")
                print(f"  run: {_ts(latest_run)}  |  {len(failed_ids)} / {n} failed")
                print(f"  Failed case IDs: {', '.join(str(i) for i in failed_ids)}")
                print("  (Re-run the eval test with -s to see per-item details)")
                printed = True

    if not printed:
        if not ITEMS_FILE.exists():
            print(f"No {ITEMS_FILE.name} found and no 'failed' lists in results.")
            print()
            print(
                "To get per-item failure details, add record_item calls to your eval tests:"
            )
            print("  # in tests/eval/conftest.py — record_item fixture is available")
            print(
                "  record_item('scorer', {'test': 'scoring_compare', 'case_id': case['id'],"
            )
            print(
                "                         'pass': passed, 'got': got, 'expected': expected})"
            )
        else:
            print("No failures found for the given filters.")

    if items:
        print(f"\n{ITEMS_FILE}")


# ── Entry point ───────────────────────────────────────────────────────────────


def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--prompt", help="Filter by prompt name (e.g. analyzer, scorer)")
    p.add_argument(
        "--test", help="Filter by test name (e.g. grammar_tagging, scoring_compare)"
    )
    p.add_argument("--model", help="Filter by model name")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eval results analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _add_filters(parser)
    sub = parser.add_subparsers(dest="cmd")

    p_history = sub.add_parser(
        "history", help="Full run history with regression warnings"
    )
    _add_filters(p_history)
    p_history.add_argument(
        "--last", type=int, metavar="N", help="Show last N runs per group"
    )

    p_diff = sub.add_parser("diff", help="Version or run delta comparison")
    _add_filters(p_diff)
    p_diff.add_argument(
        "--from", dest="from_ver", metavar="VERSION", help="Compare from this version"
    )
    p_diff.add_argument(
        "--to", dest="to_ver", metavar="VERSION", help="Compare to this version"
    )

    p_models = sub.add_parser("models", help="Model side-by-side comparison")
    _add_filters(p_models)

    p_failures = sub.add_parser("failures", help="Per-item failures")
    _add_filters(p_failures)
    p_failures.add_argument(
        "--latest", action="store_true", help="Show only the most recent run"
    )

    args = parser.parse_args()
    prompt = getattr(args, "prompt", None)
    model = getattr(args, "model", None)
    test = getattr(args, "test", None)
    cmd = args.cmd

    if cmd in (None, "summary"):
        cmd_summary(load_results(prompt=prompt, model=model, test=test))
    elif cmd == "history":
        cmd_history(load_results(prompt=prompt, model=model, test=test), last=args.last)
    elif cmd == "diff":
        cmd_diff(
            load_results(prompt=prompt, model=model, test=test),
            from_ver=args.from_ver,
            to_ver=args.to_ver,
        )
    elif cmd == "models":
        cmd_models(load_results(prompt=prompt, model=model, test=test))
    elif cmd == "failures":
        cmd_failures(
            rows=load_results(prompt=prompt, model=model, test=test),
            items=load_items(prompt=prompt, model=model, test=test),
            latest=args.latest,
        )


if __name__ == "__main__":
    main()
