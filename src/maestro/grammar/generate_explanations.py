"""
Generate CEFR grammar explanations and write them into grammar_points.json.

Each grammar point only gets explanations for its own CEFR level and above:
  A1 rule → A1, A2, B1, B2
  A2 rule → A2, B1, B2
  B1 rule → B1, B2
  B2 rule → B2

Uses the GP's linked GrammarChunk as authoritative source. Produces a
CEFR-adapted explanation per level (A1=English, A2=mixed, B1+=target language).

Idempotent — skips grammar points that already have all required explanations.

After running, execute `python -m maestro.learning.ingest` to sync to MongoDB.

Run with:  python -m maestro.grammar.generate_explanations
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from maestro.db import init_db
from maestro.models import GrammarPoint, GrammarChunk
from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import grammar as _prompts
from maestro.utils import CEFR_ORDER, data_dir, parse_llm_json

logger = logging.getLogger(__name__)

_LEVEL_GUIDANCE_KEYS = {
    "A1": "level_guidance_a1",
    "A2": "level_guidance_a2",
    "B1": "level_guidance_b1",
    "B2": "level_guidance_b2",
}


def _target_levels(gp: GrammarPoint) -> tuple[str, ...]:
    """Return the levels this grammar point needs explanations for.

    A0 GPs are formulaic — their description IS the explanation, so skip them.
    """
    if gp.cefr_level == "A0":
        return ()
    idx = CEFR_ORDER.index(gp.cefr_level) if gp.cefr_level in CEFR_ORDER else 0
    return tuple(CEFR_ORDER[idx:])


def _build_system_prompt(levels: tuple[str, ...]) -> str:
    lang = settings.TARGET_LANGUAGE_NAME
    lang_code = settings.TARGET_LANGUAGE
    guidance = "\n".join(
        f"- {lvl}: {getattr(_prompts, _LEVEL_GUIDANCE_KEYS[lvl]).render(target_language=lang)}"
        for lvl in levels
    )
    return _prompts.explanation_system.render_system(
        target_language=lang,
        target_language_code=lang_code,
        level_guidance=guidance,
    )


def _parse_response(
    raw: str, levels: tuple[str, ...]
) -> dict[str, dict[str, str]] | None:
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


async def _call_api(
    gp: GrammarPoint,
    levels: tuple[str, ...],
    chunk_content: str,
) -> dict[str, dict[str, str]] | None:
    chunk_block = (
        f"\n\nAuthoritative grammar rule from the textbook:\n{chunk_content}\n"
        if chunk_content
        else ""
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
        logger.debug(f"  STOP REASON: {response.stop_reason}, USAGE: {response.usage}")
        logger.debug(f"  RAW RESPONSE:\n{raw}")
        data = _parse_response(raw, levels)
        if data:
            return data
        if response.stop_reason == "max_tokens" and attempt < 2:
            max_tokens = min(max_tokens * 2, 65536)
            logger.warning(
                f"  Truncated response for '{gp.label}', retrying with max_tokens={max_tokens}"
            )
            continue
        logger.warning(f"  Parse error for '{gp.label}': {raw[:300]}")
        return None
    return None


def _has_all_explanations(gp: GrammarPoint) -> bool:
    needed = _target_levels(gp)
    return all(lvl in gp.explanations for lvl in needed)


async def list_codes(level: str | None = None) -> None:
    await init_db()
    query = {"cefr_level": level} if level else {}
    gps = await GrammarPoint.find(query).sort("code").to_list()
    done = 0
    for gp in gps:
        has_all = _has_all_explanations(gp)
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

    json_path = data_dir() / "grammar_points.json"
    with open(json_path) as f:
        json_items = json.load(f)
    # Index JSON items by code for fast lookup
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
            gp.explanations = {}
            await gp.save()
            if gp.code in json_by_code:
                json_by_code[gp.code].pop("explanations", None)
        logger.info(f"Cleared explanations for {len(all_gps)} grammar points")

    todo = [gp for gp in all_gps if not _has_all_explanations(gp)]
    logger.info(f"{len(todo)} grammar points need explanations")

    if test:
        # Pick one from each level for a representative spread
        by_level: dict[str, GrammarPoint] = {}
        for gp in todo:
            if gp.cefr_level not in by_level:
                by_level[gp.cefr_level] = gp
        todo = list(by_level.values())
        logger.info(f"  --test: {[f'{gp.label} ({gp.cefr_level})' for gp in todo]}")

    changed = False
    for i, gp in enumerate(todo, 1):
        levels = _target_levels(gp)
        # Only generate levels not already present
        missing = tuple(lvl for lvl in levels if lvl not in gp.explanations)
        if not missing:
            continue
        logger.info(
            f"[{i}/{len(todo)}] {gp.label} ({gp.cefr_level}) → {', '.join(missing)}"
        )

        # Load chunk content via chunk_ref
        chunk_content = ""
        if gp.chunk_ref:
            chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
            if chunk:
                chunk_content = chunk.content
            else:
                logger.warning(f"  Chunk not found for ref: {gp.chunk_ref}")

        try:
            data = await _call_api(gp, missing, chunk_content)
        except Exception as exc:
            logger.error(f"  API error: {exc}")
            continue
        if not data:
            continue

        # Write to DB (in-memory GP object)
        from maestro.models import GrammarExplanation

        for lvl, texts in data.items():
            if not texts["explanation"].strip():
                logger.warning(f"  Empty {lvl} explanation for '{gp.label}'")
                continue
            gp.explanations[lvl] = GrammarExplanation(
                title=texts.get("title", ""),
                explanation=texts["explanation"],
            )
            logger.info(f"  Saved {lvl} explanation for '{gp.label}'")
        await gp.save()

        # Write to JSON
        json_item = json_by_code.get(gp.code)
        if json_item is not None:
            if "explanations" not in json_item:
                json_item["explanations"] = {}
            for lvl, texts in data.items():
                if texts["explanation"].strip():
                    json_item["explanations"][lvl] = {
                        "title": texts.get("title", ""),
                        "explanation": texts["explanation"],
                    }
            changed = True

    if changed:
        with open(json_path, "w") as f:
            json.dump(json_items, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("Updated grammar_points.json")

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CEFR grammar explanations")
    parser.add_argument(
        "--test", action="store_true", help="One grammar point per CEFR level"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (full prompts and responses)",
    )
    parser.add_argument(
        "--code", type=str, help="Generate for a single grammar point by code"
    )
    parser.add_argument(
        "--level",
        type=str,
        choices=["A1", "A2", "B1", "B2"],
        help="Only process grammar points at this CEFR level",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing explanations before regenerating (respects --code/--level)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all grammar point codes (combine with --level to filter)",
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
