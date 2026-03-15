"""
Generate grammar reference explanations and write them into grammar_points.yaml.

Entirely offline — no database connection required.
Reads from grammar_points.yaml and (optionally) grammar_chunk_contents.json.
Writes back to grammar_points.yaml and updates grammar_points.lock.
The next app startup will detect the lock change and sync the DB automatically.

Each grammar point gets two explanations keyed by language:
  "en" — written in English, vocabulary pitched at the GP's CEFR level
  "it" — written in Italian, vocabulary pitched at the GP's CEFR level

A0 GPs are formulaic vocabulary items with no grammar rule to explain; they are skipped.

Chunk content (book excerpts) is used as the authoritative source when
grammar_chunk_contents.json is present. Generate it first with:
  uv run python scripts/export_grammar_chunks.py

Idempotent — skips (GP, language) pairs that already have an explanation.
Use --clear to regenerate from scratch.

Run with:  uv run python scripts/data/generate_explanations.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

import yaml

from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import grammar as _prompts, span_tagging_block as _stb
from maestro.utils import data_dir, parse_llm_json

logger = logging.getLogger(__name__)

GP_YAML = data_dir() / "grammar_points.yaml"
CHUNK_CONTENTS_JSON = data_dir() / "grammar_chunk_contents.json"
LOCK_FILE = data_dir() / "grammar_points.lock"


class LiteralStr(str):
    pass


def _lit_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)


def _write_yaml(path, items: list) -> None:
    """Write grammar points to YAML, using block scalars for multiline strings."""
    for gp in items:
        for key in ("description",):
            if isinstance(gp.get(key), str) and "\n" in gp[key]:
                gp[key] = LiteralStr(gp[key])
        for lang, expl in gp.get("explanations", {}).items():
            for field in ("explanation", "tip", "why_this_matters"):
                if isinstance(expl.get(field), str) and "\n" in expl[field]:
                    expl[field] = LiteralStr(expl[field])
    with open(path, "w") as f:
        yaml.dump(items, f, default_flow_style=False, allow_unicode=True, width=200)


_LANG_GUIDANCE_KEYS = {
    "en": "language_guidance_en",
    "it": "language_guidance_it",
}

_TITLE_GUIDANCE = {
    "en": 'Write the title in English. Example: "The present tense", "Using definite articles"',
    "it": 'Write the title in Italian. Example: "Il passato prossimo", "I pronomi riflessivi"',
}


def _needs_explanation(gp: dict, lang: str | None = None) -> bool:
    """True if this GP still needs an explanation for the given language (or either)."""
    if gp["cefr_level"] == "A0":
        return False
    if lang:
        return lang not in gp.get("explanations", {})
    return "en" not in gp.get("explanations", {}) or "it" not in gp.get(
        "explanations", {}
    )


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
        span_tagging=_stb(target_lang, lang_code),
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
        "why_this_matters": str(data.get("why_this_matters", "")).strip(),
        "explanation": str(data["explanation"]).strip(),
    }


async def _call_api(gp: dict, chunk_content: str, lang: str) -> dict[str, str] | None:
    system_msg = _build_system_prompt(gp["cefr_level"], lang)
    chunk_block = (
        f"Authoritative textbook excerpt:\n{chunk_content}\n\n" if chunk_content else ""
    )
    user_msg = (
        f"{chunk_block}"
        f"Grammar point: {gp['label']} ({gp['cefr_level']})\n"
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
            entity_id=None,
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
                f"  Truncated for '{gp['label']}', retrying max_tokens={max_tokens}"
            )
        else:
            logger.warning(
                f"  Parse error (attempt {attempt + 1}/3) for '{gp['label']}': {raw[:300]}"
            )
    return None


def _update_lock(json_items: list) -> None:
    """Recompute and write grammar_points.lock from the current YAML on disk."""
    content = GP_YAML.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    by_level: dict[str, dict[str, int]] = {}
    for gp in json_items:
        level = gp.get("cefr_level", "?")
        counts = by_level.setdefault(level, {})
        for lng in gp.get("explanations", {}):
            counts[lng] = counts.get(lng, 0) + 1
    lock = {
        "sha256": sha,
        "gp_count": len(json_items),
        "explanations_by_level": by_level,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n")
    summary = "  ".join(
        f"{lvl} en={c.get('en', 0)} it={c.get('it', 0)}"
        for lvl, c in sorted(by_level.items())
    )
    logger.info("Updated grammar_points.lock (gps=%d)  %s", len(json_items), summary)


def list_codes(level: str | None = None, lang: str | None = None) -> None:
    with open(GP_YAML) as f:
        json_items = yaml.safe_load(f)
    if level:
        json_items = [gp for gp in json_items if gp["cefr_level"] == level]
    done = sum(
        1
        for gp in json_items
        if not _needs_explanation(gp, lang) and gp["cefr_level"] != "A0"
    )
    for gp in json_items:
        if gp["cefr_level"] == "A0":
            marker = "-"
        elif not _needs_explanation(gp, lang):
            marker = "✓"
        else:
            marker = " "
        langs_done = "/".join(
            k for k in ("en", "it") if k in gp.get("explanations", {})
        )
        print(
            f"  [{marker}] {gp['code']:30s} {gp['cefr_level']}  "
            f"[{langs_done or '—':5s}]  {gp['label']}"
        )
    eligible = sum(1 for gp in json_items if gp["cefr_level"] != "A0")
    print(
        f"\n{len(json_items)} grammar points, {done}/{eligible} with explanations (A0 skipped)"
    )


async def generate(
    test: bool = False,
    code: str | None = None,
    level: str | None = None,
    lang: str | None = None,
    clear: bool = False,
) -> None:
    with open(GP_YAML) as f:
        json_items = yaml.safe_load(f)

    # Load chunk content for richer context (optional)
    chunk_contents: dict[str, str] = {}
    if CHUNK_CONTENTS_JSON.exists():
        with open(CHUNK_CONTENTS_JSON) as f:
            chunk_contents = json.load(f)
        logger.info("Loaded %d grammar chunk contents", len(chunk_contents))
    else:
        logger.warning(
            "grammar_chunk_contents.json not found — generating without book context. "
            "Run: uv run python scripts/export_grammar_chunks.py"
        )

    if code:
        all_items = [item for item in json_items if item["code"] == code]
        if not all_items:
            logger.error(f"Grammar point '{code}' not found in grammar_points.yaml")
            return
    else:
        all_items = list(json_items)

    if level:
        all_items = [gp for gp in all_items if gp["cefr_level"] == level]

    langs_to_generate = [lang] if lang else ["en", "it"]
    logger.info(
        "Found %d grammar points, generating: %s", len(all_items), langs_to_generate
    )

    if clear:
        for item in all_items:
            if item["cefr_level"] == "A0":
                continue
            for lng in langs_to_generate:
                item.get("explanations", {}).pop(lng, None)
        _write_yaml(GP_YAML, json_items)
        logger.info(
            "Cleared %s explanations from grammar_points.yaml", langs_to_generate
        )

    # Build work list: (gp_dict, lang) pairs that still need generation
    todo: list[tuple[dict, str]] = [
        (item, lng)
        for item in all_items
        for lng in langs_to_generate
        if _needs_explanation(item, lng)
    ]
    logger.info("%d (GP, lang) pairs need explanations", len(todo))

    if test:
        seen: set[tuple[str, str]] = set()
        pruned = []
        for item, lng in todo:
            key = (item["cefr_level"], lng)
            if key not in seen:
                seen.add(key)
                pruned.append((item, lng))
        todo = pruned
        logger.info("  --test: %s", [(item["label"], lng) for item, lng in todo])

    changed = False
    for i, (item, lng) in enumerate(todo, 1):
        logger.info(
            "[%d/%d] %s (%s) [%s]", i, len(todo), item["label"], item["cefr_level"], lng
        )

        chunk_content = chunk_contents.get(item.get("chunk_ref") or "", "")

        try:
            data = await _call_api(item, chunk_content, lng)
        except Exception as exc:
            logger.error(f"  API error: {exc}")
            continue
        if not data:
            continue

        item.setdefault("explanations", {})[lng] = {
            "title": data["title"],
            "tip": data["tip"],
            "why_this_matters": data["why_this_matters"],
            "explanation": data["explanation"],
            "language": lng,
        }
        logger.info("  ✓ [%s]: %s", lng, data["title"])
        changed = True

    if changed:
        _write_yaml(GP_YAML, json_items)
        logger.info("Updated grammar_points.yaml")
        _update_lock(json_items)

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate grammar reference explanations (offline, no DB required)"
    )
    parser.add_argument(
        "--test", action="store_true", help="One GP per (CEFR level, language) only"
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
        list_codes(level=args.level, lang=args.lang)
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
