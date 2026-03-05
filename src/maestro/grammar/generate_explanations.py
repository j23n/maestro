"""
Generate GrammarPointExplanation documents for all GrammarPoints.

Each grammar point only gets explanations for its own CEFR level and above:
  A1 rule → A1, A2, B1, B2
  A2 rule → A2, B1, B2
  B1 rule → B1, B2
  B2 rule → B2

Idempotent — skips grammar points that already have all required explanations.

Run with:  python -m maestro.grammar.generate_explanations
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re

import anthropic

from maestro.db import init_db
from maestro.models import GrammarPoint, GrammarPointExplanation
from maestro.rag.retrieve import get_chunks_for_refs
from maestro.settings import Settings
from maestro.prompts import grammar as _prompts
from maestro.utils import CEFR_ORDER

logger = logging.getLogger(__name__)
settings = Settings()

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
    delimiters = "\n".join(f"==={lvl}===\n(explanation here)" for lvl in levels)
    return _prompts.explanations_system.render_system(
        level_guidance=guidance,
        delimiters=delimiters,
    )


def _parse_response(raw: str, levels: tuple[str, ...]) -> dict[str, str] | None:
    raw = raw.strip()
    pattern = re.compile(
        r"===(" + "|".join(levels) + r")===(.*?)(?====(?:" + "|".join(levels) + r")==|$)",
        re.DOTALL,
    )
    result = {}
    for m in pattern.finditer(raw):
        level, text = m.group(1), m.group(2).strip()
        if text:
            result[level] = text
    return result if len(result) == len(levels) else None


def _call_claude(
    gp: GrammarPoint,
    levels: tuple[str, ...],
    rag_content: str,
    client: anthropic.Anthropic,
) -> dict[str, str] | None:
    rule_block = (
        f"\n\nReference material from the grammar guide:\n{rag_content}\n"
        if rag_content else ""
    )
    user_msg = (
        f"Grammar point: {gp.label} ({gp.cefr_level})\n"
        f"Description: {gp.description}"
        f"{rule_block}"
    )
    response = client.messages.create(
        model=settings.CHAT_MODEL,
        max_tokens=4096,
        system=_build_system_prompt(levels),
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text
    data = _parse_response(raw, levels)
    if not data:
        logger.warning(f"  Parse error for '{gp.label}': {raw[:300]}")
    return data


async def _has_all_explanations(gp: GrammarPoint) -> bool:
    needed = len(_target_levels(gp))
    count = await GrammarPointExplanation.find({"grammar_point.$id": gp.id}).count()
    return count >= needed


async def _save_explanations(gp: GrammarPoint, data: dict[str, str]) -> None:
    for level, text in data.items():
        if not text.strip():
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
            explanation=text,
        ).insert()
        logger.info(f"  Saved {level} explanation for '{gp.label}'")


async def generate(test: bool = False) -> None:
    await init_db()

    all_gps = await GrammarPoint.find_all().to_list()
    logger.info(f"Found {len(all_gps)} grammar points")

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

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    for i, gp in enumerate(todo, 1):
        levels = _target_levels(gp)
        logger.info(f"[{i}/{len(todo)}] {gp.label} ({gp.cefr_level}) → {', '.join(levels)}")
        chunks = await get_chunks_for_refs(gp.rag_refs)
        rag_content = "\n\n---\n\n".join(c.content for c in chunks)
        try:
            data = _call_claude(gp, levels, rag_content, client)
        except Exception as exc:
            logger.error(f"  Claude API error: {exc}")
            continue
        if data:
            await _save_explanations(gp, data)

    logger.info("Done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate CEFR grammar explanations")
    parser.add_argument("--test", action="store_true", help="One grammar point per CEFR level")
    args = parser.parse_args()
    asyncio.run(generate(test=args.test))
