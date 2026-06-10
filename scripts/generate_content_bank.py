"""
Generate static content bank files (drill item pools + scenario texts).

Produces data/<lang>/banks/<level>/drills/<gp_code>.yaml and
data/<lang>/banks/<level>/texts/<scenario>.yaml from the curriculum data
(scenarios, grammar points, communicative functions) via LLM calls, then
runs the verified vocab-annotation pass over generated texts.

Existing files are skipped unless --force is given, so the script can be
re-run incrementally as the curriculum grows.

Annotation requires DB access (the dictionary word index); pass
--skip-annotations to generate content without it (runtime falls back to
the legacy NLP discovery for unannotated content).

Run with:
  uv run python scripts/generate_content_bank.py --lang it --level A1
  uv run python scripts/generate_content_bank.py --lang it --level A1 \\
      --scenarios al-bar presentarsi --skip-annotations
  uv run python scripts/generate_content_bank.py --lang it --level A1 --drills-only
"""

import argparse
import asyncio
import json
import logging

import yaml

from maestro.language import LANGUAGES
from maestro.llm import get_client
from maestro.lessons.bank import (
    BankDrillFile,
    BankScenarioFile,
    bank_dir,
)
from maestro.utils import data_dir, parse_llm_json

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GENERATION_MODEL = "claude-sonnet-4-6"

_DRILL_SYSTEM = """\
You are an experienced {lang_name} teacher writing drill exercises for one
grammar point at {level} level.

Rules:
- fill_blank: prompt is a {lang_name} sentence with ___ as placeholder;
  correct_answer is the word/phrase that fills the blank. Where the blank is
  ambiguous, add a parenthesised cue at the end, e.g. "Io ___ Marco. (essere)".
- error_correction: prompt is a bare erroneous {lang_name} sentence (no intro
  text); correct_answer is the corrected sentence. The error must target the
  grammar point.
- Every item must actually exercise the target grammar point.
- Vary vocabulary and contexts across items; keep all vocabulary at {level}.
- Answers must be unambiguous: exactly one natural correct answer.

Return ONLY a JSON object:
{{"items": [{{"exercise_type": "fill_blank" | "error_correction",
  "prompt": "...", "correct_answer": "..."}}]}}
"""

_TEXTS_SYSTEM = """\
You are an experienced {lang_name} teacher writing reusable lesson material
for a curriculum scenario at {level} level. The material will be served to
many students, so keep it self-contained: no references to a specific
student, day, or previous lesson.

Rules:
- listenings: two-speaker dialogues, each speaker turn on its own line
  prefixed by '— ' (em-dash + space). An optional narrator scene-setter
  sentence may precede the first line. ~{word_count} words. Rendered as
  audio with alternating TTS voices: short natural sentences, clear turns.
- readings: prose or dialogue optimised for visual reading, ~{word_count}
  words.
- Each listening/reading has exactly {question_count} comprehension
  questions in {lang_name} with short unambiguous answers. Tag each question
  with the grammar_point_codes (from the scenario's list) it exercises,
  empty list if none.
- Texts should naturally exercise the scenario's grammar points and
  communicative functions; all vocabulary at {level} level.
- writings: short {lang_name} writing prompts (2-3 sentences) tied to the
  scenario depth.
- speakings: for EACH communicative function listed, 2-3 sentence {lang_name}
  speaking prompts asking the student to practise that function in this
  scenario. Mini-dialogue context lines start with '— '.
- Variants within a list must differ substantially (different angle,
  characters, sub-situation), not be paraphrases.

Return ONLY a JSON object:
{{"depths": {{"<depth_number>": {{
    "listenings": [{{"text": "...", "questions": [{{"text": "...",
      "correct_answer": "...", "grammar_point_codes": ["..."]}}]}}],
    "readings": [ ...same shape... ],
    "writings": [{{"prompt": "..."}}]
  }}}},
  "speakings": [{{"cf_code": "...", "prompt": "..."}}]}}
"""

_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_QUESTION_COUNT = 5


