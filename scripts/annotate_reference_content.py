"""
One-off: annotate grammar point and communicative function reference content
with verified vocab mappings so reference-page popovers work.

Since the runtime NLP discovery pipeline was removed, popovers only appear
on content with stored VocabAnnotations. Lesson content gets them at
generation time; GP/CF reference content (examples, explanations, patterns)
is static, so it is annotated once here:

  1. For each GP/CF, the target-language text (examples, patterns, and all
     explanation fields) is sent through the same LLM lemma pass used
     everywhere else (vocab.annotate.annotate_texts), validated against the
     dictionary word index — unknown lemmas are dropped, never guessed.
  2. The merged annotations are written into grammar_points.yaml /
     comm_functions.json (source of truth), the lock files are refreshed so
     the next app startup syncs the DB, AND the live DB documents are
     updated directly so no restart is needed.

Entries that already have annotations are skipped unless --force is given,
so the script is safe to re-run incrementally.

Requires DB access (dictionary word index) and ANTHROPIC_API_KEY.

Run with:
  uv run python scripts/annotate_reference_content.py --lang it
  uv run python scripts/annotate_reference_content.py --lang it --level A1
  uv run python scripts/annotate_reference_content.py --lang it --cfs-only --force
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "data"))

from _shared import write_cf_json, write_gp_yaml  # noqa: E402

from maestro.db import init_db  # noqa: E402
from maestro.language import LANGUAGES  # noqa: E402
from maestro.models import CommunicativeFunction, GrammarPoint  # noqa: E402
from maestro.utils import data_dir  # noqa: E402
from maestro.vocab import cache as vocab_cache  # noqa: E402
from maestro.vocab.annotate import annotate_texts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 8  # entries per annotation LLM call


def _gp_text(item: dict) -> str:
    """Collect all renderable target-language text for a grammar point."""
    parts = list(item.get("examples") or [])
    for expl in (item.get("explanations") or {}).values():
        for field in ("title", "tip", "explanation", "why_this_matters"):
            if expl.get(field):
                parts.append(expl[field])
    return "\n".join(parts)


def _cf_text(item: dict) -> str:
    """Collect all renderable target-language text for a communicative function."""
    parts = list(item.get("patterns") or []) + list(item.get("examples") or [])
    for expl in (item.get("explanations") or {}).values():
        for field in ("title", "tip", "explanation", "why_this_matters"):
            if expl.get(field):
                parts.append(expl[field])
    return "\n".join(parts)


async def _annotate_entries(
    entries: list[dict],
    text_fn,
    *,
    lang: str,
    force: bool,
    level: str | None,
    limit: int | None,
) -> int:
    """Fill entry["vocab_annotations"] in place. Returns # entries annotated."""
    todo: list[dict] = []
    for item in entries:
        if level and item.get("cefr_level") != level:
            continue
        if item.get("vocab_annotations") and not force:
            continue
        if not text_fn(item).strip():
            continue
        todo.append(item)
        if limit and len(todo) >= limit:
            break

    logger.info("%d entries to annotate", len(todo))
    annotated = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        texts = [text_fn(item) for item in batch]
        results = await annotate_texts(texts, language=lang)
        if results is None:
            logger.warning(
                "annotation batch failed (%s..) — skipping batch",
                batch[0].get("code"),
            )
            continue
        for item, anns in zip(batch, results):
            item["vocab_annotations"] = [ann.model_dump(mode="json") for ann in anns]
            annotated += 1
            logger.info("  %-40s %d mappings", item.get("code"), len(anns))
    return annotated


async def _update_db(entries: list[dict], document_cls, lang: str) -> int:
    """Write annotations to live DB docs so no restart is needed."""
    coll = document_cls.get_pymongo_collection()
    updated = 0
    for item in entries:
        if "vocab_annotations" not in item:
            continue
        result = await coll.update_one(
            {"code": item["code"], "language": lang},
            {"$set": {"vocab_annotations": item["vocab_annotations"]}},
        )
        updated += result.modified_count
    return updated


def _update_lock(script: str, lang: str) -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), "--language", lang],
        check=True,
    )


async def main_async(args) -> None:
    lang = args.lang
    await init_db()
    await vocab_cache.ensure_loaded(lang)
    if not vocab_cache.word_index(lang):
        logger.error("word index empty for %s — is the dictionary ingested?", lang)
        sys.exit(1)

    if not args.cfs_only:
        gp_path = data_dir(lang) / "grammar_points.yaml"
        with open(gp_path) as f:
            gps = yaml.safe_load(f)
        n = await _annotate_entries(
            gps,
            _gp_text,
            lang=lang,
            force=args.force,
            level=args.level,
            limit=args.limit,
        )
        if n:
            write_gp_yaml(gp_path, gps)
            logger.info("wrote %s (%d entries annotated)", gp_path, n)
            _update_lock("update_gp_lock.py", lang)
            db_n = await _update_db(gps, GrammarPoint, lang)
            logger.info("updated %d GrammarPoint docs in DB", db_n)

    if not args.gps_only:
        cf_path = data_dir(lang) / "comm_functions.json"
        with open(cf_path) as f:
            cfs = json.load(f)
        n = await _annotate_entries(
            cfs,
            _cf_text,
            lang=lang,
            force=args.force,
            level=args.level,
            limit=args.limit,
        )
        if n:
            write_cf_json(cf_path, cfs)
            logger.info("wrote %s (%d entries annotated)", cf_path, n)
            _update_lock("update_cf_lock.py", lang)
            db_n = await _update_db(cfs, CommunicativeFunction, lang)
            logger.info("updated %d CommunicativeFunction docs in DB", db_n)


def main():
    parser = argparse.ArgumentParser(
        description="Annotate GP/CF reference content with verified vocab mappings"
    )
    parser.add_argument("--lang", required=True, choices=sorted(LANGUAGES))
    parser.add_argument("--level", help="only entries at this CEFR level (e.g. A1)")
    parser.add_argument("--gps-only", action="store_true")
    parser.add_argument("--cfs-only", action="store_true")
    parser.add_argument("--limit", type=int, help="max entries per kind (smoke runs)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-annotate entries that already have annotations",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
