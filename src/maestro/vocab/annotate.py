"""Generation-time vocab annotation.

Produces verified surface→lemma mappings (VocabAnnotation) for lesson content
via a small LLM call, validated against the dictionary word index. Replaces
render-time spaCy lemmatization for lesson activities: only lemmas that
resolve to an exact dictionary headword are kept, so a bad guess can never
create a UserVocabularyCard.

Contextual lemmatization is exactly the failure mode of the runtime spaCy
pipeline (capisco→capiscare, parte/partire, gendered-lemma collapsing) and
exactly what an LLM does well; validation against the word index makes the
result safe regardless.
"""

from __future__ import annotations

import json
import logging
import re

from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import ActivityType, CallType, GeneratedDrill, VocabAnnotation
from maestro.utils import parse_llm_json
from maestro.vocab import cache as _cache

logger = logging.getLogger(__name__)

_ANNOTATION_SYSTEM = """\
You are a precise lemmatizer for {language_name} learner content.

For each numbered text, list every {language_name} content word with its
dictionary lemma. Rules:
- lemma is the dictionary citation form: infinitive for verbs, masculine
  singular for adjectives, singular for nouns, base form for articles
  (il for l'/la/lo, un for un'/una)
- include each distinct (surface, lemma) pair once per text, even if the
  surface occurs multiple times
- skip proper nouns (people, places, brands), numbers, and any words not in
  {language_name}
- multi-word expressions that function as a unit (e.g. "un po'") may be
  listed with the whole expression as both surface and lemma
- upos is the Universal POS tag of the surface in context: NOUN, VERB, AUX,
  ADJ, ADV, ADP, PRON, DET, CCONJ, SCONJ, INTJ, NUM

Return ONLY a JSON object:
{{"texts": [{{"index": 0, "tokens": [{{"surface": "...", "lemma": "...", "upos": "..."}}]}}]}}
"""

_LANGUAGE_NAMES = {"it": "Italian", "de": "German"}


def _validate_tokens(
    tokens: list[dict],
    text: str,
    language: str,
) -> list[VocabAnnotation]:
    """Keep only tokens whose surface occurs in the text and whose lemma is an
    exact word-index (or phrase-index) headword. Merge duplicates by
    (lemma, upos) into surface_forms lists."""
    word_idx = _cache.word_index(language)
    phrase_idx = _cache.phrase_index(language)

    merged: dict[tuple[str, str], VocabAnnotation] = {}
    for tok in tokens:
        if not isinstance(tok, dict):
            continue
        surface = str(tok.get("surface") or "").strip()
        lemma = str(tok.get("lemma") or "").strip().lower()
        upos = str(tok.get("upos") or "").strip().upper()
        if not surface or not lemma:
            continue
        # Surface must actually occur in the text (word-boundary, case-insensitive)
        pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", re.IGNORECASE)
        if not pattern.search(text):
            logger.debug("[annotate] surface %r not found in text — dropped", surface)
            continue
        # Lemma must be an exact dictionary headword — this is the validation
        # that prevents vocabulary pollution. No fuzzy fallback by design.
        if lemma not in word_idx and lemma not in phrase_idx:
            logger.debug("[annotate] lemma %r not in word index — dropped", lemma)
            continue
        key = (lemma, upos)
        if key in merged:
            if surface not in merged[key].surface_forms:
                merged[key].surface_forms.append(surface)
        else:
            merged[key] = VocabAnnotation(
                surface_forms=[surface], lemma=lemma, upos=upos
            )
    return list(merged.values())


