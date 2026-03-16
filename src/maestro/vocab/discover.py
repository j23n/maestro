import json
import logging
import re

from beanie import PydanticObjectId
from bs4 import BeautifulSoup, NavigableString, Tag
from bson import DBRef

from maestro.models import (
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.profile import get_cefr_level
from maestro.utils import create_background_task
from maestro.vocab.generate_definitions import generate_definitions_for_word
from maestro.vocab.nlp import get_nlp
from maestro.vocab.pos import matches_pos
from maestro.vocab import cache as _cache

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"(<[^>]+>)")
_TRANSLATION_RE = re.compile(r"(</span>)\s*\(([^)]+)\)")

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# Tags that should never be targets for vocab discovery, even if they carry lang="it".
# <html lang="en"> is the norm; `html` here is defense-in-depth.
_SKIP_DISCOVER_TAGS = frozenset({"html", "head", "title", "script", "style", "nav"})


def _keep_token(token) -> bool:
    """True if the token should be considered for vocab discovery.

    Checks the *lemma* rather than the surface form so that elided tokens
    like ``dov'`` (lemma ``dove``) and ``l'`` (lemma ``il``) are included.
    """
    lem = token.lemma_
    return lem.isalpha() and len(lem) > 1


def lemmatize(text: str) -> list[str]:
    """Return the lemma of each token in text, lowercased, alphabetic only.

    No stop-word filter — the vocab word_index already gates which lemmas
    produce matches, and stop words (sì, no, come, bene …) are legitimate
    vocabulary for language learners.
    """
    nlp = get_nlp()
    doc = nlp(text)
    return [token.lemma_.lower() for token in doc if _keep_token(token)]


def lemmatize_with_pos(text: str) -> list[tuple[str, str]]:
    """Return (lemma, universal_POS) for each token, lowercased, alphabetic only.

    Like lemmatize(), but also captures the spaCy POS tag for disambiguation
    when multiple dictionary entries exist for the same lemma.
    """
    nlp = get_nlp()
    doc = nlp(text)
    return [(token.lemma_.lower(), token.pos_) for token in doc if _keep_token(token)]