def _load_curriculum(lang: str, level: str):
    with open(data_dir(lang) / f"scenarios_{level.lower()}.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(data_dir(lang) / "grammar_points.yaml") as f:
        gps = {g["code"]: g for g in yaml.safe_load(f)}
    with open(data_dir(lang) / "comm_functions.json") as f:
        cfs = {c["code"]: c for c in json.load(f)}
    return scenarios, gps, cfs


def _llm_json(client, system: str, prompt: str, max_tokens: int = 16000) -> dict:
    response = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    result = parse_llm_json(response.content[0].text)
    if not isinstance(result, dict):
        raise ValueError("LLM did not return a JSON object")
    return result


def generate_gp_drills(
    client, lang_name: str, level: str, gp: dict, scenario_labels: list[str], n: int
) -> BankDrillFile:
    examples = "\n".join(f"  - {e}" for e in gp.get("examples", [])[:5])
    contexts = ", ".join(scenario_labels[:4]) or "everyday situations"
    n_fill = (n * 2) // 3
    n_err = n - n_fill
    prompt = (
        f"Grammar point: {gp['label']} ({gp['code']})\n"
        f"Description: {gp.get('description', '')}\n"
        f"Examples:\n{examples}\n\n"
        f"Curriculum scenarios where this grammar point appears: {contexts}.\n"
        f"Draw drill contexts from these situations where natural.\n\n"
        f"Write {n_fill} fill_blank items and {n_err} error_correction items."
    )
    result = _llm_json(
        client,
        _DRILL_SYSTEM.format(lang_name=lang_name, level=level),
        prompt,
    )
    parsed = BankDrillFile.model_validate(
        {"grammar_point_code": gp["code"], "items": result.get("items", [])}
    )
    bad = [i for i in parsed.items if not i.prompt.strip() or not i.correct_answer.strip()]
    if bad:
        raise ValueError(f"{len(bad)} items with empty prompt/answer")
    return parsed


def generate_scenario_texts(
    client,
    lang_name: str,
    level: str,
    scenario: dict,
    gps: dict,
    cfs: dict,
    variants: int,
) -> BankScenarioFile:
    gp_lines = "\n".join(
        f"  - {code} | {gps[code]['label']}"
        for code in scenario["gp_codes"]
        if code in gps
    )
    cf_lines = "\n".join(
        f"  - {code} | {cfs[code]['label']}"
        for code in scenario["cf_codes"]
        if code in cfs
    )
    depth_lines = "\n".join(
        f"  depth {i + 1}: {d}" for i, d in enumerate(scenario.get("depths", []))
    )
    prompt = (
        f"Scenario: \"{scenario['label']}\" — {scenario['description']}\n"
        f"Depths:\n{depth_lines}\n\n"
        f"Grammar points:\n{gp_lines}\n\n"
        f"Communicative functions:\n{cf_lines}\n\n"
        f"For EACH depth produce {variants} listening variants, {variants} "
        f"reading variants, and {variants} writing prompts matched to that "
        f"depth's focus. Then produce one speaking prompt per communicative "
        f"function (scenario-level, not per depth)."
    )
    result = _llm_json(
        client,
        _TEXTS_SYSTEM.format(
            lang_name=lang_name,
            level=level,
            word_count=_WORD_COUNT.get(level, 200),
            question_count=_QUESTION_COUNT,
        ),
        prompt,
        max_tokens=32000,
    )
    result["scenario"] = scenario["slug"]
    return BankScenarioFile.model_validate(result)


async def annotate_bank_file(scenario_file: BankScenarioFile, lang: str) -> None:
    """Fill vocab_annotations on all texts via the verified annotation pass."""
    from maestro.vocab.annotate import annotate_texts

    targets = []
    texts = []
    for depth in scenario_file.depths.values():
        for t in depth.listenings + depth.readings:
            targets.append(t)
            texts.append(t.text + "\n" + "\n".join(q.text for q in t.questions))
        for w in depth.writings:
            targets.append(w)
            texts.append(w.prompt)
    for s in scenario_file.speakings:
        targets.append(s)
        texts.append(s.prompt)

    annotations = await annotate_texts(texts, language=lang)
    if annotations is None:
        logger.warning("annotation failed for %s — left empty", scenario_file.scenario)
        return
    for target, anns in zip(targets, annotations):
        target.vocab_annotations = anns


def _dump_yaml(model, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(
            model.model_dump(mode="json", exclude_defaults=True),
            f,
            allow_unicode=True,
            sort_keys=False,
            width=88,
        )
    logger.info("wrote %s", path)


async def main_async(args) -> None:
    lang = args.lang
    level = args.level.upper()
    lang_name = LANGUAGES[lang].name
    scenarios, gps, cfs = _load_curriculum(lang, level)

    if args.scenarios:
        scenarios = [s for s in scenarios if s["slug"] in args.scenarios]
    gp_codes: list[str] = args.gps or sorted(
        {c for s in scenarios for c in s["gp_codes"]}
    )

    if not args.skip_annotations:
        from maestro.db import init_db
        from maestro.vocab import cache as vocab_cache

        await init_db()
        await vocab_cache.ensure_loaded(lang)

    client = get_client()
    out_dir = bank_dir(lang, level)

    if not args.texts_only:
        gp_scenarios: dict[str, list[str]] = {}
        for s in scenarios:
            for code in s["gp_codes"]:
                gp_scenarios.setdefault(code, []).append(s["label"])
        for code in gp_codes:
            if code not in gps:
                logger.warning("unknown GP code %s — skipped", code)
                continue
            path = out_dir / "drills" / f"{code}.yaml"
            if path.exists() and not args.force:
                logger.info("exists, skipping: %s", path)
                continue
            logger.info("generating drills for %s", code)
            try:
                drill_file = generate_gp_drills(
                    client,
                    lang_name,
                    level,
                    gps[code],
                    gp_scenarios.get(code, []),
                    args.items_per_gp,
                )
            except Exception:
                logger.exception("drill generation failed for %s", code)
                continue
            _dump_yaml(drill_file, path)

    if not args.drills_only:
        for scenario in scenarios:
            path = out_dir / "texts" / f"{scenario['slug']}.yaml"
            if path.exists() and not args.force:
                logger.info("exists, skipping: %s", path)
                continue
            logger.info("generating texts for %s", scenario["slug"])
            try:
                scenario_file = generate_scenario_texts(
                    client, lang_name, level, scenario, gps, cfs, args.variants
                )
                if not args.skip_annotations:
                    await annotate_bank_file(scenario_file, lang)
            except Exception:
                logger.exception("text generation failed for %s", scenario["slug"])
                continue
            _dump_yaml(scenario_file, path)


def main():
    parser = argparse.ArgumentParser(description="Generate content bank files")
    parser.add_argument("--lang", required=True, choices=sorted(LANGUAGES))
    parser.add_argument("--level", default="A1", help="CEFR level (default: A1)")
    parser.add_argument("--scenarios", nargs="*", help="limit to these scenario slugs")
    parser.add_argument("--gps", nargs="*", help="limit to these GP codes")
    parser.add_argument("--drills-only", action="store_true")
    parser.add_argument("--texts-only", action="store_true")
    parser.add_argument("--items-per-gp", type=int, default=12)
    parser.add_argument("--variants", type=int, default=2)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument(
        "--skip-annotations",
        action="store_true",
        help="skip the vocab annotation pass (no DB needed)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
