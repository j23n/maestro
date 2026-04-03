"""
One-off ingest script:
  1. Replace all GrammarPoint documents from grammar_points.yaml (full replace)
  2. Set chunk_ref on each GP from the static mapping file
  3. Replace all CommunicativeFunction documents from comm_functions.json
  4. Create empty LearningProfile if none exists

Run with:
  python -m maestro.sync.ingest
"""

import asyncio
import json
import logging

import yaml

from maestro.db import init_db

from maestro.models import (
    CefrSense,
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    VocabularyWord,
    VocabularyWordDefinition,
)
from maestro.lessons.curriculum import detect_prerequisite_cycles
from maestro.utils import data_dir, iter_language_dirs, utcnow

logger = logging.getLogger(__name__)


async def upsert_grammar_points() -> list[GrammarPoint]:
    all_codes: set[str] = set()
    gp_fields = set(GrammarPoint.model_fields.keys()) - {"id"}
    for lang_dir in iter_language_dirs():
        lang = lang_dir.name
        gp_file = lang_dir / "grammar_points.yaml"
        if not gp_file.exists():
            continue
        with open(gp_file) as f:
            items = yaml.safe_load(f)
        for item in items:
            all_codes.add(item["code"])
            gp = await GrammarPoint.find_one({"code": item["code"]})
            if gp:
                for key, val in item.items():
                    if key in gp_fields:
                        setattr(gp, key, val)
                gp.language = lang
                await gp.save()
            else:
                filtered = {k: v for k, v in item.items() if k in gp_fields}
                await GrammarPoint(**filtered, language=lang).insert()
    # Remove GPs that no longer exist in any data file
    existing = await GrammarPoint.find_all().to_list()
    for gp in existing:
        if gp.code not in all_codes:
            await gp.delete()
    inserted = await GrammarPoint.find_all().to_list()
    logger.info(f"Grammar points: upserted {len(inserted)} records")
    return inserted


async def link_grammar_points_to_chunks(grammar_points: list[GrammarPoint]) -> None:
    """Set chunk_ref on each GP from the static mapping file."""
    for lang_dir in iter_language_dirs():
        chunk_file = lang_dir / "grammar_point_chunks.yaml"
        if not chunk_file.exists():
            continue
        with open(chunk_file) as f:
            mapping = yaml.safe_load(f) or {}
        for gp in grammar_points:
            if gp.language != lang_dir.name:
                continue
            ref = mapping.get(gp.code)
            if ref:
                gp.chunk_ref = ref
                await gp.save()

    mapped = sum(1 for gp in grammar_points if gp.chunk_ref)
    logger.info(f"Chunk refs set: {mapped}/{len(grammar_points)}")


async def upsert_comm_functions() -> None:
    total = 0
    for lang_dir in iter_language_dirs():
        lang = lang_dir.name
        cf_file = lang_dir / "comm_functions.json"
        if not cf_file.exists():
            continue
        await CommunicativeFunction.find(
            CommunicativeFunction.language == lang
        ).delete()
        with open(cf_file) as f:
            items = json.load(f)
        docs = []
        for item in items:
            if not item.get("description"):
                patterns = item.get("patterns", [])
                item["description"] = (
                    "; ".join(patterns[:3]) if patterns else item["label"]
                )
            docs.append(CommunicativeFunction(**item, language=lang))
        await CommunicativeFunction.insert_many(docs)
        total += len(docs)
    logger.info(f"Communicative functions: inserted {total} items")


async def seed_scenarios() -> None:
    """Upsert CurriculumScenario documents from scenario YAML files."""
    total = 0
    all_slugs: set[str] = set()
    for lang_dir in iter_language_dirs():
        lang = lang_dir.name
        for filename in ("scenarios_a0.yaml", "scenarios_a1.yaml"):
            scenario_file = lang_dir / filename
            if not scenario_file.exists():
                continue

            with open(scenario_file) as f:
                data = yaml.safe_load(f)

            scenarios = data.get("scenarios", [])
            for item in scenarios:
                all_slugs.add(item["slug"])
                existing = await CurriculumScenario.find_one({"slug": item["slug"]})
                if existing:
                    for key, val in item.items():
                        setattr(existing, key, val)
                    existing.language = lang
                    await existing.save()
                else:
                    await CurriculumScenario(**item, language=lang).insert()
            total += len(scenarios)

    # Remove scenarios that no longer exist in the YAML files
    existing_all = await CurriculumScenario.find_all().to_list()
    stale = [s for s in existing_all if s.slug not in all_slugs]
    for s in stale:
        await s.delete()
    if stale:
        logger.info(
            "Scenarios: removed %d stale: %s",
            len(stale),
            [s.slug for s in stale],
        )

    logger.info(f"Scenarios: upserted {total} records")


