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

_LEVEL_GUIDANCE_KEYS = {
    "A1": "level_guidance_a1",
    "A2": "level_guidance_a2",
    "B1": "level_guidance_b1",
    "B2": "level_guidance_b2",
}

_TITLE_GUIDANCE = {
    "A1": 'Write the title in English. Example: "The present tense", "Using definite articles"',
    "A2": 'Write the title in English. Example: "The present tense", "Reflexive verbs"',
    "B1": 'Write the title in Italian. Example: "Il passato prossimo", "I pronomi riflessivi"',
    "B2": 'Write the title in Italian. Example: "Il congiuntivo presente", "I verbi fraseologici"',
}


def _needs_explanation(gp: GrammarPoint) -> bool:
    """True if this GP still needs its explanation generated."""
    if gp.cefr_level == "A0":
        return False
    return gp.cefr_level not in gp.explanations


def _build_system_prompt(level: str) -> str:
    lang = settings.TARGET_LANGUAGE_NAME
    lang_code = settings.TARGET_LANGUAGE
    title_guidance = _TITLE_GUIDANCE.get(level, "")
    level_guidance = getattr(_prompts, _LEVEL_GUIDANCE_KEYS[level]).render(
        target_language=lang,
        target_language_code=lang_code,
        title_guidance=f"Title: {title_guidance}",
        title_guidance_a1=_TITLE_GUIDANCE["A1"],
        title_guidance_a2=_TITLE_GUIDANCE["A2"],
        title_guidance_b1=_TITLE_GUIDANCE["B1"],
        title_guidance_b2=_TITLE_GUIDANCE["B2"],
    )
    return _prompts.explanation_system.render_system(
        target_language=lang,
        target_language_code=lang_code,
        cefr_level=level,
        title_guidance=title_guidance,
        level_guidance=level_guidance,
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


async def _call_api(gp: GrammarPoint, chunk_content: str) -> dict[str, str] | None:
    system_msg = _build_system_prompt(gp.cefr_level)
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
            continue
        logger.warning(f"  Parse error for '{gp.label}': {raw[:300]}")
        return None
    return None


async def list_codes(level: str | None = None) -> None:
    await init_db()
    query = {"cefr_level": level} if level else {}
    gps = await GrammarPoint.find(query).sort("code").to_list()
    done = sum(1 for gp in gps if not _needs_explanation(gp) and gp.cefr_level != "A0")
    for gp in gps:
        if gp.cefr_level == "A0":
            marker = "-"
        elif not _needs_explanation(gp):
            marker = "✓"
        else:
            marker = " "
        print(f"  [{marker}] {gp.code:30s} {gp.cefr_level}  {gp.label}")
    eligible = sum(1 for gp in gps if gp.cefr_level != "A0")
    print(
        f"\n{len(gps)} grammar points, {done}/{eligible} with explanations (A0 skipped)"
    )


async def generate(
    test: bool = False,
    code: str | None = None,
    level: str | None = None,
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

    logger.info(f"Found {len(all_gps)} grammar points")

    if clear:
        for gp in all_gps:
            if gp.cefr_level == "A0":
                continue
            gp.explanations.pop(gp.cefr_level, None)
            await gp.save()
            if gp.code in json_by_code:
                json_by_code[gp.code].get("explanations", {}).pop(gp.cefr_level, None)
        logger.info("Cleared explanations for eligible GPs")

    todo = [gp for gp in all_gps if _needs_explanation(gp)]
    logger.info(f"{len(todo)} grammar points need explanations")

    if test:
        by_level: dict[str, GrammarPoint] = {}
        for gp in todo:
            if gp.cefr_level not in by_level:
                by_level[gp.cefr_level] = gp
        todo = list(by_level.values())
        logger.info(f"  --test: {[f'{gp.label} ({gp.cefr_level})' for gp in todo]}")

    changed = False
    for i, gp in enumerate(todo, 1):
        logger.info(f"[{i}/{len(todo)}] {gp.label} ({gp.cefr_level})")

        chunk_content = ""
        if gp.chunk_ref:
            chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
            if chunk:
                chunk_content = chunk.content
            else:
                logger.warning(f"  Chunk not found: {gp.chunk_ref}")

        try:
            data = await _call_api(gp, chunk_content)
        except Exception as exc:
            logger.error(f"  API error: {exc}")
            continue
        if not data:
            continue

        gp.explanations[gp.cefr_level] = GrammarExplanation(
            title=data["title"],
            tip=data["tip"],
            explanation=data["explanation"],
        )
        await gp.save()
        logger.info(f"  ✓ {gp.cefr_level}: {data['title']}")

        json_item = json_by_code.get(gp.code)
        if json_item is not None:
            json_item.setdefault("explanations", {})[gp.cefr_level] = {
                "title": data["title"],
                "tip": data["tip"],
                "explanation": data["explanation"],
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
        asyncio.run(list_codes(level=args.level))
    else:
        asyncio.run(
            generate(test=args.test, code=args.code, level=args.level, clear=args.clear)
        )
