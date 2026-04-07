"""
Generate A0 lesson content for a target language using the Italian A0 lessons
as a structural template and Claude API for content generation.

Reads:
  data/it/a0_lessons.yaml        — Italian structural template
  data/<lang>/scenarios_a0.yaml  — scenario definitions
  data/<lang>/grammar_points.yaml — A0 grammar points with explanations
  data/<lang>/comm_functions.json — A0 communicative functions

Writes:
  data/<lang>/a0_lessons.yaml    — generated lesson content

Usage:
  uv run python scripts/data/generate_a0_lessons.py                     # all scenarios
  uv run python scripts/data/generate_a0_lessons.py --scenario a0-01-im-flugzeug
  uv run python scripts/data/generate_a0_lessons.py --dry-run
  uv run python scripts/data/generate_a0_lessons.py --lang de
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"

LANGUAGE_NAMES = {
    "de": "German",
    "it": "Italian",
    "es": "Spanish",
    "fr": "French",
    "pt": "Portuguese",
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert language teacher and curriculum designer. You create \
engaging, accurate A0-level (absolute beginner) lesson content for a \
language learning app. Your output must be valid YAML.

You follow these design principles strictly:
- Never more than 2 grammar cards before a practice activity
- 10-12 activities per lesson
- ~15 new vocabulary items per lesson (max 18)
- Active:passive ratio >= 2:1 (drills, speaking, writing > grammar, reading)
- Every lesson ends with a speaking activity
- Use <span lang="{lang_tag}">...</span> for all target-language text
- Grammar table pronunciation columns use audio file paths: /static/audio/{lang}/phrase_{slug}.wav
- Grammar explanations are in English, aimed at adults with zero background
- Drill items use fill_blank exercise_type with clear prompts
- Reading passages use realistic dialogue with narrative stage directions in *italics*
- Questions on reading/listening should test comprehension, not translation"""