async def annotate_texts(
    texts: list[str],
    *,
    language: str,
    entity_id=None,
    student_id=None,
) -> list[list[VocabAnnotation]] | None:
    """Return one validated VocabAnnotation list per input text, or None on failure.

    Returns None (rather than empty lists) when annotation cannot be trusted:
    LLM/parse failure or an unloaded word index. Callers must treat None as
    "leave content unannotated" so render-time discovery falls back to the
    legacy NLP path instead of silently showing no vocabulary.
    """
    if not texts:
        return []
    if not _cache.word_index(language):
        logger.warning("[annotate] word index empty for %s — skipping", language)
        return None

    language_name = _LANGUAGE_NAMES.get(language, language)
    numbered = "\n\n".join(f"### Text {i}\n{t}" for i, t in enumerate(texts))
    try:
        response = await llm_messages_create(
            model=settings.ANNOTATION_MODEL,
            max_tokens=8000,
            system=_ANNOTATION_SYSTEM.format(language_name=language_name),
            messages=[{"role": "user", "content": numbered}],
            entity_id=entity_id,
            call_type=CallType.ANNOTATION,
            student_id=student_id,
        )
        raw = response.content[0].text
        result = parse_llm_json(raw)
    except Exception:
        logger.exception("[annotate] annotation LLM call failed")
        return None

    if not isinstance(result, dict) or not isinstance(result.get("texts"), list):
        logger.warning("[annotate] unparseable annotation response")
        return None

    by_index: dict[int, list[dict]] = {}
    for entry in result["texts"]:
        if isinstance(entry, dict) and isinstance(entry.get("tokens"), list):
            try:
                by_index[int(entry.get("index"))] = entry["tokens"]
            except (TypeError, ValueError):
                continue

    annotations = [
        _validate_tokens(by_index.get(i, []), text, language)
        for i, text in enumerate(texts)
    ]
    logger.info(
        "[annotate] annotated %d texts: %s validated mappings",
        len(texts),
        [len(a) for a in annotations],
    )
    return annotations


def _activity_target_text(activity, drill: GeneratedDrill | None) -> str:
    """Collect the target-language text rendered for an activity."""
    parts: list[str] = []
    if activity.type == ActivityType.DRILL:
        if drill:
            parts.extend(item.prompt for item in drill.items if item.prompt)
    else:
        if activity.content:
            parts.append(activity.content)
        parts.extend(q.text for q in activity.questions if q.text)
    return "\n".join(parts)


_ANNOTATABLE_TYPES = (
    ActivityType.READING,
    ActivityType.LISTENING,
    ActivityType.SPEAKING,
    ActivityType.WRITING,
    ActivityType.DRILL,
    ActivityType.GRAMMAR,
    ActivityType.INTRO,
    ActivityType.INFO,
)


async def annotate_lesson_activities(
    activities: list,
    *,
    language: str,
    lesson_id=None,
    student_id=None,
) -> None:
    """Annotate any unannotated content-bearing activities in place.

    Fully defensive: any failure leaves activities unannotated (render-time
    discovery then falls back to the legacy NLP path). One LLM call covers
    all texts in the lesson.
    """
    try:
        targets: list = []
        texts: list[str] = []
        for act in activities:
            if act.type not in _ANNOTATABLE_TYPES or act.vocab_annotated:
                continue
            drill = None
            if act.type == ActivityType.DRILL:
                if act.drill_id is None:
                    continue
                drill = await GeneratedDrill.get(act.drill_id)
            text = _activity_target_text(act, drill)
            if not text.strip():
                continue
            targets.append(act)
            texts.append(text)

        if not texts:
            return

        annotations = await annotate_texts(
            texts, language=language, entity_id=lesson_id, student_id=student_id
        )
        if annotations is None:
            return

        for act, anns in zip(targets, annotations):
            act.vocab_annotations = anns
            act.vocab_annotated = True
        logger.info(
            "lesson activities annotated",
            extra={
                "lesson_id": str(lesson_id),
                "n_activities": len(targets),
                "n_mappings": sum(len(a) for a in annotations),
            },
        )
    except Exception:
        logger.exception(
            "activity annotation failed", extra={"lesson_id": str(lesson_id)}
        )


def merge_annotations(activities: list) -> list[VocabAnnotation]:
    """Union of all activities' annotations, deduplicated by (lemma, upos).

    Used for pages that render content spanning a whole lesson (overview,
    completion page) rather than a single activity.
    """
    merged: list[VocabAnnotation] = []
    seen: set[tuple[str, str]] = set()
    for act in activities:
        for ann in getattr(act, "vocab_annotations", []) or []:
            key = (ann.lemma, ann.upos)
            if key not in seen:
                seen.add(key)
                merged.append(ann)
    return merged


def annotations_from_dicts(raw: list[dict] | None) -> list[VocabAnnotation]:
    """Parse bank-file annotation dicts into VocabAnnotation, skipping invalid."""
    out: list[VocabAnnotation] = []
    for item in raw or []:
        try:
            out.append(VocabAnnotation.model_validate(item))
        except Exception:
            logger.warning("invalid bank annotation skipped: %s", json.dumps(item))
    return out
