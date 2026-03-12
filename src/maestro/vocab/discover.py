import json
import logging
import re

import markdown as _md
from beanie import PydanticObjectId
from bs4 import BeautifulSoup, NavigableString, Tag
from bson import DBRef

from maestro.models import (
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.profile import get_cefr_level
from maestro.utils import create_background_task, lang_wrap
from maestro.vocab.generate_definitions import generate_definitions_for_word
from maestro.vocab.nlp import get_nlp
from maestro.vocab import cache as _cache

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"(<[^>]+>)")
_TRANSLATION_RE = re.compile(r"(</span>)\s*\(([^)]+)\)")

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# Tags that should never be targets for vocab discovery, even if they carry lang="it".
# <html lang="it"> is the root element and would make the entire page a target.
_SKIP_DISCOVER_TAGS = frozenset({"html", "head", "title", "script", "style", "nav"})


def lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only.

    No stop-word filter — the vocab word_index already gates which lemmas
    produce matches, and stop words (sì, no, come, bene …) are legitimate
    vocabulary for language learners.
    """
    nlp = get_nlp()
    doc = nlp(text)
    return [token.lemma_.lower() for token in doc if token.is_alpha and len(token) > 1]


def _build_vocab_attrs(word, wdef) -> str:
    """Build the data-attribute string for a vocab-word popover span."""
    senses_data = []
    translation = ""
    if wdef:
        senses_data = [
            {
                "definition": s.definition,
                "translation": s.translation,
                "examples": s.examples,
            }
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
        f' data-audio-path="{getattr(word, "audio_url", None) or ""}"'
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


def get_target_text(lang_elements: list) -> str:
    """Extract text from lang elements, skipping text inside nested lang elements."""
    parts = []
    for el in lang_elements:
        for desc in el.descendants:
            if not isinstance(desc, NavigableString):
                continue
            if _has_nested_lang(desc, el):
                continue
            text = str(desc).strip()
            if text:
                parts.append(text)
    return " ".join(parts)


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
    lang_elements = [
        el
        for el in soup.find_all(attrs={"lang": target_lang})
        if el.name not in _SKIP_DISCOVER_TAGS
    ]
    if not lang_elements:
        return response_text

    # Lemmatize only text within target-language elements (skip nested lang tags)
    target_text = get_target_text(lang_elements)
    text_lemmas = lemmatize(target_text)

    words_with_vocab = {
        lem: w for lem, w in _cache.word_index().items() if lem in text_lemmas
    }
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
            [
                UserVocabularyCard(student_id=student_id, word=w, message=message)
                for w in new_words
            ]
        )
        # A0 words have simple built-in definitions — skip LLM generation
        words_without_defs = [
            w
            for w in new_words
            if w.cefr_level != "A0"
            and w.senses
            and not any(
                _cache.get_definition(str(w.id), lvl)
                for lvl in ("A1", "A2", "B1", "B2")
            )
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


def preprocess_grammar_markdown(text: str) -> str:
    """Fix LLM span-tagging patterns that break markdown parsing.

    Two known failure modes:
    1. Headings wrapped in a lang span: <span lang="en">## Heading\n\n</span>
       — the markdown parser never sees ## at the start of a line.
    2. Table rows whose first cell is inside an opening span:
       <span lang="en">| col1 | col2 |
       — the parser doesn't recognise the line as a table row.

    Ideally the LLM would place spans INSIDE the heading marker:
      ## <span lang="it">Formazione</span>
    which the markdown parser handles correctly without any preprocessing.
    The prompt instructs this but the LLM occasionally wraps the marker too.
    """
    # Fix 1: Strip span wrappers around markdown headings.
    # No \s* before </span> so trailing \n\n inside the span is preserved in group 1.
    text = re.sub(r"<span[^>]*>(#{1,6}\s[^<]+?)</span>", r"\1", text)
    # Fix 2: Strip all span tags from table rows.
    lines = []
    for line in text.split("\n"):
        if re.sub(r"</?span[^>]*>", "", line).lstrip().startswith("|"):
            line = re.sub(r"</?span[^>]*>", "", line)
        lines.append(line)
    return "\n".join(lines)


async def discover_markdown(
    text: str,
    student_id: PydanticObjectId | None = None,
    lang: str | None = None,
) -> str:
    text = preprocess_grammar_markdown(text)
    html = _md.markdown(text, extensions=["extra", "nl2br", "sane_lists"])
    if lang:
        html = lang_wrap(html, lang)
    return await discover(html, student_id=student_id)


async def discover_list(
    texts: list[str], student_id: PydanticObjectId | None = None
) -> list[str]:
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
            logger.info(
                f"[discover] generated {len(defs)} definition(s) for '{word.word}'"
            )
        except Exception as exc:
            logger.warning(
                f"[discover] definition generation failed for '{word.word}': {exc}"
            )


def hide_translations(html: str) -> str:
    """Wrap parenthesized English translations after </span> in a toggleable span."""
    return _TRANSLATION_RE.sub(r'\1 <span class="translation-toggle">\2</span>', html)


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