USER_PROMPT = """\
Generate the A0 lesson content for scenario **{scenario_slug}** in \
**{target_language}**.

## Scenario
```yaml
{scenario_yaml}
```

## Grammar Points for this lesson
{gp_section}

## Communicative Functions for this lesson
{cf_section}

## Italian reference lesson (structural template — match activity types, count, and flow)
```yaml
{italian_lesson_yaml}
```

## Instructions

Produce the YAML content for this one scenario key. The output should be \
structured exactly like the Italian reference: a top-level key \
`"{scenario_slug}"` with an `activities` list.

**Critical rules:**
1. Match the Italian lesson's **activity types and ordering** closely \
   (grammar, drill, reading, listening, speaking, vocab_review, etc.)
2. Adapt ALL content for {target_language} — do NOT translate Italian \
   literally; create culturally appropriate {target_language} content
3. Use <span lang="{lang_tag}"> tags for ALL {target_language} text
4. Grammar explanations should reference the GP explanations provided above \
   but be formatted as lesson cards (tables, examples, tips)
5. Drills: 5-8 fill_blank items per drill, testing the grammar point taught
6. Reading: a short dialogue (6-10 lines) set in the scenario's location, \
   with 2-3 comprehension questions
7. Listening: same format as reading (content + questions), with audio_path \
   set to /static/audio/a0_{sequence_num:02d}_{scenario_short}.wav
8. Speaking: a prompt asking the student to say phrases out loud
9. vocab_review: just `- type: vocab_review` (no content needed)
10. The first scenario (sequence 1) must start with an onboarding activity \
    (type: onboarding, profile_field: name)
11. Keep the scene_setting narrative consistent — reference {location_context}
12. Write drill correct_answer values as single words (the word that fills \
    the blank), not full sentences

Output ONLY valid YAML. No markdown fences, no commentary before or after.
Start directly with `"{scenario_slug}":` on the first line."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict | list:
    with open(path) as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def _call_llm(
    client: anthropic.Anthropic,
    system: str,
    user: str,
    max_tokens: int = 16384,
) -> str:
    """Send a single LLM request and return the text response."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _clean_yaml_response(raw: str) -> str:
    """Strip markdown fences and leading/trailing whitespace."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _validate_lesson(slug: str, data: dict) -> list[str]:
    """Basic validation of generated lesson data."""
    warnings = []
    if slug not in data:
        warnings.append(f"Missing top-level key '{slug}'")
        return warnings
    lesson = data[slug]
    activities = lesson.get("activities", [])
    if not activities:
        warnings.append(f"{slug}: no activities found")
        return warnings
    count = len(activities)
    if count < 8:
        warnings.append(f"{slug}: only {count} activities (expected 10-12)")
    elif count > 14:
        warnings.append(f"{slug}: {count} activities (expected 10-12)")
    types = [a.get("type") for a in activities]
    if "grammar" not in types:
        warnings.append(f"{slug}: no grammar activity")
    if "drill" not in types:
        warnings.append(f"{slug}: no drill activity")
    return warnings


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------


def generate_lesson(
    scenario: dict,
    italian_lessons: dict,
    it_scenarios: list[dict],
    gps_by_code: dict,
    cfs_by_code: dict,
    client: anthropic.Anthropic,
    lang: str,
    dry_run: bool = False,
) -> dict | None:
    """Generate lesson content for a single scenario."""
    slug = scenario["slug"]
    target_language = LANGUAGE_NAMES.get(lang, lang)
    lang_tag = lang

    # Find the matching Italian scenario by sequence number
    it_scenario = next(
        (s for s in it_scenarios if s["sequence"] == scenario["sequence"]),
        None,
    )
    italian_slug = it_scenario["slug"] if it_scenario else None
    italian_lesson_yaml = ""
    if italian_slug and italian_slug in italian_lessons:
        italian_lesson_yaml = yaml.dump(
            {italian_slug: italian_lessons[italian_slug]},
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )
    else:
        logger.warning(
            f"No Italian reference lesson for sequence {scenario['sequence']}"
        )
        italian_lesson_yaml = "# No Italian reference available for this sequence"

    # Build GP section
    gp_codes = scenario.get("gp_codes", [])
    gp_parts = []
    for code in gp_codes:
        gp = gps_by_code.get(code)
        if gp:
            gp_parts.append(
                f"### {code}\n"
                f"- Label: {gp.get('label', '')}\n"
                f"- Explanation:\n{gp.get('explanations', {}).get('en', {}).get('explanation', 'N/A')}\n"
            )
        else:
            gp_parts.append(f"### {code}\n(not found in grammar_points.yaml)\n")
    gp_section = "\n".join(gp_parts)

    # Build CF section
    cf_codes = scenario.get("cf_codes", [])
    cf_parts = []
    for code in cf_codes:
        cf = cfs_by_code.get(code)
        if cf:
            cf_parts.append(
                f"- **{code}** ({cf.get('label', '')}): "
                f"{cf.get('description', '')} — "
                f"patterns: {', '.join(cf.get('patterns', []))}"
            )
        else:
            cf_parts.append(f"- **{code}** (not found)")
    cf_section = "\n".join(cf_parts)

    # Determine location context from the scenario's own scene_setting
    location_context = scenario.get("scene_setting", "")

    # Scenario short name for audio path
    scenario_short = slug.replace("a0-", "").replace("-", "_")
    sequence_num = scenario["sequence"]

    scenario_yaml = yaml.dump(scenario, allow_unicode=True, default_flow_style=False)

    system = SYSTEM_PROMPT.format(lang_tag=lang_tag)
    user = USER_PROMPT.format(
        scenario_slug=slug,
        target_language=target_language,
        scenario_yaml=scenario_yaml,
        gp_section=gp_section,
        cf_section=cf_section,
        italian_lesson_yaml=italian_lesson_yaml,
        lang_tag=lang_tag,
        sequence_num=sequence_num,
        scenario_short=scenario_short,
        location_context=location_context,
    )

    if dry_run:
        print(f"\n{'=' * 60}")
        print(f"SCENARIO: {slug}")
        print(f"{'=' * 60}")
        print(f"System prompt length: {len(system)} chars")
        print(f"User prompt length: {len(user)} chars")
        print(f"GP codes: {gp_codes}")
        print(f"CF codes: {cf_codes}")
        print(f"Italian reference: {italian_slug}")
        return None

    logger.info(f"Generating lesson for {slug}...")
    raw = _call_llm(client, system, user, max_tokens=16384)
    cleaned = _clean_yaml_response(raw)

    try:
        data = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML for {slug}: {e}")
        logger.error(f"Raw (first 500 chars): {cleaned[:500]}")
        return None

    if not isinstance(data, dict):
        logger.error(f"Expected dict for {slug}, got {type(data).__name__}")
        return None

    # Validate
    for w in _validate_lesson(slug, data):
        logger.warning(w)

    logger.info(
        f"  Generated {len(data.get(slug, {}).get('activities', []))} activities for {slug}"
    )
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate A0 lesson content for a target language"
    )
    parser.add_argument(
        "--lang",
        default="de",
        help="Target language ISO code (default: de)",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Generate only this scenario slug (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts without calling the API",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: data/<lang>/a0_lessons.yaml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    lang = args.lang
    lang_dir = DATA_ROOT / lang

    # Load data
    scenarios_data = _load_yaml(lang_dir / "scenarios_a0.yaml")
    scenarios = scenarios_data["scenarios"]
    logger.info(f"Loaded {len(scenarios)} scenarios for {lang}")

    gps_list = _load_yaml(lang_dir / "grammar_points.yaml")
    gps_by_code = {gp["code"]: gp for gp in gps_list if gp.get("cefr_level") == "A0"}
    logger.info(f"Loaded {len(gps_by_code)} A0 grammar points")

    cfs_list = _load_json(lang_dir / "comm_functions.json")
    cfs_by_code = {cf["code"]: cf for cf in cfs_list if cf.get("cefr_level") == "A0"}
    logger.info(f"Loaded {len(cfs_by_code)} A0 communicative functions")

    italian_lessons = _load_yaml(DATA_ROOT / "it" / "a0_lessons.yaml")
    logger.info(f"Loaded Italian reference lessons ({len(italian_lessons)} scenarios)")

    it_scenarios = _load_yaml(DATA_ROOT / "it" / "scenarios_a0.yaml")["scenarios"]
    logger.info(f"Loaded {len(it_scenarios)} Italian reference scenarios")

    # Filter scenarios if --scenario specified
    if args.scenario:
        scenarios = [s for s in scenarios if s["slug"] == args.scenario]
        if not scenarios:
            logger.error(f"Scenario '{args.scenario}' not found")
            sys.exit(1)

    # Sort by sequence
    scenarios.sort(key=lambda s: s["sequence"])

    # Create client (unless dry-run)
    client = None
    if not args.dry_run:
        client = anthropic.Anthropic()

    # Generate lessons
    all_lessons = {}
    failed_scenarios: list[str] = []
    output_path = Path(args.output) if args.output else lang_dir / "a0_lessons.yaml"

    # If generating a single scenario and output file exists, load existing
    if args.scenario and output_path.exists():
        try:
            existing = _load_yaml(output_path)
            if isinstance(existing, dict):
                all_lessons = existing
                logger.info(f"Loaded existing lessons from {output_path}")
        except Exception:
            pass

    for scenario in scenarios:
        result = generate_lesson(
            scenario=scenario,
            italian_lessons=italian_lessons,
            it_scenarios=it_scenarios,
            gps_by_code=gps_by_code,
            cfs_by_code=cfs_by_code,
            client=client,
            lang=lang,
            dry_run=args.dry_run,
        )
        if result:
            all_lessons.update(result)
        elif not args.dry_run:
            failed_scenarios.append(scenario["slug"])

    if failed_scenarios:
        logger.error(
            f"{len(failed_scenarios)} scenario(s) failed: "
            + ", ".join(failed_scenarios)
        )

    if args.dry_run:
        logger.info("Dry run complete — no files written")
        return

    if not all_lessons:
        logger.error("No lessons generated")
        sys.exit(1)

    # Write header comment + YAML
    header = f"""\
