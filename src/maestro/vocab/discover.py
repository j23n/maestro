import json
import re

_TAG_RE = re.compile(r"(<[^>]+>)")
from maestro.models import (
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
    LearningProfile,
)
from maestro.vocab.nlp import get_nlp


_vocab_index: dict[str, VocabularyWord] = {}
# Keyed by (word_id_str, student_level) → VocabularyWordDefinition
_def_index: dict[tuple[str, str], VocabularyWordDefinition] = {}


async def load_vocab():
    nlp = get_nlp()
    words = await VocabularyWord.find_all().to_list()
    word_forms = [w.word for w in words]
    lemmas = (
        doc[0].lemma_.lower()
        for doc in nlp.pipe(word_forms, disable=["parser", "senter", "ner"], batch_size=512)
    )
    _vocab_index.update({lemma: word for lemma, word in zip(lemmas, words)})

    defs = await VocabularyWordDefinition.find_all().to_list()
    for d in defs:
        word_id = str(d.word.ref.id) if hasattr(d.word, "ref") else str(d.word.id)
        _def_index[(word_id, d.student_level)] = d


def _lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only."""
    nlp = get_nlp()
    doc = nlp(text)
    return [
        token.lemma_.lower()
        for token in doc
        if token.is_alpha and not token.is_stop and len(token) > 2
    ]


async def _get_student_level() -> str:
    profile = await LearningProfile.find_one()
    return profile.cefr_estimate if profile else "A1"


async def discover(response_text: str, message=None) -> str:
    text_lemmas = _lemmatize(response_text)

    words_with_vocab = {l: w for l, w in _vocab_index.items() if l in text_lemmas}
    matched_word_ids = [w.id for w in words_with_vocab.values()]

    existing_cards = await UserVocabularyCard.find(
        {"word.$id": {"$in": matched_word_ids}}
    ).to_list()
    existing_word_ids = {card.word.ref.id for card in existing_cards}

    new_words = [w for w in words_with_vocab.values() if w.id not in existing_word_ids]

    if new_words:
        await UserVocabularyCard.insert_many(
            [UserVocabularyCard(word=w, message=message) for w in new_words]
        )

    student_level = await _get_student_level()

    annotated_text = response_text
    for w in words_with_vocab.values():
        word_id = str(w.id)
        wdef = _def_index.get((word_id, student_level))
        annotated_text = _annotate(annotated_text, w, wdef)

    return annotated_text


def _annotate(
    text: str, word: VocabularyWord, wdef: VocabularyWordDefinition | None
) -> str:
    """Wrap the first occurrence of word.word in a popover span, skipping headings."""
    pattern = re.compile(rf"\b({re.escape(word.word)})\b", re.IGNORECASE)

    senses_data = []
    translation = ""
    if wdef:
        senses_data = [
            {"definition": s.definition, "examples": s.examples}
            for s in wdef.senses
        ]
        translation = wdef.translation
    elif word.senses:
        # Fall back to raw EPUB senses if no graded definition yet
        senses_data = [
            {"definition": s.definition, "examples": s.examples[:1]}
            for s in word.senses
            if s.definition
        ]

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
