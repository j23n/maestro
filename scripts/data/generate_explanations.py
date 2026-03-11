"""
Generate grammar reference explanations and write them into grammar_points.json.

Each grammar point gets one explanation at its own CEFR level — a complete reference
entry a student consults when they need to understand a rule fully.

A0 GPs are formulaic vocabulary items with no grammar rule to explain; they are skipped.

Uses the GP's linked GrammarChunk as the authoritative source for rules and examples.
Writes to both grammar_points.json and MongoDB.

Idempotent — skips GPs that already have an explanation at their own level.
Use --clear to regenerate from scratch.

Run with:  uv run python scripts/data/generate_explanations.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from maestro.db import init_db
from maestro.models import GrammarPoint, GrammarChunk, GrammarExplanation
from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import grammar as _prompts
from maestro.utils import data_dir, parse_llm_json

logger = logging.getLogger(__name__)

_LANG_GUIDANCE_KEYS = {
    "en": "language_guidance_en",
    "it": "language_guidance_it",
}

_TITLE_GUIDANCE = {
    "en": 'Write the title in English. Example: "The present tense", "Using definite articles"',
    "it": 'Write the title in Italian. Example: "Il passato prossimo", "I pronomi riflessivi"',
}


def _needs_explanation(gp: GrammarPoint, lang: str | None = None) -> bool:
    """True if this GP still needs an explanation generated for the given language (or either)."""
    if gp.cefr_level == "A0":
        return False
    if lang:
        return lang not in gp.explanations
    return "en" not in gp.explanations or "it" not in gp.explanations


def _build_system_prompt(cefr_level: str, lang: str) -> str:
    target_lang = settings.TARGET_LANGUAGE_NAME
    lang_code = settings.TARGET_LANGUAGE
    title_guidance = _TITLE_GUIDANCE[lang]
    language_guidance = getattr(_prompts, _LANG_GUIDANCE_KEYS[lang]).render(
        target_language=target_lang,
        target_language_code=lang_code,
        cefr_level=cefr_level,
        title_guidance=title_guidance,
    )
    return _prompts.explanation_system.render_system(
        target_language=target_lang,
        target_language_code=lang_code,
        cefr_level=cefr_level,
        title_guidance=title_guidance,
        level_guidance=language_guidance,
    )


def _parse_response(raw: str) -> dict[str, str] | None:
    """Parse JSON response into {"title": ..., "tip": ..., "explanation": ...}."""
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        return None
    if not data.get("explanation"):
        return None
    return {
        "title": str(data.get("title", "")).strip(),
        "tip": str(data.get("tip", "")).strip(),
        "explanation": str(data["explanation"]).strip(),
    }


async def _call_api(
    gp: GrammarPoint, chunk_content: str, lang: str
) -> dict[str, str] | None:
    system_msg = _build_system_prompt(gp.cefr_level, lang)
    chunk_block = (
        f"Authoritative textbook excerpt:\n{chunk_content}\n\n" if chunk_content else ""
    )
    user_msg = (
        f"{chunk_block}"
        f"Grammar point: {gp.label} ({gp.cefr_level})\n"
        f"Write the reference entry."
    )
    logger.debug(f"  SYSTEM:\n{system_msg}")
    logger.debug(f"  USER:\n{user_msg}")
    max_tokens = 16384
    for attempt in range(3):
        response = await llm_messages_create(
            model=settings.EXPLANATION_MODEL,
            max_tokens=max_tokens,
            system=system_msg,
            messages=[{"role": "user", "content": user_msg}],
            entity_id=gp.id,
            call_type=CallType.GRAMMAR_EXPLANATION,
        )
        raw = response.content[0].text
        logger.debug(f"  STOP: {response.stop_reason}  USAGE: {response.usage}")
        logger.debug(f"  RESPONSE:\n{raw}")
        data = _parse_response(raw)
        if data:
            return data
        if response.stop_reason == "max_tokens" and attempt < 2:
            max_tokens = min(max_tokens * 2, 65536)
            logger.warning(
                f"  Truncated for '{gp.label}', retrying max_tokens={max_tokens}"
            )
        else:
            logger.warning(
                f"  Parse error (attempt {attempt + 1}/3) for '{gp.label}': {raw[:300]}"
            )
    return None


async def list_codes(level: str | None = None, lang: str | None = None) -> None:
    await init_db()
    query = {"cefr_level": level} if level else {}
    gps = await GrammarPoint.find(query).sort("code").to_list()
    done = sum(
        1 for gp in gps if not _needs_explanation(gp, lang) and gp.cefr_level != "A0"
    )
    for gp in gps:
        if gp.cefr_level == "A0":
            marker = "-"
        elif not _needs_explanation(gp, lang):
            marker = "✓"
        else:
            marker = " "
        langs_done = "/".join(k for k in ("en", "it") if k in gp.explanations)
        print(
            f"  [{marker}] {gp.code:30s} {gp.cefr_level}  [{langs_done or '—':5s}]  {gp.label}"
        )
    eligible = sum(1 for gp in gps if gp.cefr_level != "A0")
    print(
        f"\n{len(gps)} grammar points, {done}/{eligible} with explanations (A0 skipped)"
    )


async def generate(
    test: bool = False,
    code: str | None = None,
    level: str | None = None,
    lang: str | None = None,
    clear: bool = False,
) -> None:
    await init_db()

    json_path = data_dir() / "grammar_points.json"
    with open(json_path) as f:
        json_items = json.load(f)
    json_by_code: dict[str, dict] = {item["code"]: item for item in json_items}

    if code:
        gp = await GrammarPoint.find_one({"code": code})
        if not gp:
            logger.error(f"Grammar point '{code}' not found")
            return
        all_gps = [gp]
    else:
        all_gps = await GrammarPoint.find_all().to_list()

    if level:
        all_gps = [gp for gp in all_gps if gp.cefr_level == level]

    langs_to_generate = [lang] if lang else ["en", "it"]
    logger.info(f"Found {len(all_gps)} grammar points, generating: {langs_to_generate}")

    if clear:
        for gp in all_gps:
            if gp.cefr_level == "A0":
                continue
            for lng in langs_to_generate:
                gp.explanations.pop(lng, None)
                json_by_code.get(gp.code, {}).get("explanations", {}).pop(lng, None)
            await gp.save()
        logger.info(f"Cleared {langs_to_generate} explanations for eligible GPs")

    # Build work list: (gp, lang) pairs that still need generation
    todo: list[tuple[GrammarPoint, str]] = []
    for gp in all_gps:
        for lng in langs_to_generate:
            if _needs_explanation(gp, lng):
                todo.append((gp, lng))
    logger.info(f"{len(todo)} (GP, lang) pairs need explanations")

    if test:
        seen: set[tuple[str, str]] = set()
        pruned = []
        for gp, lng in todo:
            key = (gp.cefr_level, lng)
            if key not in seen:
                seen.add(key)
                pruned.append((gp, lng))
        todo = pruned
        logger.info(f"  --test: {[(gp.label, lng) for gp, lng in todo]}")

    changed = False
    for i, (gp, lng) in enumerate(todo, 1):
        logger.info(f"[{i}/{len(todo)}] {gp.label} ({gp.cefr_level}) [{lng}]")

        chunk_content = ""
        if gp.chunk_ref:
            chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
            if chunk:
                chunk_content = chunk.content
            else:
                logger.warning(f"  Chunk not found: {gp.chunk_ref}")

        try:
            data = await _call_api(gp, chunk_content, lng)
        except Exception as exc:
            logger.error(f"  API error: {exc}")
            continue
        if not data:
            continue

        gp.explanations[lng] = GrammarExplanation(
            title=data["title"],
            tip=data["tip"],
            explanation=data["explanation"],
            language=lng,
        )
        await gp.save()
        logger.info(f"  ✓ [{lng}]: {data['title']}")

        json_item = json_by_code.get(gp.code)
        if json_item is not None:
            json_item.setdefault("explanations", {})[lng] = {
                "title": data["title"],
                "tip": data["tip"],
                "explanation": data["explanation"],
                "language": lng,
            }
            changed = True

    if changed:
        with open(json_path, "w") as f:
            json.dump(json_items, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("Updated grammar_points.json")

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate grammar reference explanations"
    )
    parser.add_argument(
        "--test", action="store_true", help="One GP per CEFR level only"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Log full prompts and responses"
    )
    parser.add_argument("--code", type=str, help="Generate for a single GP by code")
    parser.add_argument(
        "--level",
        type=str,
        choices=["A1", "A2", "B1", "B2"],
        help="Only process GPs at this CEFR level",
    )
    parser.add_argument(
        "--lang",
        type=str,
        choices=["en", "it"],
        help="Only generate explanations in this language (default: both)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing explanations before regenerating",
    )
    parser.add_argument(
        "--list", action="store_true", help="List all GP codes with completion status"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    if args.list:
        asyncio.run(list_codes(level=args.level, lang=args.lang))
    else:
        asyncio.run(
            generate(
                test=args.test,
                code=args.code,
                level=args.level,
                lang=args.lang,
                clear=args.clear,
            )
        )