def _build_vocab_attrs(
    word, wdef, *, anonymous: bool = False, in_vocab: bool = False
) -> str:
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

    entry_id = "" if (anonymous or in_vocab) else (word.entry_id or "")

    return (
        f' class="vocab-word"'
        f' data-word="{word.word}"'
        f' data-pos="{word.part_of_speech or ""}"'
        f' data-syllabization="{word.syllabization or ""}"'
        f" data-senses='{senses_json}'"
        f' data-translation="{translation}"'
        f' data-entry-id="{entry_id}"'
        f' data-in-vocab="{"true" if in_vocab else ""}"'
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


def _annotate_in_elements(
    lang_elements: list,
    word,
    wdef,
    *,
    anonymous: bool = False,
    in_vocab: bool = False,
    surface_forms: list[str] | None = None,
) -> int:
    """Annotate all occurrences of word within the given BS4 elements.

    Tries the dictionary headword and any inflected surface forms found
    during lemmatization. Returns the number of matches annotated.
    """
    attrs = _build_vocab_attrs(word, wdef, anonymous=anonymous, in_vocab=in_vocab)

    # Build combined pattern: dictionary form + surface forms
    forms = {word.word.lower(): word.word}
    if surface_forms:
        for f in surface_forms:
            key = f.lower()
            # Keep the longest form per lowercased key
            if key not in forms or len(f) > len(forms[key]):
                forms[key] = f

    alternatives = "|".join(re.escape(f) for f in forms.values())
    pattern = re.compile(rf"\b({alternatives})\b", re.IGNORECASE)
    count = 0

    for el in lang_elements:
        # Re-collect text nodes each iteration since the tree mutates
        text_nodes = [
            n
            for n in el.descendants
            if isinstance(n, NavigableString)
            and not _is_inside_heading(n)
            and not _has_nested_lang(n, el)
            and not (
                isinstance(n.parent, Tag)
                and "vocab-word" in (n.parent.get("class") or [])
            )
        ]
        for text_node in text_nodes:
            original = str(text_node)
            parts = []
            last_end = 0
            for match in pattern.finditer(original):
                parts.append(original[last_end : match.start()])
                parts.append(f"<span{attrs}>{match.group()}</span>")
                last_end = match.end()
                count += 1
            if last_end == 0:
                continue
            parts.append(original[last_end:])
            fragment = BeautifulSoup("".join(parts), "html.parser")
            text_node.replace_with(*list(fragment.children))

    return count


async def discover(
    response_text: str,
    student_id: PydanticObjectId | None = None,
    message=None,
    create_cards: bool = True,
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
        and not el.find_parent(attrs={"data-no-discover": True})
    ]
    if not lang_elements:
        return response_text

    # Split into saveable (create cards) vs no-save (tooltip only) elements
    save_elements = [el for el in lang_elements if not el.has_attr("data-no-save")]
    nosave_elements = [el for el in lang_elements if el.has_attr("data-no-save")]

    # Lemmatize all elements for annotation, tracking surface forms for each lemma
    all_text = get_target_text(lang_elements)
    nlp = get_nlp()
    doc = nlp(all_text)
    text_tokens = [
        (token.lemma_.lower(), token.pos_, token.text)
        for token in doc
        if _keep_token(token)
    ]
    text_lemmas = [(lem, pos) for lem, pos, _ in text_tokens]

    # Map lemma → list of inflected surface forms seen in the text
    surface_map: dict[str, list[str]] = {}
    for lem, _, surface in text_tokens:
        forms = surface_map.setdefault(lem, [])
        if surface not in forms:
            forms.append(surface)

    save_text = get_target_text(save_elements) if nosave_elements else all_text
    save_lemma_set = (
        {lem for lem, _ in lemmatize_with_pos(save_text)} if nosave_elements else None
    )

    # Match lemmas to vocab entries, preferring the POS variant that matches context.
    # First occurrence's POS wins — if a word appears as both noun and verb in the
    # same text, the POS from its first occurrence is used for disambiguation.
    words_with_vocab: dict[str, VocabularyWord] = {}
    for lem, upos in text_lemmas:
        if lem in words_with_vocab:
            continue
        entries = _cache.word_index().get(lem)
        if not entries:
            continue
        if len(entries) == 1:
            words_with_vocab[lem] = entries[0]
        else:
            match = next(
                (e for e in entries if matches_pos(e.part_of_speech, upos)), None
            )
            # Fallback: sort by part_of_speech for deterministic selection
            words_with_vocab[lem] = (
                match or sorted(entries, key=lambda e: e.part_of_speech)[0]
            )
    matched_word_ids = [w.id for w in words_with_vocab.values()]

    if student_id is not None:
        word_refs = [
            DBRef(VocabularyWord.Settings.name, wid) for wid in matched_word_ids
        ]
        card_filter: dict = {"word": {"$in": word_refs}, "student_id": student_id}
        existing_cards = await UserVocabularyCard.find(card_filter).to_list()
        existing_word_ids = {card.word.ref.id for card in existing_cards}
    else:
        existing_word_ids = set()

    new_words = [
        w
        for lem, w in words_with_vocab.items()
        if w.id not in existing_word_ids
        and (save_lemma_set is None or lem in save_lemma_set)
    ]

    if new_words and create_cards:
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
    anonymous = student_id is None
    owned_word_ids = existing_word_ids | (
        {w.id for w in new_words} if create_cards else set()
    )

    for lem, w in words_with_vocab.items():
        word_id = str(w.id)
        wdef = _cache.get_definition(word_id, student_level)
        if wdef is None and student_level == "A0":
            wdef = _cache.get_definition(word_id, "A1")
        _annotate_in_elements(
            lang_elements,
            w,
            wdef,
            anonymous=anonymous,
            in_vocab=w.id in owned_word_ids,
            surface_forms=surface_map.get(lem),
        )

    return str(soup)


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
