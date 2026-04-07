"""Augment grammar points with missing fields via LLM.

Reads grammar_points.yaml, detects which fields are incomplete, calls the LLM
to generate them, and writes back. All augmentable fields are generated in a
single LLM call per GP for consistency.

Fields augmented: subcategory, description, examples, explanations (en + target).
Fields NOT touched: code, label, cefr_level, category, source_note, chunk_ref,
prerequisites, language (those come from source parse or other scripts).

Usage:
  uv run python scripts/data/augment_gp.py --lang it --level A1
  uv run python scripts/data/augment_gp.py --lang de --code present_tense --debug
  uv run python scripts/data/augment_gp.py --lang it --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

import yaml

from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import augment_gp_prompts as _prompts, span_tagging_block as _stb
from maestro.utils import data_dir

from _shared import (
    CEFR_ORDER,
    LANGUAGE_NAMES,
    UsageStats,
    _EXPLANATION_FIELDS,
    compute_sha256,
    parse_response,
    validate_explanation,
    write_gp_yaml,
    write_lock,
)

logger = logging.getLogger(__name__)

# Fields the augment script manages (everything else is left alone)
_AUGMENTABLE_SIMPLE = ("subcategory", "description", "examples")


# ---------------------------------------------------------------------------
# Missing-field detection
# ---------------------------------------------------------------------------


def _missing_fields(
    gp: dict,
    explanation_langs: list[str],
    force: bool = False,
) -> list[str]:
    """Return list of field names that need generation."""
    if force:
        missing = list(_AUGMENTABLE_SIMPLE)
        if gp["cefr_level"] != "A0":
            for lang in explanation_langs:
                missing.append(f"explanations.{lang}")
        return missing

    missing: list[str] = []
    if not gp.get("subcategory"):
        missing.append("subcategory")
    if not gp.get("description"):
        missing.append("description")
    if not gp.get("examples"):
        missing.append("examples")
    if gp["cefr_level"] != "A0":
        for lang in explanation_langs:
            expl = gp.get("explanations", {}).get(lang)
            if not expl:
                missing.append(f"explanations.{lang}")
            elif not expl.get("tip") or not expl.get("why_this_matters"):
                missing.append(f"explanations.{lang}")
    return missing


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_TITLE_GUIDANCE = {
    "en": 'Write the title in English. Example: "The present tense", "Using definite articles"',
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
    # Build explanation guidance for each requested language
    guidance_parts = []
    for lang in explanation_langs:
        if lang == "en":
            tpl = _prompts.explanation_guidance_en
        else:
            tpl = _prompts.explanation_guidance_target
        guidance_parts.append(
            tpl.render(
                target_language=target_lang_name,
                target_language_code=target_lang_code,
                cefr_level=cefr_level,
                title_guidance_en=_title_guidance("en", target_lang_name),
                title_guidance_target=_title_guidance(
                    target_lang_code, target_lang_name
                ),
            )
        )
    explanation_guidance = "\n\n".join(guidance_parts)

    return _prompts.augment_system.render_system(
        target_language=target_lang_name,
        target_language_code=target_lang_code,
        cefr_level=cefr_level,
        explanation_guidance=explanation_guidance,
        span_tagging=_stb(target_lang_name, target_lang_code),
    )


def _build_user_prompt(
    gp: dict,
    missing: list[str],
    context_list: str,
    chunk_content: str,
    force: bool = False,
) -> str:
    chunk_block = (
        f"\nAuthoritative textbook excerpt:\n{chunk_content}\n" if chunk_content else ""
    )

    # Show existing data so LLM can be consistent
    existing = {
        "code": gp["code"],
        "label": gp.get("label", ""),
        "cefr_level": gp["cefr_level"],
        "category": gp.get("category", ""),
        "subcategory": gp.get("subcategory", ""),
        "description": gp.get("description", ""),
        "examples": gp.get("examples", []),
    }
    # Include full existing explanation when it needs regeneration (e.g. missing
    # tip) or when force-regenerating, so the LLM can preserve good content.
    # Otherwise just send the title to keep the prompt lighter.
    for lang, expl in gp.get("explanations", {}).items():
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
        f"Grammar point (existing data):\n{existing_block}\n"
        f"{chunk_block}\n"
        f"Sibling grammar points at {gp['cefr_level']} level:\n{context_list}\n\n"
        f"Generate these fields: {', '.join(missing)}"
        f"{force_instruction}"
    )


# ---------------------------------------------------------------------------
# LLM call + response parsing
# ---------------------------------------------------------------------------


async def _call_llm(
    gp: dict,
    missing: list[str],
    context_list: str,
    chunk_content: str,
    explanation_langs: list[str],
    target_lang_name: str,
    target_lang_code: str,
    force: bool = False,
    stats: UsageStats | None = None,
) -> dict | None:
    system_msg = _build_system_prompt(
        gp["cefr_level"], explanation_langs, target_lang_name, target_lang_code
    )
    user_msg = _build_user_prompt(gp, missing, context_list, chunk_content, force=force)
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
            call_type=CallType.AUGMENT_GP,
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
                "  Truncated for '%s', retrying max_tokens=%d", gp["label"], max_tokens
            )
        else:
            logger.warning(
                "  Parse error for '%s', not retrying: %s",
                gp["label"],
                raw[:300],
            )
            break
    return None


# ---------------------------------------------------------------------------
# Apply augmentation
# ---------------------------------------------------------------------------


def _apply(gp: dict, data: dict, missing: list[str]) -> int:
    """Merge LLM output into gp dict. Only writes fields that were in `missing`.
    Returns number of fields updated."""
    updated = 0

    for field in ("subcategory", "description"):
        if field in missing and field in data and data[field]:
            gp[field] = str(data[field]).strip()
            updated += 1

    if (
        "examples" in missing
        and "examples" in data
        and isinstance(data["examples"], list)
    ):
        gp["examples"] = [str(ex).strip() for ex in data["examples"] if ex]
        updated += 1

    # Explanations
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
            gp.setdefault("explanations", {})[lang] = validated
            updated += 1
            if not validated.get("tip"):
                logger.warning(
                    "%s: LLM returned empty tip for explanations.%s",
                    gp["code"],
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
    gp_yaml = data_dir(target_lang_code) / "grammar_points.yaml"
    with open(gp_yaml) as f:
        items = yaml.safe_load(f)
    if level:
        items = [gp for gp in items if gp["cefr_level"] == level]

    explanation_langs = (
        [explanation_lang] if explanation_lang else ["en", target_lang_code]
    )
    total_fields = len(_AUGMENTABLE_SIMPLE) + len(explanation_langs)

    complete = 0
    for gp in items:
        missing = _missing_fields(gp, explanation_langs)
        filled = total_fields - len(missing)
        # A0 doesn't get explanations
        a0_max = len(_AUGMENTABLE_SIMPLE)
        max_fields = a0_max if gp["cefr_level"] == "A0" else total_fields

        marker = "✓" if not missing else " "
        missing_names = ", ".join(missing) if missing else ""
        suffix = f"  (missing: {missing_names})" if missing else ""
        print(
            f"  [{marker}] {filled}/{max_fields}  "
            f"{gp['code']:30s} {gp['cefr_level']}  {gp.get('label', '')}{suffix}"
        )
        if not missing:
            complete += 1

    print(f"\n{complete}/{len(items)} grammar points fully augmented")


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
    gp_yaml = lang_dir / "grammar_points.yaml"
    chunk_contents_json = lang_dir / "grammar_chunk_contents.json"
    lock_file = lang_dir / "grammar_points.lock"

    with open(gp_yaml) as f:
        all_items = yaml.safe_load(f)

    # Load chunk content for richer context (optional)
    chunk_contents: dict[str, str] = {}
    if chunk_contents_json.exists():
        with open(chunk_contents_json) as f:
            chunk_contents = json.load(f)
        logger.info("Loaded %d grammar chunk contents", len(chunk_contents))

    # Determine explanation languages
    explanation_langs = (
        [explanation_lang] if explanation_lang else ["en", target_lang_code]
    )

    # Filter items
    items = list(all_items)
    if code:
        items = [gp for gp in items if gp["code"] == code]
        if not items:
            logger.error("Grammar point '%s' not found", code)
            return
    if level:
        items = [gp for gp in items if gp["cefr_level"] == level]

    # Build work list
    todo: list[tuple[dict, list[str]]] = []
    for gp in items:
        missing = _missing_fields(gp, explanation_langs, force=force)
        if missing:
            todo.append((gp, missing))

    logger.info(
        "%d/%d %s grammar points need augmentation (langs: %s)",
        len(todo),
        len(items),
        target_lang_name,
        explanation_langs,
    )

    if not todo:
        logger.info("Nothing to do.")
        return

    if test:
        # One per CEFR level
        seen_levels: set[str] = set()
        pruned = []
        for gp, missing in todo:
            if gp["cefr_level"] not in seen_levels:
                seen_levels.add(gp["cefr_level"])
                pruned.append((gp, missing))
        todo = pruned
        logger.info("--test: %d items", len(todo))

    # Pre-build per-level context lists (code + label, lightweight)
    context_by_level: dict[str, str] = {}
    for gp in all_items:
        lvl = gp["cefr_level"]
        if lvl not in context_by_level:
            level_gps = [g for g in all_items if g["cefr_level"] == lvl]
            context_by_level[lvl] = "\n".join(
                f"- {g['code']}: {g.get('label', '')}" for g in level_gps
            )

    stats = UsageStats()
    changed = False
    for i, (gp, missing) in enumerate(todo, 1):
        logger.info(
            "[%d/%d] %s (%s) — missing: %s",
            i,
            len(todo),
            gp.get("label", gp["code"]),
            gp["cefr_level"],
            ", ".join(missing),
        )

        # Only include explanation langs that are actually needed for this GP
        gp_explanation_langs = [
            lang for lang in explanation_langs if f"explanations.{lang}" in missing
        ]

        context = context_by_level.get(gp["cefr_level"], "")
        chunk_content = chunk_contents.get(gp.get("chunk_ref") or "", "")

        try:
            data = await _call_llm(
                gp,
                missing,
                context,
                chunk_content,
                gp_explanation_langs,
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

        n = _apply(gp, data, missing)
        logger.info("  ✓ updated %d fields", n)
        if n:
            changed = True

    if changed:
        write_gp_yaml(gp_yaml, all_items)
        logger.info("Updated %s", gp_yaml)
        _update_lock(all_items, gp_yaml, lock_file)

    stats.log_summary()


def _update_lock(items: list, gp_yaml: Path, lock_file: Path) -> None:
    by_level: dict[str, dict[str, int]] = {}
    for gp in items:
        level = gp.get("cefr_level", "?")
        counts = by_level.setdefault(level, {})
        for lng in gp.get("explanations", {}):
            counts[lng] = counts.get(lng, 0) + 1
    write_lock(
        lock_file,
        {
            "sha256": compute_sha256(gp_yaml),
            "gp_count": len(items),
            "explanations_by_level": by_level,
        },
    )
    logger.info("Updated %s", lock_file)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Augment grammar points with missing fields via LLM"
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
        help="Only process GPs at this CEFR level",
    )
    parser.add_argument("--code", help="Augment a single GP by code")
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
        help="List all GP codes with augmentation status",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="One GP per CEFR level only (for testing)",
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
