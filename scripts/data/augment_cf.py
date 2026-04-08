"""Augment communicative functions with missing fields via LLM.

Reads comm_functions.json, detects which fields are incomplete, calls the LLM
to generate them, and writes back. All augmentable fields are generated in a
single LLM call per CF for consistency.

Fields augmented: description, examples, explanations (en + target).
Fields NOT touched: code, label, category, cefr_level, patterns,
source_url, language (those come from source parse).

Usage:
  uv run python scripts/data/augment_cf.py --lang it --level A1
  uv run python scripts/data/augment_cf.py --lang de --code a0_begruessen --debug
  uv run python scripts/data/augment_cf.py --lang it --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import (
    augment_cf_prompts as _prompts,
    span_tagging_block as _stb,
    json_output_block as _job,
    language_guidance_block as _lgb,
)
from maestro.utils import data_dir

from _shared import (
    CEFR_ORDER,
    LANGUAGE_NAMES,
    UsageStats,
    _EXPLANATION_FIELDS,
    compute_sha256,
    parse_response,
    validate_explanation,
    write_cf_json,
    write_lock,
)

logger = logging.getLogger(__name__)

_AUGMENTABLE_SIMPLE = ("description", "examples")


# ---------------------------------------------------------------------------
# Missing-field detection
# ---------------------------------------------------------------------------


def _is_auto_description(cf: dict) -> bool:
    """True if description looks auto-generated from patterns (or is the label)."""
    desc = cf.get("description", "")
    if not desc:
        return True
    patterns = cf.get("patterns", [])
    if desc == cf.get("label", ""):
        return True
    if patterns and desc == "; ".join(patterns[:3]):
        return True
    return False


def _missing_fields(
    cf: dict,
    explanation_langs: list[str],
    force: bool = False,
) -> list[str]:
    """Return list of field names that need generation."""
    if force:
        missing = list(_AUGMENTABLE_SIMPLE)
        if cf["cefr_level"] != "A0":
            for lang in explanation_langs:
                missing.append(f"explanations.{lang}")
        return missing

    missing: list[str] = []
    if _is_auto_description(cf):
        missing.append("description")
    if not cf.get("examples"):
        missing.append("examples")
    if cf["cefr_level"] != "A0":
        for lang in explanation_langs:
            expl = cf.get("explanations", {}).get(lang)
            if not expl:
                missing.append(f"explanations.{lang}")
            elif not expl.get("tip") or not expl.get("why_this_matters"):
                missing.append(f"explanations.{lang}")
    return missing


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_TITLE_GUIDANCE = {
    "en": 'Write the title in English. Example: "Greeting someone", "Making a request"',
}


def _title_guidance(lang: str, target_lang_name: str) -> str:
    if lang == "en":
        return _TITLE_GUIDANCE["en"]
    return f"Write the title in {target_lang_name}."


def _build_system_prompt(
    cefr_level: str,
    explanation_langs: list[str],
    target_lang_name: str,
    target_lang_code: str,
) -> str:
    guidance_parts = []
    for lang in explanation_langs:
        base = _lgb(lang, target_lang_name, target_lang_code, cefr_level)
        title = _title_guidance(lang, target_lang_name)
        label = "en" if lang == "en" else target_lang_code
        guidance_parts.append(f'For the "{label}" explanation:\n{base}{title}')
    explanation_guidance = "\n\n".join(guidance_parts)

    return _prompts.augment_system.render_system(
        target_language=target_lang_name,
        target_language_code=target_lang_code,
        cefr_level=cefr_level,
        explanation_guidance=explanation_guidance,
        span_tagging=_stb(target_lang_name, target_lang_code),
        json_output=_job(),
    )


def _build_user_prompt(
    cf: dict,
    missing: list[str],
    context_list: str,
    force: bool = False,
) -> str:
    existing = {
        "code": cf["code"],
        "label": cf.get("label", ""),
        "cefr_level": cf["cefr_level"],
        "category": cf.get("category", ""),
        "patterns": cf.get("patterns", []),
        "description": cf.get("description", ""),
        "examples": cf.get("examples", []),
    }
    # Include full existing explanation when it needs regeneration (e.g. missing
    # tip) or when force-regenerating, so the LLM can preserve good content.
    # Otherwise just send the title to keep the prompt lighter.
    for lang, expl in cf.get("explanations", {}).items():
        expl_key = f"explanations.{lang}"
        if force or expl_key in missing:
            existing[expl_key] = {k: expl.get(k, "") for k in _EXPLANATION_FIELDS}
        else:
            existing[f"{expl_key}.title"] = expl.get("title", "")

    existing_block = json.dumps(existing, ensure_ascii=False, indent=2)

    force_instruction = ""
    if force:
        force_instruction = (
            "\n\nIMPORTANT — regeneration mode: existing values are shown above. "
            "You MUST return every requested field, but preserve the existing "
            "wording when it is already accurate, complete, and well-written. "
            "Only change text that is factually wrong, incomplete, poorly "
            "structured, or missing required elements (e.g. too few examples, "
            "missing paradigm table). Do NOT rephrase for style alone."
        )

    return (
        f"Communicative function (existing data):\n{existing_block}\n\n"
        f"Sibling communicative functions at {cf['cefr_level']} level:\n{context_list}\n\n"
        f"Generate these fields: {', '.join(missing)}"
        f"{force_instruction}"
    )


# ---------------------------------------------------------------------------
# LLM call + response parsing
# ---------------------------------------------------------------------------


async def _call_llm(
    cf: dict,
    missing: list[str],
    context_list: str,
    explanation_langs: list[str],
    target_lang_name: str,
    target_lang_code: str,
    force: bool = False,
    stats: UsageStats | None = None,
) -> dict | None:
    system_msg = _build_system_prompt(
        cf["cefr_level"], explanation_langs, target_lang_name, target_lang_code
    )
    user_msg = _build_user_prompt(cf, missing, context_list, force=force)
    logger.debug("  SYSTEM:\n%s", system_msg)
    logger.debug("  USER:\n%s", user_msg)

    max_tokens = 16384
    for attempt in range(3):
        response = await llm_messages_create(
            model=settings.EXPLANATION_MODEL,
            max_tokens=max_tokens,
            system=system_msg,
            messages=[{"role": "user", "content": user_msg}],
            entity_id=None,
            call_type=CallType.AUGMENT_CF,
        )
        cost = stats.record(response) if stats else 0.0
        logger.info(
            "  tokens: %d in + %d out = $%.4f",
            response.usage.input_tokens,
            response.usage.output_tokens,
            cost,
        )
        raw = response.content[0].text
        logger.debug("  STOP: %s  USAGE: %s", response.stop_reason, response.usage)
        logger.debug("  RESPONSE:\n%s", raw)
        data = parse_response(raw)
        if data:
            return data
        if response.stop_reason == "max_tokens" and attempt < 2:
            max_tokens = min(max_tokens * 2, 65536)
            logger.warning(
                "  Truncated for '%s', retrying max_tokens=%d", cf["label"], max_tokens
            )
        else:
            logger.warning(
                "  Parse error for '%s', not retrying: %s",
                cf["label"],
                raw[:300],
            )
            break
    return None


# ---------------------------------------------------------------------------
# Apply augmentation
# ---------------------------------------------------------------------------


def _apply(cf: dict, data: dict, missing: list[str]) -> int:
    updated = 0

    if "description" in missing and "description" in data and data["description"]:
        cf["description"] = str(data["description"]).strip()
        updated += 1

    if (
        "examples" in missing
        and "examples" in data
        and isinstance(data["examples"], list)
    ):
        cf["examples"] = [str(ex).strip() for ex in data["examples"] if ex]
        updated += 1

    explanations_data = data.get("explanations", {})
    for key in list(missing):
        if not key.startswith("explanations."):
            continue
        lang = key.split(".", 1)[1]
        expl_raw = explanations_data.get(lang)
        if not expl_raw:
            continue
        validated = validate_explanation(expl_raw, lang)
        if validated:
            cf.setdefault("explanations", {})[lang] = validated
            updated += 1
            if not validated.get("tip"):
                logger.warning(
                    "%s: LLM returned empty tip for explanations.%s",
                    cf["code"],
                    lang,
                )

    return updated


# ---------------------------------------------------------------------------
# List status
# ---------------------------------------------------------------------------


def list_status(
    target_lang_code: str,
    level: str | None = None,
    explanation_lang: str | None = None,
) -> None:
    cf_json_path = data_dir(target_lang_code) / "comm_functions.json"
    with open(cf_json_path) as f:
        items = json.load(f)
    if level:
        items = [cf for cf in items if cf.get("cefr_level") == level]

    explanation_langs = (
        [explanation_lang] if explanation_lang else ["en", target_lang_code]
    )

    complete = 0
    for cf in items:
        missing = _missing_fields(cf, explanation_langs)

        marker = "✓" if not missing else " "
        missing_names = ", ".join(missing) if missing else ""
        suffix = f"  (missing: {missing_names})" if missing else ""
        print(
            f"  [{marker}] {cf['code']:35s} {cf['cefr_level']}  "
            f"{cf.get('label', '')}{suffix}"
        )
        if not missing:
            complete += 1

    print(f"\n{complete}/{len(items)} communicative functions fully augmented")


# ---------------------------------------------------------------------------
# Main generation loop
# ---------------------------------------------------------------------------


async def generate(
    target_lang_code: str,
    level: str | None = None,
    code: str | None = None,
    explanation_lang: str | None = None,
    force: bool = False,
    test: bool = False,
    debug: bool = False,
) -> None:
    target_lang_name = LANGUAGE_NAMES[target_lang_code]
    lang_dir = data_dir(target_lang_code)
    cf_json_path = lang_dir / "comm_functions.json"
    lock_file = lang_dir / "comm_functions.lock"

    with open(cf_json_path) as f:
        all_items = json.load(f)

    explanation_langs = (
        [explanation_lang] if explanation_lang else ["en", target_lang_code]
    )

    items = list(all_items)
    if code:
        items = [cf for cf in items if cf["code"] == code]
        if not items:
            logger.error("Communicative function '%s' not found", code)
            return
    if level:
        items = [cf for cf in items if cf["cefr_level"] == level]

    # Build work list
    todo: list[tuple[dict, list[str]]] = []
    for cf in items:
        missing = _missing_fields(cf, explanation_langs, force=force)
        if missing:
            todo.append((cf, missing))

    logger.info(
        "%d/%d %s communicative functions need augmentation (langs: %s)",
        len(todo),
        len(items),
        target_lang_name,
        explanation_langs,
    )

    if not todo:
        logger.info("Nothing to do.")
        return

    if test:
        seen_levels: set[str] = set()
        pruned = []
        for cf, missing in todo:
            if cf["cefr_level"] not in seen_levels:
                seen_levels.add(cf["cefr_level"])
                pruned.append((cf, missing))
        todo = pruned
        logger.info("--test: %d items", len(todo))

    # Pre-build per-level context lists
    context_by_level: dict[str, str] = {}
    for cf in all_items:
        lvl = cf["cefr_level"]
        if lvl not in context_by_level:
            level_cfs = [c for c in all_items if c["cefr_level"] == lvl]
            context_by_level[lvl] = "\n".join(
                f"- {c['code']}: {c.get('label', '')}" for c in level_cfs
            )

    stats = UsageStats()
    changed = False
    for i, (cf, missing) in enumerate(todo, 1):
        logger.info(
            "[%d/%d] %s (%s) — missing: %s",
            i,
            len(todo),
            cf.get("label", cf["code"]),
            cf["cefr_level"],
            ", ".join(missing),
        )

        cf_explanation_langs = [
            lang for lang in explanation_langs if f"explanations.{lang}" in missing
        ]

        context = context_by_level.get(cf["cefr_level"], "")

        try:
            data = await _call_llm(
                cf,
                missing,
                context,
                cf_explanation_langs,
                target_lang_name,
                target_lang_code,
                force=force,
                stats=stats,
            )
        except Exception as exc:
            logger.error("  API error: %s", exc)
            continue

        if not data:
            logger.warning("  No usable response, skipping")
            continue

        n = _apply(cf, data, missing)
        logger.info("  ✓ updated %d fields", n)
        if n:
            changed = True

    if changed:
        write_cf_json(cf_json_path, all_items)
        logger.info("Updated %s", cf_json_path)
        _update_lock(all_items, cf_json_path, lock_file)

    stats.log_summary()


def _update_lock(items: list, cf_json_path: Path, lock_file: Path) -> None:
    by_level: dict[str, int] = {}
    explanations_by_level: dict[str, dict[str, int]] = {}
    for cf in items:
        level = cf.get("cefr_level", "?")
        by_level[level] = by_level.get(level, 0) + 1
        counts = explanations_by_level.setdefault(level, {})
        for lng in cf.get("explanations", {}):
            counts[lng] = counts.get(lng, 0) + 1
    write_lock(
        lock_file,
        {
            "sha256": compute_sha256(cf_json_path),
            "cf_count": len(items),
            "by_cefr_level": dict(sorted(by_level.items())),
            "explanations_by_level": explanations_by_level,
        },
    )
    logger.info("Updated %s", lock_file)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Augment communicative functions with missing fields via LLM"
    )
    parser.add_argument(
        "--lang",
        required=True,
        choices=sorted(LANGUAGE_NAMES),
        help="Target language ISO code (e.g. it, de)",
    )
    parser.add_argument(
        "--level",
        choices=CEFR_ORDER,
        help="Only process CFs at this CEFR level",
    )
    parser.add_argument("--code", help="Augment a single CF by code")
    parser.add_argument(
        "--explanation-lang",
        help="Only generate explanations in this language (en or target lang code)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all augmentable fields (overwrite existing)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all CF codes with augmentation status",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="One CF per CEFR level only (for testing)",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.explanation_lang and args.explanation_lang not in ("en", args.lang):
        parser.error(
            f"--explanation-lang must be 'en' or '{args.lang}' (the target language)"
        )

    return args


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.list:
        list_status(
            target_lang_code=args.lang,
            level=args.level,
            explanation_lang=args.explanation_lang,
        )
    else:
        asyncio.run(
            generate(
                target_lang_code=args.lang,
                level=args.level,
                code=args.code,
                explanation_lang=args.explanation_lang,
                force=args.force,
                test=args.test,
                debug=args.debug,
            )
        )


if __name__ == "__main__":
    main()
