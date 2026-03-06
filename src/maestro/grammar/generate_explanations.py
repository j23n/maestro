"""
Generate GrammarPointExplanation documents for all GrammarPoints.

Each grammar point only gets explanations for its own CEFR level and above:
  A1 rule → A1, A2, B1, B2
  A2 rule → A2, B1, B2
  B1 rule → B1, B2
  B2 rule → B2

Uses the GP's linked ItalianChunk as authoritative source. Produces a
CEFR-adapted explanation per level (A1=English, A2=mixed, B1+=Italian).

Idempotent — skips grammar points that already have all required explanations.

Run with:  python -m maestro.grammar.generate_explanations
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from maestro.db import init_db
from maestro.models import GrammarPoint, GrammarPointExplanation, ItalianChunk
from maestro.config import settings
from maestro.llm import get_client
from maestro.prompts import grammar as _prompts
from maestro.utils import CEFR_ORDER, parse_llm_json

logger = logging.getLogger(__name__)

_LEVEL_GUIDANCE_KEYS = {
    "A1": "level_guidance_a1",
    "A2": "level_guidance_a2",
    "B1": "level_guidance_b1",
    "B2": "level_guidance_b2",
}


def _target_levels(gp: GrammarPoint) -> tuple[str, ...]:
    """Return the levels this grammar point needs explanations for."""
    idx = CEFR_ORDER.index(gp.cefr_level) if gp.cefr_level in CEFR_ORDER else 0
    return tuple(CEFR_ORDER[idx:])


def _build_system_prompt(levels: tuple[str, ...]) -> str:
    guidance = "\n".join(
        f"- {lvl}: {getattr(_prompts, _LEVEL_GUIDANCE_KEYS[lvl]).render()}"
        for lvl in levels
    )
    return _prompts.explanations_system.render_system(level_guidance=guidance)


def _parse_response(raw: str, levels: tuple[str, ...]) -> dict[str, dict[str, str]] | None:
    """Parse JSON response into {level: {"title": ..., "explanation": ...}}."""
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        return None
    result = {}
    for level in levels:
        entry = data.get(level)
        if not entry or not entry.get("explanation"):
            return None
        result[level] = {
            "title": entry.get("title", ""),
            "explanation": entry["explanation"],
        }
    return result if len(result) == len(levels) else None


def _call_claude(
    gp: GrammarPoint,
    levels: tuple[str, ...],
    chunk_content: str,
    client,
) -> dict[str, dict[str, str]] | None:
    chunk_block = (
        f"\n\nAuthoritative grammar rule from the textbook:\n{chunk_content}\n"
        if chunk_content else ""
    )
    system_msg = _build_system_prompt(levels)
    levels_str = ", ".join(levels)
    user_msg = (
        f"Grammar point: {gp.label} ({gp.cefr_level})\n"
        f"Description: {gp.description}\n"
        f"Generate explanations for these levels: {levels_str}"
        f"{chunk_block}"
    )
    logger.debug(f"  SYSTEM PROMPT:\n{system_msg}")
    logger.debug(f"  USER MESSAGE:\n{user_msg}")
    response = client.messages.create(
        model=settings.EXPLANATION_MODEL,
        max_tokens=16384,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text
    logger.debug(f"  STOP REASON: {response.stop_reason}, USAGE: {response.usage}")
    logger.debug(f"  RAW RESPONSE:\n{raw}")
    data = _parse_response(raw, levels)
    if not data:
        logger.warning(f"  Parse error for '{gp.label}': {raw[:300]}")
    return data


async def _has_all_explanations(gp: GrammarPoint) -> bool:
    needed = len(_target_levels(gp))
    count = await GrammarPointExplanation.find({"grammar_point.$id": gp.id}).count()
    return count >= needed


async def _save_explanations(gp: GrammarPoint, data: dict[str, dict[str, str]]) -> None:
    for level, texts in data.items():
        explanation = texts["explanation"]
        if not explanation.strip():
            logger.warning(f"  Empty {level} explanation for '{gp.label}'")
            continue
        existing = await GrammarPointExplanation.find_one(
            {"grammar_point.$id": gp.id, "student_level": level}
        )
        if existing:
            continue
        await GrammarPointExplanation(
            grammar_point=gp,
            student_level=level,
            title=texts.get("title", ""),
            explanation=explanation,
        ).insert()
        logger.info(f"  Saved {level} explanation for '{gp.label}'")


async def list_codes(level: str | None = None) -> None:
    await init_db()
    query = {"cefr_level": level} if level else {}
    gps = await GrammarPoint.find(query).sort("code").to_list()
    done = 0
    for gp in gps:
        has_all = await _has_all_explanations(gp)
        if has_all:
            done += 1
        marker = "✓" if has_all else " "
        print(f"  [{marker}] {gp.code:30s} {gp.cefr_level}  {gp.label}")
    print(f"\n{len(gps)} grammar points, {done} with explanations")


async def generate(
    test: bool = False,
    code: str | None = None,
    level: str | None = None,
    clear: bool = False,
) -> None:
    await init_db()

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
        gp_ids = [gp.id for gp in all_gps]
        result = await GrammarPointExplanation.find(
            {"grammar_point.$id": {"$in": gp_ids}}
        ).delete()
        logger.info(f"Cleared {result.deleted_count} existing explanations")

    todo = [gp for gp in all_gps if not await _has_all_explanations(gp)]
    logger.info(f"{len(todo)} grammar points need explanations")

    if test:
        # Pick one from each level for a representative spread
        by_level: dict[str, GrammarPoint] = {}
        for gp in todo:
            if gp.cefr_level not in by_level:
                by_level[gp.cefr_level] = gp
        todo = list(by_level.values())
        logger.info(f"  --test: {[f'{gp.label} ({gp.cefr_level})' for gp in todo]}")

    client = get_client()

    for i, gp in enumerate(todo, 1):
        levels = _target_levels(gp)
        logger.info(f"[{i}/{len(todo)}] {gp.label} ({gp.cefr_level}) → {', '.join(levels)}")

        # Load chunk content via chunk_ref
        chunk_content = ""
        if gp.chunk_ref:
            chunk = await ItalianChunk.find_one({"ref": gp.chunk_ref})
            if chunk:
                chunk_content = chunk.content
            else:
                logger.warning(f"  Chunk not found for ref: {gp.chunk_ref}")

        try:
            data = _call_claude(gp, levels, chunk_content, client)
        except Exception as exc:
            logger.error(f"  Claude API error: {exc}")
            continue
        if data:
            await _save_explanations(gp, data)

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CEFR grammar explanations")
    parser.add_argument("--test", action="store_true", help="One grammar point per CEFR level")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (full prompts and responses)")
    parser.add_argument("--code", type=str, help="Generate for a single grammar point by code")
    parser.add_argument("--level", type=str, choices=["A1", "A2", "B1", "B2"], help="Only process grammar points at this CEFR level")
    parser.add_argument("--clear", action="store_true", help="Delete existing explanations before regenerating (respects --code/--level)")
    parser.add_argument("--list", action="store_true", help="List all grammar point codes (combine with --level to filter)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    if args.list:
        asyncio.run(list_codes(level=args.level))
    else:
        asyncio.run(generate(test=args.test, code=args.code, level=args.level, clear=args.clear))
