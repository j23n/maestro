"""
Re-map grammar points to grammar book chunks using an LLM.

All 124 chunk descriptions (from chunk_enrichment.json) are fed as context to the LLM,
which maps each GP to the best chunk ref — or null if no chunk covers the concept.

This avoids the embedding approach's core flaw: cosine similarity always picks *something*,
so A0 formulaic items (saluti, mi_chiamo, …) end up with spurious chunk_refs.

Results are written directly into grammar_points.json as chunk_ref.

Run:  uv run python scripts/llm_remap_chunks.py [--dry-run] [--batch-size 30]
"""

from __future__ import annotations

import argparse
import json
import logging
import time

logger = logging.getLogger(__name__)

DATA_DIR = "src/maestro/data/it"
_BATCH_SIZE = 30
_MAX_RETRIES = 3


def _build_system_prompt(chunks: dict[str, str]) -> str:
    lines = ["You are mapping Italian grammar points to grammar book chapters."]
    lines.append("")
    lines.append("Available chapters (ref: description):")
    for ref, desc in chunks.items():
        lines.append(f"  {ref}: {desc}")
    lines.append("")
    lines.append(
        "Rules:\n"
        "- Map each GP to the single best chapter ref from the list above.\n"
        "- Output null if the GP is formulaic vocabulary / A0 social phrase "
        "  (greetings, introductions, polite expressions) with no dedicated grammar chapter.\n"
        "- Output null if no chapter meaningfully covers the grammar concept.\n"
        "- Use ONLY refs from the list above — never invent new ones.\n"
        '- Respond with a single JSON object: {"gp_code": "chunk_ref_or_null", ...}. '
        "  No other text."
    )
    return "\n".join(lines)


def _build_user_prompt(batch: list[dict]) -> str:
    lines = ["Map each grammar point to its best chapter ref (or null):"]
    lines.append("")
    for gp in batch:
        label = gp.get("label") or gp.get("unistr_label", "")
        lines.append(f"  {gp['code']}: [{gp['cefr_level']}] [{gp['category']}] {label}")
    return "\n".join(lines)


def _call_llm(system: str, user: str, client) -> dict[str, str | None] | None:
    for attempt in range(_MAX_RETRIES):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if "```" in raw:
                raw = raw.rsplit("```", 1)[0]
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        logger.warning(f"  Attempt {attempt + 1}: bad response — {raw[:120]}")
        time.sleep(1)
    return None


def main(dry_run: bool, batch_size: int) -> None:
    from maestro.llm import get_client

    with open(f"{DATA_DIR}/grammar_points.json") as f:
        gps = json.load(f)

    with open(f"{DATA_DIR}/chunk_enrichment.json") as f:
        enrichment: dict[str, str] = json.load(f)

    chunks = {k: v for k, v in enrichment.items() if not k.startswith("__")}
    valid_refs = set(chunks.keys())

    logger.info(f"GPs: {len(gps)}, chunks: {len(chunks)}")

    system_prompt = _build_system_prompt(chunks)
    client = get_client()

    total_batches = (len(gps) + batch_size - 1) // batch_size
    updated = unchanged = nulled = invalid = 0

    for batch_num, start in enumerate(range(0, len(gps), batch_size), 1):
        batch = gps[start : start + batch_size]
        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} GPs)…")

        user_prompt = _build_user_prompt(batch)
        result = _call_llm(system_prompt, user_prompt, client)

        if result is None:
            logger.error(
                f"  Batch {batch_num} failed after {_MAX_RETRIES} attempts — aborting"
            )
            return

        for gp in batch:
            code = gp["code"]
            if code not in result:
                logger.warning(f"  {code}: missing from LLM response — skipping")
                continue

            new_ref = result[code]

            # Validate ref
            if new_ref is not None and new_ref not in valid_refs:
                logger.warning(f"  {code}: invalid ref '{new_ref}' — setting null")
                new_ref = None
                invalid += 1

            old_ref = gp.get("chunk_ref")
            if new_ref != old_ref:
                change = f"  (was: {old_ref})" if old_ref else ""
                marker = "∅" if new_ref is None else "→"
                logger.info(f"  {code:20s} {marker} {new_ref}{change}")
                gp["chunk_ref"] = new_ref
                if new_ref is None:
                    nulled += 1
                else:
                    updated += 1
            else:
                unchanged += 1

    logger.info(
        f"\nUpdated: {updated}, Nulled: {nulled}, Unchanged: {unchanged}, "
        f"Invalid refs corrected: {invalid}"
    )

    if dry_run:
        logger.info("[DRY RUN] Not writing.")
        return

    with open(f"{DATA_DIR}/grammar_points.json", "w") as f:
        json.dump(gps, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info(f"Written to {DATA_DIR}/grammar_points.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--batch-size",
        type=int,
        default=_BATCH_SIZE,
        help=f"GPs per LLM call (default {_BATCH_SIZE})",
    )
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    main(dry_run=args.dry_run, batch_size=args.batch_size)
