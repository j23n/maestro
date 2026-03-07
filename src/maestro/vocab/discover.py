import json
import logging
import re

import markdown as _md
from beanie import PydanticObjectId
from bs4 import BeautifulSoup, NavigableString, Tag
from bson import DBRef

_TAG_RE = re.compile(r"(<[^>]+>)")
from maestro.models import (
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.profile import get_cefr_level
from maestro.utils import create_background_task
from maestro.vocab.generate_definitions import generate_definitions_for_word
from maestro.vocab.nlp import get_nlp
from maestro.vocab import cache as _cache

logger = logging.getLogger(__name__)

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def lang_wrap(html: str, lang: str) -> str:
    """Wrap HTML content in a <span lang="xx"> tag."""
    return f'<span lang="{lang}">{html}</span>'


def _lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only."""
    nlp = get_nlp()
    doc = nlp(text)
    return [
        token.lemma_.lower()
        for token in doc
        if token.is_alpha and not token.is_stop and len(token) > 2
    ]


def _build_vocab_attrs(word, wdef) -> str:
    """Build the data-attribute string for a vocab-word popover span."""
    senses_data = []
    translation = ""
    if wdef:
        senses_data = [
            {"definition": s.definition, "translation": s.translation, "examples": s.examples}
            for s in wdef.senses
        ]
        translation = wdef.translation

    senses_json = json.dumps(senses_data, ensure_ascii=False).replace("'", "&#39;")

    return (
        f' class="vocab-word"'
        f' data-word="{word.word}"'
        f' data-pos="{word.part_of_speech or ""}"'
        f' data-syllabization="{word.syllabization or ""}"'
        f" data-senses='{senses_json}'"
        f' data-translation="{translation}"'
        f' data-entry-id="{word.entry_id or ""}"'
    )


def _is_inside_heading(node) -> bool:
    """Check if a node is inside an h1-h6 element."""
    for parent in node.parents:
        if isinstance(parent, Tag) and parent.name in _HEADING_TAGS:
            return True
    return False


def _has_nested_lang(node, lang_element) -> bool:
    """True if node is inside a nested element with its own lang attr (under lang_element)."""
    parent = node.parent
    while parent is not None and parent is not lang_element:
        if isinstance(parent, Tag) and parent.has_attr("lang"):
            return True
        parent = parent.parent
    return False


def _annotate_in_elements(lang_elements: list, word, wdef) -> bool:
    """Annotate the first occurrence of word within the given BS4 elements.

    Returns True if a match was found and annotated.
    """
    pattern = re.compile(rf"\b({re.escape(word.word)})\b", re.IGNORECASE)
    attrs = _build_vocab_attrs(word, wdef)

    for el in lang_elements:
        for text_node in list(el.descendants):
            if not isinstance(text_node, NavigableString):
                continue
            if _is_inside_heading(text_node):
                continue
            if _has_nested_lang(text_node, el):
                continue
            parent = text_node.parent
            if isinstance(parent, Tag) and "vocab-word" in (parent.get("class") or []):
                continue

            match = pattern.search(str(text_node))
            if match:
                original = str(text_node)
                before = original[: match.start()]
                matched = original[match.start() : match.end()]
                after = original[match.end() :]

                replacement_html = f"{before}<span{attrs}>{matched}</span>{after}"
                fragment = BeautifulSoup(replacement_html, "html.parser")
                text_node.replace_with(*list(fragment.children))
                return True
    return False


async def discover(
    response_text: str,
    student_id: PydanticObjectId | None = None,
    message=None,
) -> str:
    from maestro.config import settings

    target_lang = settings.TARGET_LANGUAGE

    # No lang attributes → return unchanged (safe default for untagged content)
    if ' lang="' not in response_text and " lang='" not in response_text:
        return response_text

    soup = BeautifulSoup(response_text, "html.parser")
    lang_elements = soup.find_all(attrs={"lang": target_lang})
    if not lang_elements:
        return response_text

    # Lemmatize only text within target-language elements
    target_text = " ".join(el.get_text(" ", strip=True) for el in lang_elements)
    text_lemmas = _lemmatize(target_text)

    words_with_vocab = {l: w for l, w in _cache.word_index().items() if l in text_lemmas}
    matched_word_ids = [w.id for w in words_with_vocab.values()]

    word_refs = [DBRef(VocabularyWord.Settings.name, wid) for wid in matched_word_ids]
    card_filter: dict = {"word": {"$in": word_refs}}
    if student_id is not None:
        card_filter["student_id"] = student_id
    existing_cards = await UserVocabularyCard.find(card_filter).to_list()
    existing_word_ids = {card.word.ref.id for card in existing_cards}

    new_words = [w for w in words_with_vocab.values() if w.id not in existing_word_ids]

    if new_words:
        await UserVocabularyCard.insert_many(
            [UserVocabularyCard(student_id=student_id, word=w, message=message) for w in new_words]
        )
        # A0 words have simple built-in definitions — skip LLM generation
        words_without_defs = [
            w
            for w in new_words
            if w.cefr_level != "A0"
            and w.senses
            and not any(_cache.get_definition(str(w.id), lvl) for lvl in ("A1", "A2", "B1", "B2"))
        ]
        if words_without_defs:
            create_background_task(
                _generate_and_cache(words_without_defs),
                name=f"vocab-defs-{'-'.join(w.word for w in words_without_defs[:3])}",
            )

    student_level = await get_cefr_level(student_id) if student_id else "A1"

    for w in words_with_vocab.values():
        word_id = str(w.id)
        wdef = _cache.get_definition(word_id, student_level)
        if wdef is None and student_level == "A0":
            wdef = _cache.get_definition(word_id, "A1")
        _annotate_in_elements(lang_elements, w, wdef)

    return str(soup)


async def discover_markdown(
    text: str,
    student_id: PydanticObjectId | None = None,
    lang: str | None = None,
) -> str:
    html = _md.markdown(text, extensions=["extra", "nl2br", "sane_lists"])
    if lang:
        html = lang_wrap(html, lang)
    return await discover(html, student_id=student_id)


async def discover_list(texts: list[str], student_id: PydanticObjectId | None = None) -> list[str]:
    return [await discover(t, student_id=student_id) for t in texts]


async def _generate_and_cache(words: list[VocabularyWord]) -> None:
    """Background task: generate CEFR-aware definitions and update the cache."""
    for word in words:
        try:
            await generate_definitions_for_word(word)
            defs = await VocabularyWordDefinition.find(
                {"word": DBRef(VocabularyWord.Settings.name, word.id)}
            ).to_list()
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
    attrs = _build_vocab_attrs(word, wdef)
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
