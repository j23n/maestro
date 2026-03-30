"""
Generate short (≤10 char) snake_case English codes for all GrammarPoints and write
them to grammar_points.yaml.

Preserves the current verbose code as `unistr_code` (immutable unique identifier).
The new `code` becomes the short human/LLM-friendly reference used in prompts and DB.

After running this script, run ingest to sync changes to MongoDB, then run migration
0003_short_codes to remap all other collections from unistr_code → code.

Run with:  python -m maestro.grammar.generate_short_codes
"""

from __future__ import annotations

import argparse
import json
import logging
import re

import yaml

from maestro.llm import get_client
from maestro.utils import data_dir


class LiteralStr(str):
    pass


def _lit_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)

logger = logging.getLogger(__name__)

_MAX_CODE_LEN = 10
_BATCH_SIZE = 50  # GPs per LLM call


def _sanitise(code: str) -> str:
    """Ensure code is snake_case, lowercase, alphanumeric+underscore, ≤10 chars."""
    code = code.lower().strip()
    code = re.sub(r"[^a-z0-9_]", "_", code)
    code = re.sub(r"_+", "_", code).strip("_")
    return code[:_MAX_CODE_LEN]


def _deduplicate(codes: list[str], existing: set[str]) -> list[str]:
    """Ensure all codes in the list are unique (within the list and against existing)."""
    seen: set[str] = set(existing)
    result = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            result.append(code)
        else:
            # Try appending a numeric suffix
            for i in range(2, 20):
                candidate = code[: _MAX_CODE_LEN - len(str(i))] + str(i)
                if candidate not in seen:
                    seen.add(candidate)
                    result.append(candidate)
                    break
            else:
                # Fallback: shouldn't happen
                result.append(code)
    return result


def _generate_batch(
    gps: list[dict],
    client,
) -> list[str]:
    """Ask the LLM to generate short codes for a batch of GPs.

    Returns a list of short codes in the same order as gps.
    """
    lines = []
    for i, gp in enumerate(gps, 1):
        lines.append(f"{i}. [{gp['cefr_level']}] {gp['label']}")

    prompt = f"""\
You are generating concise reference codes for Italian grammar points used in language learning software.

For each grammar point below, produce a short English snake_case code that:
- Is ≤10 characters (strict)
- Uses snake_case (underscores, lowercase letters, digits only)
- Captures the grammatical concept in English
- Is unique within this list
- Is recognisable to an LLM as a grammar concept label

Examples of good codes: pres_ind, def_art, pos_adj, fut_simp, cond_pres, subj_pres, part_ci, ne_part, refl_vb, dir_pron

Grammar points:
{chr(10).join(lines)}

Output ONLY a JSON array of {len(gps)} short codes, in the same order, no other text.
Example: ["pres_ind", "def_art", "pos_adj"]"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if "```" in raw:
            raw = raw.rsplit("```", 1)[0]

    try:
        codes = json.loads(raw)
        if isinstance(codes, list) and len(codes) == len(gps):
            return [_sanitise(c) for c in codes]
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning(f"Bad LLM response for batch, raw: {raw[:200]}")
    return []


def generate(lang: str, force: bool = False) -> None:
    yaml_path = data_dir(lang) / "grammar_points.yaml"
    with open(yaml_path) as f:
        items = yaml.safe_load(f)

    # Identify items that need short codes
    todo_indices = []
    for i, item in enumerate(items):
        # Skip if already has a short code (unless --force)
        existing_code = item.get("code", "")
        has_unistr = "unistr_code" in item
        if not force and has_unistr and len(existing_code) <= _MAX_CODE_LEN:
            continue
        todo_indices.append(i)

    if not todo_indices:
        logger.info(
            "All grammar points already have short codes. Use --force to regenerate."
        )
        return

    logger.info(f"Generating short codes for {len(todo_indices)} grammar points")

    # Collect existing short codes to avoid collisions
    existing_short_codes: set[str] = set()
    for i, item in enumerate(items):
        if i not in todo_indices and "unistr_code" in item:
            existing_short_codes.add(item["code"])

    client = get_client()

    # Process in batches
    all_new_codes: list[str] = []
    for batch_start in range(0, len(todo_indices), _BATCH_SIZE):
        batch_idxs = todo_indices[batch_start : batch_start + _BATCH_SIZE]
        batch_gps = [items[i] for i in batch_idxs]
        batch_num = batch_start // _BATCH_SIZE + 1
        total_batches = (len(todo_indices) + _BATCH_SIZE - 1) // _BATCH_SIZE
        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch_gps)} GPs)...")

        raw_codes = _generate_batch(batch_gps, client)
        if not raw_codes:
            logger.error(f"Batch {batch_num} failed — aborting")
            return

        # Deduplicate within this batch and against already-assigned codes
        deduped = _deduplicate(raw_codes, existing_short_codes)
        existing_short_codes.update(deduped)
        all_new_codes.extend(deduped)

    # Write results back to JSON
    for i, (item_idx, new_code) in enumerate(zip(todo_indices, all_new_codes)):
        item = items[item_idx]
        old_code = item["code"]
        if "unistr_code" not in item:
            item["unistr_code"] = old_code
        item["code"] = new_code
        logger.info(f"  {old_code!r:55s} → {new_code!r}")

    # Wrap multiline strings for block-scalar output
    for item in items:
        for key in ("description",):
            if isinstance(item.get(key), str) and "\n" in item[key]:
                item[key] = LiteralStr(item[key])
        for lang, expl in item.get("explanations", {}).items():
            for field in ("explanation", "tip", "why_this_matters"):
                if isinstance(expl.get(field), str) and "\n" in expl[field]:
                    expl[field] = LiteralStr(expl[field])
    with open(yaml_path, "w") as f:
        yaml.dump(items, f, default_flow_style=False, allow_unicode=True, width=200)

    logger.info(
        f"Done. Updated {len(todo_indices)} codes in grammar_points.yaml.\n"
        "Next steps:\n"
        "  1. python -m maestro.sync.ingest\n"
        "  2. Migration 0003_short_codes runs on next app startup"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate short ≤10 char codes for grammar points"
    )
    parser.add_argument(
        "--lang",
        required=True,
        help="Target language ISO code (e.g. it, de)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate codes even for GPs that already have short codes",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    generate(lang=args.lang, force=args.force)