##############################################################################
# Maestro A0 — Scenario-first {LANGUAGE_NAMES.get(lang, lang)} crash course
# {len(all_lessons)} lessons total
# Designed for ~12-15 min daily sessions over two weeks
#
# Design principles:
#   - Never more than 2 grammar cards before a practice activity
#   - Listening + speaking in every lesson
#   - ~15 new vocab items per lesson (max 18)
#   - Active:passive ratio >= 2:1
#   - 10-12 activities per lesson
#   - Every lesson ends with a review drill of earlier material
#
# Generated by scripts/data/generate_a0_lessons.py
##############################################################################

"""
    yaml_content = yaml.dump(
        all_lessons,
        allow_unicode=True,
        default_flow_style=False,
        width=120,
        sort_keys=False,
    )

    with open(output_path, "w") as f:
        f.write(header)
        f.write(yaml_content)

    logger.info(f"Wrote {len(all_lessons)} lessons to {output_path}")

    # Summary
    total_activities = sum(len(v.get("activities", [])) for v in all_lessons.values())
    logger.info(f"Total activities: {total_activities}")
    for slug in sorted(all_lessons.keys()):
        acts = all_lessons[slug].get("activities", [])
        types = [a.get("type", "?") for a in acts]
        logger.info(f"  {slug}: {len(acts)} activities — {', '.join(types)}")

    if failed_scenarios:
        sys.exit(1)


if __name__ == "__main__":
    main()
