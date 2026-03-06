import json
import logging
import re

import markdown as _md
from beanie import PydanticObjectId

_TAG_RE = re.compile(r"(<[^>]+>)")
from maestro.models import (
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.profile import get_cefr_level
from maestro.utils import create_background_task
from maestro.vocab.nlp import get_nlp
from maestro.vocab import cache as _cache

logger = logging.getLogger(__name__)


def _lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only."""
    nlp = get_nlp()
    doc = nlp(text)
    return [
        token.lemma_.lower()
        for token in doc
        if token.is_alpha and not token.is_stop and len(token) > 2
    ]


async def discover(response_text: str, student_id: PydanticObjectId | None = None, message=None) -> str:
    text_lemmas = _lemmatize(response_text)

    words_with_vocab = {l: w for l, w in _cache.word_index().items() if l in text_lemmas}
    matched_word_ids = [w.id for w in words_with_vocab.values()]

    card_filter: dict = {"word.$id": {"$in": matched_word_ids}}
    if student_id is not None:
        card_filter["student_id"] = student_id
    existing_cards = await UserVocabularyCard.find(card_filter).to_list()
    existing_word_ids = {card.word.ref.id for card in existing_cards}

    new_words = [w for w in words_with_vocab.values() if w.id not in existing_word_ids]

    if new_words:
        await UserVocabularyCard.insert_many(
            [UserVocabularyCard(student_id=student_id, word=w, message=message) for w in new_words]
        )
        words_without_defs = [
            w for w in new_words
            if w.senses and not any(
                _cache.get_definition(str(w.id), lvl) for lvl in ("A1", "A2", "B1", "B2")
            )
        ]
        if words_without_defs:
            create_background_task(
                _generate_and_cache(words_without_defs),
                name=f"vocab-defs-{'-'.join(w.word for w in words_without_defs[:3])}",
            )

    student_level = await get_cefr_level(student_id) if student_id else "A1"

    annotated_text = response_text
    for w in words_with_vocab.values():
        word_id = str(w.id)
        wdef = _cache.get_definition(word_id, student_level)
        annotated_text = _annotate(annotated_text, w, wdef)

    return annotated_text


async def discover_markdown(text: str, student_id: PydanticObjectId | None = None) -> str:
    html = _md.markdown(text, extensions=["extra", "nl2br", "sane_lists"])
    return await discover(html, student_id=student_id)


async def discover_list(texts: list[str], student_id: PydanticObjectId | None = None) -> list[str]:
    return [await discover(t, student_id=student_id) for t in texts]


async def _generate_and_cache(words: list[VocabularyWord]) -> None:
    """Background task: generate CEFR-aware definitions and update the cache."""
    from maestro.vocab.generate_definitions import generate_definitions_for_word
    for word in words:
        try:
            await generate_definitions_for_word(word)
            defs = await VocabularyWordDefinition.find({"word.$id": word.id}).to_list()
            for d in defs:
                _cache.set_definition(str(word.id), d.student_level, d)
            logger.info(f"[discover] generated {len(defs)} definition(s) for '{word.word}'")
        except Exception as exc:
            logger.warning(f"[discover] definition generation failed for '{word.word}': {exc}")


def _annotate(
    text: str, word: VocabularyWord, wdef: VocabularyWordDefinition | None
) -> str:
    """Wrap the first occurrence of word.word in a popover span, skipping headings."""
    pattern = re.compile(rf"\b({re.escape(word.word)})\b", re.IGNORECASE)

    senses_data = []
    translation = ""
    if wdef:
        senses_data = [
            {"definition": s.definition, "translation": s.translation, "examples": s.examples}
            for s in wdef.senses
        ]
        translation = wdef.translation

    senses_json = json.dumps(senses_data, ensure_ascii=False).replace("'", "&#39;")

    attrs = (
        f' class="vocab-word"'
        f' data-word="{word.word}"'
        f' data-pos="{word.part_of_speech or ""}"'
        f' data-syllabization="{word.syllabization or ""}"'
        f" data-senses='{senses_json}'"
        f' data-translation="{translation}"'
        f' data-entry-id="{word.entry_id or ""}"'
    )
    replacement = f"<span{attrs}>" + r"\1</span>"

    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#"):
            continue
        # Split into alternating text nodes (even indices) and HTML tags (odd indices).
        # Only replace inside text nodes to avoid corrupting attribute values.
        parts = _TAG_RE.split(line)
        for j in range(0, len(parts), 2):
            new_part, n = pattern.subn(replacement, parts[j], count=1)
            if n:
                parts[j] = new_part
                lines[i] = "".join(parts)
                return "\n".join(lines)
    return text
