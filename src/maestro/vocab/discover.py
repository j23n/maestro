import re
from maestro.models import VocabularyWord, UserVocabularyCard, Message
from maestro.vocab.nlp import get_nlp


_vocab_index: dict[str, VocabularyWord] = {}


async def load_vocab():
    nlp = get_nlp()
    words = await VocabularyWord.find_all().to_list()
    _vocab_index.update({nlp(w.word)[0].lemma_.lower(): w for w in words})


def _lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only."""
    nlp = get_nlp()
    doc = nlp(text)
    return [
        token.lemma_.lower()
        for token in doc
        if token.is_alpha and not token.is_stop and len(token) > 2
    ]


async def discover(response_text: str, message) -> str:
    text_lemmas = _lemmatize(response_text)

    words_with_vocab = {l: w for l, w in _vocab_index.items() if l in text_lemmas}
    matched_word_ids = [w.id for w in words_with_vocab.values()]

    existing_cards = await UserVocabularyCard.find(
        {"word.$id": {"$in": matched_word_ids}}
    ).to_list()
    existing_word_ids = {card.word.ref.id for card in existing_cards}

    new_words = [w for w in words_with_vocab.values() if w.id not in existing_word_ids]

    await UserVocabularyCard.insert_many(
        [UserVocabularyCard(word=w, discovered_in_message=message) for w in new_words]
    )

    annotated_text = response_text
    for w in words_with_vocab.values():
        annotated_text = _annotate(annotated_text, w)

    return annotated_text


def _annotate(text: str, word: VocabularyWord) -> str:
    """Wrap the first occurrence of word.word in a popover span, skipping heading lines."""
    pattern = re.compile(rf"\b({re.escape(word.word)})\b", re.IGNORECASE)
    replacement = (
        f'<span class="vocab-word"'
        f' data-word="{word.word}"'
        f' data-definition="{word.definition}"'
        f' data-translation="{word.translation}">'
        r"\1</span>"
    )
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#"):
            continue
        new_line, n = pattern.subn(replacement, line, count=1)
        if n:
            lines[i] = new_line
            return "\n".join(lines)
    return text
