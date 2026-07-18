"""Seeded-error case construction (plan §11.2).

Takes correct Italian sentences from the pack sources and injects
*known* error types, so ground truth is known by construction and
tagged with the violated grammar point. Output goes to
``evals/cases/_drafts/<task>/`` — the harness never loads drafts; a
human checks each case (is the injection the ONLY error? are the
must_not_claim tags safe?) and moves it into ``evals/cases/<task>/``.

Usage:
    python -m evals.seed_cases --pack packs/it [--limit 20]

Transforms are deliberately few and high-precision; add one whenever a
real review finding suggests a new seedable error class.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

# (name, regex, replacement, violated grammar tag)
TRANSFORMS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "aux_ho_to_sono",
        re.compile(r"\bho (\w+?[aiu]to)\b"),
        r"sono \1",
        "ind_pass_p",
    ),
    (
        "aux_abbiamo_to_siamo",
        re.compile(r"\babbiamo (\w+?[aiu]to)\b"),
        r"siamo \1",
        "ind_pass_p",
    ),
    (
        "piace_to_piacciono_sing",
        re.compile(r"\bmi piace (il|la|lo|l')"),
        r"mi piacciono \1",
        "mi_piace",
    ),
    (
        "vorrei_to_voglio",
        re.compile(r"\b[Vv]orrei\b"),
        "voglio",
        "vorrei",
    ),
    (
        "reflexive_drop_mi",
        re.compile(r"\bmi (alzo|sveglio|chiamo|lavo)\b"),
        r"\1",
        "pron_refl",
    ),
]


def _sentences(pack_dir: Path) -> list[str]:
    """Correct Italian sentences from reviewed pack content."""
    out: list[str] = []

    def add_text(text: str) -> None:
        for s in re.split(r"(?<=[.!?])\s+", text.strip()):
            if len(s.split()) >= 4:
                out.append(s.strip())

    for f in sorted((pack_dir / "readings").glob("*.yaml")):
        for entry in yaml.safe_load(f.read_text()) or []:
            if entry.get("status", "reviewed") == "reviewed":
                add_text(entry.get("text", ""))
    for f in sorted((pack_dir / "listenings").glob("*.yaml")):
        for entry in yaml.safe_load(f.read_text()) or []:
            if entry.get("status", "reviewed") == "reviewed":
                for turn in entry.get("turns", []):
                    add_text(turn["text"])
    for f in sorted((pack_dir / "writing_prompts").glob("*.yaml")):
        for entry in yaml.safe_load(f.read_text()) or []:
            if entry.get("status", "reviewed") == "reviewed" and entry.get(
                "model_answer"
            ):
                add_text(entry["model_answer"])
    return out


def seed_cases(pack_dir: Path, limit: int = 20) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for sentence in _sentences(pack_dir):
        for name, pattern, replacement, tag in TRANSFORMS:
            if len(cases) >= limit:
                return cases
            seeded, n = pattern.subn(replacement, sentence, count=1)
            if n == 0 or seeded == sentence or seeded in seen:
                continue
            seen.add(seeded)
            cases.append(
                {
                    "id": f"wf.gen_{name}.{len(cases) + 1:03d}",
                    "task": "writing_feedback",
                    "seeding_note": (
                        f"HAND-CHECK ME: transform {name} over pack sentence "
                        f"{sentence!r}"
                    ),
                    "input": {
                        "level": "A1",
                        "prompt": "(from pack content — set the real task)",
                        "submission": seeded,
                        "weakness_tags": [tag],
                    },
                    "expect": {
                        "must_identify": [tag],
                        "must_not_claim": [],
                        "must_contain": [],
                    },
                }
            )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(prog="seed_cases")
    parser.add_argument("--pack", type=Path, default=Path("packs/it"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    cases = seed_cases(args.pack, args.limit)
    out_dir = Path("evals/cases/_drafts/writing_feedback")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "generated.yaml"
    header = (
        "# GENERATED case drafts — the harness does NOT load _drafts/.\n"
        "# For each case: verify the injection is the only error, fill\n"
        "# prompt/must_contain/must_not_claim, drop the HAND-CHECK note,\n"
        "# then move it into evals/cases/writing_feedback/.\n"
    )
    out.write_text(
        header + yaml.dump(cases, allow_unicode=True, sort_keys=False, width=88),
        encoding="utf-8",
    )
    print(f"drafted {len(cases)} case(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