async def seed_a0_vocab(language: str) -> None:
    """Upsert A0 vocabulary words from vocab_a0.yaml and create A0-level definitions.

    Each YAML entry has word, part_of_speech, and translation.  These are words
    and phrases NOT in the dictionary — they get a translation-only A0
    definition (no target-language definition text, just the English gloss).
    """
    lang = language
    vocab_file = data_dir(lang) / "vocab_a0.yaml"
    if not vocab_file.exists():
        logger.warning(f"A0 vocab file not found: {vocab_file}")
        return

    with open(vocab_file) as f:
        items = yaml.safe_load(f)

    # Purge existing A0-level definitions for this language — only
    # vocab_a0.yaml words should have A0 definitions (translation only).
    purged = await VocabularyWordDefinition.find(
        {"student_level": "A0", "language": lang}
    ).delete()
    if purged and purged.deleted_count:
        logger.info(
            f"A0 vocab [{lang}]: purged {purged.deleted_count} old A0 definitions"
        )

    count = 0
    def_count = 0
    for item in items:
        item_pos = item.get("part_of_speech", "")
        query = {"word": item["word"], "language": lang}
        if item_pos:
            query["part_of_speech"] = item_pos
        existing = await VocabularyWord.find_one(query)
        now = utcnow()
        syllabization = item.get("syllabization", "")
        ipa = item.get("ipa", "")
        if existing:
            existing.cefr_level = "A0"
            existing.part_of_speech = item_pos or existing.part_of_speech
            if syllabization:
                existing.syllabization = syllabization
            if ipa:
                existing.ipa = ipa
            existing.updated_at = now
            await existing.save()
            word_doc = existing
        else:
            word_doc = VocabularyWord(
                word=item["word"],
                part_of_speech=item_pos,
                syllabization=syllabization or None,
                ipa=ipa or None,
                cefr_level="A0",
                senses=[],
                language=lang,
                created_at=now,
                updated_at=now,
            )
            await word_doc.insert()
            count += 1

        # Create A0-level definition with translation only
        translation = item.get("translation", "")
        if not translation:
            continue

        cefr_senses = [CefrSense(definition="", translation=translation)]
        await VocabularyWordDefinition(
            word=word_doc,
            student_level="A0",
            senses=cefr_senses,
            translation=translation,
            language=lang,
            created_at=utcnow(),
        ).insert()
        def_count += 1

    logger.info(
        f"A0 vocab [{lang}]: {count} new words inserted, {def_count} new definitions ({len(items)} total)"
    )


async def seed_dwds_headwords() -> None:
    """Ingest bare VocabularyWord documents from DWDS headwords JSON.

    Creates one VocabularyWord per headword with empty senses — enrichment
    from DWDS web pages happens on-demand when words are discovered.
    Skips words that already exist (by word + part_of_speech + language).
    """
    import re
    import unicodedata

    from pymongo.errors import BulkWriteError

    headwords_path = data_dir("de") / "dwds_headwords.json"
    if not headwords_path.exists():
        logger.warning("dwds: headwords file not found: %s", headwords_path)
        return

    superscript_re = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$")

    raw: dict[str, str] = json.loads(headwords_path.read_text())
    seen: set[str] = set()
    words: list[str] = []
    for headword in raw:
        stripped = headword.strip()
        if not stripped or stripped.startswith("-") or not stripped[0].isalpha():
            continue
        stripped = superscript_re.sub("", stripped)
        stripped = unicodedata.normalize("NFC", stripped)
        if stripped and stripped not in seen:
            seen.add(stripped)
            words.append(stripped)

    logger.info("dwds: loaded %d unique headwords", len(words))

    now = utcnow()
    docs = [
        VocabularyWord(
            word=w,
            part_of_speech="",
            language="de",
            senses=[],
            cefr_level=None,
            created_at=now,
            updated_at=now,
        )
        for w in words
    ]

    batch_size = 500
    inserted = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        try:
            await VocabularyWord.insert_many(batch)
            inserted += len(batch)
        except BulkWriteError:
            for doc in batch:
                existing = await VocabularyWord.find_one(
                    VocabularyWord.word == doc.word,
                    VocabularyWord.part_of_speech == doc.part_of_speech,
                    VocabularyWord.language == doc.language,
                )
                if not existing:
                    try:
                        await doc.insert()
                        inserted += 1
                    except Exception:
                        pass

        if (i + batch_size) % 5000 < batch_size:
            logger.info(
                "dwds: progress %d / %d", min(i + batch_size, len(docs)), len(docs)
            )

    logger.info("dwds: ingested %d new VocabularyWord documents", inserted)


async def ingest():
    await init_db()

    logger.info("=== Ingesting grammar points ===")
    await upsert_grammar_points()

    logger.info("=== Ingesting communicative functions ===")
    await upsert_comm_functions()

    logger.info("=== Seeding curriculum scenarios ===")
    await seed_scenarios()

    logger.info("=== Seeding A0 vocabulary ===")
    await seed_a0_vocab()

    logger.info("=== Validating grammar prerequisites ===")
    await _validate_prerequisites()

    logger.info("Done.")


async def _validate_prerequisites() -> None:
    """Validate that all prerequisite GP codes reference existing grammar points."""
    all_gps = await GrammarPoint.find_all().to_list()
    valid_codes = {gp.code for gp in all_gps}
    gps_with_prereqs = [gp for gp in all_gps if gp.prerequisites]
    if not gps_with_prereqs:
        logger.info("No grammar points have prerequisites")
        return
    for gp in gps_with_prereqs:
        for dep in gp.prerequisites:
            if dep not in valid_codes:
                logger.warning(
                    "prerequisite '%s' (for '%s') not found in grammar points",
                    dep,
                    gp.code,
                )

    # Check for cycles — a cycle would permanently lock those GPs
    prereqs_map = {gp.code: gp.prerequisites for gp in gps_with_prereqs}
    cycles = detect_prerequisite_cycles(prereqs_map)
    for cycle in cycles:
        logger.warning(
            "prerequisite cycle detected: %s",
            " → ".join(cycle),
        )


if __name__ == "__main__":
    asyncio.run(ingest())
