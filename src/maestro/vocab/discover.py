import json
import logging
import re
from dataclasses import dataclass, field

import simplemma
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

# Inline tags that should NOT insert a space when joining adjacent text nodes.
_INLINE_TAGS = frozenset(
    {
        "b",
        "i",
        "u",
        "em",
        "strong",
        "span",
        "a",
        "mark",
        "sup",
        "sub",
        "abbr",
        "cite",
        "code",
        "dfn",
        "kbd",
        "q",
        "s",
        "samp",
        "small",
        "time",
        "var",
        "wbr",
    }
)

# Vowel endings tried when reconstructing an elided lemma (mezz' → mezzo).
_ELISION_VOWELS = ("o", "a", "e", "i")


@dataclass
class TokenOccurrence:
    """A single token occurrence in the input text."""

    surface: str  # exact text as it appeared
    pos: str  # spaCy UPOS tag
    index: int  # position among kept tokens (document order)


@dataclass
class VocabMatch:
    """A single vocabulary match: one lemma resolved to one dictionary entry."""

    lemma: str  # resolved lemma (post-simplemma fallback)
    word: VocabularyWord  # matched dictionary entry
    occurrences: list[TokenOccurrence] = field(default_factory=list)

    @property
    def surface_forms(self) -> list[str]:
        """Unique surface forms from occurrences, preserving first-seen order."""
        seen: set[str] = set()
        forms: list[str] = []
        for occ in self.occurrences:
            if occ.surface not in seen:
                seen.add(occ.surface)
                forms.append(occ.surface)
        return forms

    @property
    def pos(self) -> str:
        """UPOS of first occurrence (backward compat)."""
        return self.occurrences[0].pos if self.occurrences else ""


# Word IDs currently being generated — prevents concurrent LLM calls for the
# same word when multiple requests discover it simultaneously.  Unbounded but
# entries are removed in _generate_and_cache's finally block; if the process is
# killed mid-generation, stale entries are cleared on restart.
_pending_def_gen: set[str] = set()


def _keep_token(token) -> bool:
    """True if the token should be considered for vocab discovery.

    Checks the *lemma* rather than the surface form so that elided tokens
    like ``dov'`` (lemma ``dove``) and ``l'`` (lemma ``il``) are included.
    Strips trailing apostrophes before the alpha check so that unresolved
    elisions like ``cos'`` (lemma ``cos'`` instead of ``cosa``) aren't dropped.
    Accepts compound lemmas from spaCy contractions (``sul`` → lemma
    ``su il``) where each part is alphabetic.
    Excludes proper nouns (PROPN) to prevent names like Marco → marcare.
    """
    lem = token.lemma_.rstrip("'")
    if not (lem.isalpha() or all(p.isalpha() for p in lem.split())):
        return False
    return token.pos_ != "PROPN"


def tokenize(text: str) -> list[tuple[str, str, str]]:
    """Run spaCy on *text* and return kept tokens as (lemma, POS, surface) triples.

    Filters out punctuation, non-alpha, and proper nouns.
    """
    nlp = get_nlp()
    doc = nlp(text)
    tokens = []
    for token in doc:
        keep = _keep_token(token)
        if keep:
            lem = token.lemma_.lower()
            # Compound lemmas from contractions (sul → "su il"): use the
            # surface form so it matches dictionary headwords like "sul".
            if " " in lem:
                lem = token.text.lower()
            tokens.append((lem, token.pos_, token.text))
        logger.debug(
            "[discover] token: %-15s lemma=%-15s POS=%-6s keep=%s",
            token.text,
            token.lemma_,
            token.pos_,
            keep,
        )
    return tokens


def match_vocab_words(
    text: str,
    word_index: dict[str, list[VocabularyWord]] | None = None,
) -> list[VocabMatch]:
    """Tokenize *text*, match lemmas against *word_index*, return matches.

    Uses spaCy for lemmatization with a simplemma fallback for lemmas that
    spaCy gets wrong (e.g. ``capisco`` → ``capiscare`` instead of ``capire``).

    Supports per-occurrence POS disambiguation: if the same lemma appears with
    different POS tags that resolve to different dictionary entries (e.g.
    "piano" as noun vs adjective), both matches are returned.

    Parameters
    ----------
    text : str
        Plain text to tokenize and match (no HTML).
    word_index : dict, optional
        headword → list of VocabularyWord entries.  Defaults to the global
        vocab cache when ``None``.

    Returns
    -------
    list[VocabMatch]
        Matches in token order, deduplicated by (lemma, word.id).
    """
    if word_index is None:
        word_index = _cache.word_index()

    logger.debug("[discover] extracted text: %r", text)
    logger.debug("[discover] word_index has %d headwords", len(word_index))

    text_tokens = tokenize(text)
    logger.debug(
        "[discover] kept tokens: %s", [(s, lem, p) for lem, p, s in text_tokens]
    )

    # Map lemma → all inflected surface forms (for simplemma/elision fallback).
    # Read-only after construction — per-token surfaces are tracked via
    # TokenOccurrence on each VocabMatch instead.
    lemma_surfaces: dict[str, list[str]] = {}
    for lem, _, surface in text_tokens:
        forms = lemma_surfaces.setdefault(lem, [])
        if surface not in forms:
            forms.append(surface)

    # Match tokens to vocab entries with per-occurrence POS disambiguation.
    # Dedup key is (lemma, word.id) — same lemma can produce multiple matches
    # when different POS tags resolve to different dictionary entries.
    # Duplicate keys append an occurrence to the existing match.
    matches: list[VocabMatch] = []
    seen: dict[tuple[str, str], int] = {}  # key → index in matches
    resolved_lemmas: dict[str, str] = {}  # cache: spaCy lemma → resolved lemma
    for token_idx, (lem, upos, surface) in enumerate(text_tokens):
        # Check if a previous token already resolved this lemma
        if lem in resolved_lemmas:
            resolved_lem = resolved_lemmas[lem]
            entries = word_index.get(resolved_lem)
        else:
            entries = word_index.get(lem)
            resolved_lem = lem

        # Prefer surface form when it's a distinct headword with a POS that
        # matches the spaCy tag.  spaCy collapses gendered forms to a base
        # lemma (la→il, questa→questo, signora→signore) but the dictionary
        # carries each form as its own entry.  We only override when the
        # surface entry POS-matches the spaCy tag — this prevents "parte"
        # (s.f.) from stealing a VERB token away from lemma "partire" (v.intr.).
        surface_lower = surface.lower()
        if surface_lower != resolved_lem:
            surface_entries = word_index.get(surface_lower)
            if surface_entries and any(
                matches_pos(e.part_of_speech, upos) for e in surface_entries
            ):
                resolved_lem = surface_lower
                entries = surface_entries
                logger.debug(
                    "[discover] surface %r POS-matches %s — preferring over lemma %r",
                    surface_lower,
                    upos,
                    lem,
                )

        if entries:
            logger.debug(
                "[discover] lemma %r → word_index HIT (%d entries: %s)",
                resolved_lem,
                len(entries),
                [e.word for e in entries],
            )
        if not entries and lem not in resolved_lemmas:
            logger.debug(
                "[discover] lemma %r → word_index MISS, trying simplemma fallback", lem
            )
            for surf in lemma_surfaces.get(lem, []):
                candidate = simplemma.lemmatize(surf, lang="it").lower()
                logger.debug("[discover]   simplemma(%r) → %r", surf, candidate)
                if candidate != lem:
                    entries = word_index.get(candidate)
                    if entries:
                        logger.debug(
                            "[discover]   simplemma fallback HIT: %r → %s",
                            candidate,
                            [e.word for e in entries],
                        )
                        resolved_lem = candidate
                        resolved_lemmas[lem] = candidate
                        break
                    else:
                        logger.debug(
                            "[discover]   simplemma fallback MISS: %r not in word_index",
                            candidate,
                        )
            # Elision repair: mezz' → mezzo, grand' → grande, etc.
            if not entries and lem.endswith("'"):
                stem = lem.rstrip("'")
                for vowel in _ELISION_VOWELS:
                    candidate = stem + vowel
                    entries = word_index.get(candidate)
                    if entries:
                        logger.debug(
                            "[discover]   elision repair HIT: %r → %s",
                            candidate,
                            [e.word for e in entries],
                        )
                        resolved_lem = candidate
                        resolved_lemmas[lem] = candidate
                        break
                else:
                    logger.debug(
                        "[discover]   elision repair MISS: %r + vowels not in word_index",
                        stem,
                    )
            if not entries:
                logger.debug("[discover] lemma %r → NO MATCH (not in vocabulary)", lem)
                continue
        elif not entries:
            # resolved_lemmas cache pointed to a lemma no longer in word_index
            continue
        if len(entries) == 1:
            matched_word = entries[0]
        else:
            matched_word = (
                next((e for e in entries if matches_pos(e.part_of_speech, upos)), None)
                or sorted(entries, key=lambda e: e.part_of_speech)[0]
            )

        key = (resolved_lem, str(matched_word.id))
        occ = TokenOccurrence(surface=surface, pos=upos, index=token_idx)
        if key in seen:
            matches[seen[key]].occurrences.append(occ)
            logger.debug(
                "[discover] lemma %r (word=%r) — added occurrence #%d",
                resolved_lem,
                matched_word.word,
                len(matches[seen[key]].occurrences),
            )
            continue
        seen[key] = len(matches)

        matches.append(
            VocabMatch(
                lemma=resolved_lem,
                word=matched_word,
                occurrences=[occ],
            )
        )
        logger.debug(
            "[discover] lemma %r → matched vocab word %r (pos=%s)",
            resolved_lem,
            matched_word.word,
            matched_word.part_of_speech,
        )

    logger.debug(
        "[discover] SUMMARY: %d matches: %s",
        len(matches),
        [(m.lemma, m.word.word, m.word.part_of_speech) for m in matches],
    )
    return matches


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


def _has_nested_lang(node, lang_element) -> bool:
    """True if node is inside a nested element with its own lang attr (under lang_element)."""
    parent = node.parent
    while parent is not None and parent is not lang_element:
        if isinstance(parent, Tag) and parent.has_attr("lang"):
            return True
        parent = parent.parent
    return False


def get_target_text(lang_elements: list) -> str:
    """Extract text from lang elements, skipping text inside nested lang elements.

    Inline tags (b, i, em, strong, span, etc.) do NOT insert spaces between
    adjacent text nodes, so ``<b>a</b>more`` produces ``"amore"`` rather than
    ``"a more"``.  Block tags (div, p, br, etc.) insert a space.
    """
    parts: list[str] = []
    for el in lang_elements:
        if parts:
            parts.append(" ")  # space between separate lang elements
        for desc in el.descendants:
            if isinstance(desc, Tag):
                # Block element boundary → ensure a space separator
                if desc.name not in _INLINE_TAGS and parts:
                    parts.append(" ")
                continue
            if not isinstance(desc, NavigableString):
                continue
            if _has_nested_lang(desc, el):
                continue
            parts.append(str(desc))
    # Join all parts, then collapse whitespace
    return " ".join("".join(parts).split())


def _annotate_in_elements(
    lang_elements: list,
    word,
    wdef,
    *,
    anonymous: bool = False,
    in_vocab: bool = False,
    surface_forms: list[str] | None = None,
    max_count: int | None = None,
) -> int:
    """Annotate occurrences of word within the given BS4 elements.

    Tries the dictionary headword and any inflected surface forms found
    during lemmatization. Returns the number of matches annotated.

    When *max_count* is set, stops after that many matches.  Used by the
    multi-POS annotation path to annotate one occurrence at a time so each
    gets the correct dictionary entry's attributes.
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
                if max_count is not None and count >= max_count:
                    break
            if last_end == 0:
                continue
            parts.append(original[last_end:])
            fragment = BeautifulSoup("".join(parts), "html.parser")
            text_node.replace_with(*list(fragment.children))
            if max_count is not None and count >= max_count:
                return count

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

    # Scope discovery to lang="it" elements inside <main>
    # (excludes nav, head, vocab-tooltip, scripts automatically).
    # Fall back to all lang elements if no <main> is found (e.g. fragments).
    content_container = soup.find("main")

    if content_container is not None:
        lang_elements = list(content_container.find_all(attrs={"lang": target_lang}))
        logger.debug(
            "[discover] scoped to .site-container, found %d lang='%s' elements",
            len(lang_elements),
            target_lang,
        )
    else:
        lang_elements = list(soup.find_all(attrs={"lang": target_lang}))
        logger.debug(
            "[discover] no .site-container found (fragment mode), found %d lang='%s' elements",
            len(lang_elements),
            target_lang,
        )

    # Filter out elements marked data-no-discover (e.g. the drilled word on
    # the vocab practice page — annotating it would reveal the answer).
    lang_elements = [el for el in lang_elements if not el.has_attr("data-no-discover")]

    if not lang_elements:
        logger.debug("[discover] no lang elements found — returning unchanged")
        return response_text

    # Split into saveable (create cards) vs no-save (tooltip only) elements
    save_elements = [el for el in lang_elements if not el.has_attr("data-no-save")]
    nosave_elements = [el for el in lang_elements if el.has_attr("data-no-save")]

    # --- Vocabulary matching (pure NLP, no DB) ---
    all_text = get_target_text(lang_elements)
    matches = match_vocab_words(all_text, _cache.word_index())

    # Unique words by id — for card creation, def generation, DB queries.
    unique_words: dict[str, VocabMatch] = {}
    for m in matches:
        wid = str(m.word.id)
        if wid not in unique_words:
            unique_words[wid] = m
    matched_word_ids = [m.word.id for m in unique_words.values()]

    # --- Card creation (DB) ---
    save_text = get_target_text(save_elements) if nosave_elements else all_text

    # Determine which lemmas appear in save-eligible elements (those without
    # data-no-save). Token-set check avoids substring false positives
    # (e.g. surface "ara" matching inside "preparare").
    if nosave_elements:
        save_tokens = set(save_text.lower().split())
        save_lemma_set = {
            m.lemma
            for m in matches
            if any(s.lower() in save_tokens for s in m.surface_forms)
        }
    else:
        save_lemma_set = None

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
        m.word
        for m in unique_words.values()
        if m.word.id not in existing_word_ids
        and (save_lemma_set is None or m.lemma in save_lemma_set)
    ]

    if new_words and create_cards:
        await UserVocabularyCard.insert_many(
            [
                UserVocabularyCard(student_id=student_id, word=w, message=message)
                for w in new_words
            ]
        )

    # --- Definition generation (background) ---
    # For ANY discovered word missing A1–B2 definitions, regardless of auth
    # state or card creation.  A0 words have hardcoded A0-level definitions
    # (shown to A0 students) but still need LLM-generated A1–B2 ones.
    words_without_defs = [
        m.word
        for m in unique_words.values()
        if m.word.senses
        and not any(
            _cache.get_definition(str(m.word.id), lvl)
            for lvl in ("A1", "A2", "B1", "B2")
        )
    ]
    words_to_generate = [
        w for w in words_without_defs if str(w.id) not in _pending_def_gen
    ]
    if words_to_generate:
        _pending_def_gen.update(str(w.id) for w in words_to_generate)
        create_background_task(
            _generate_and_cache(words_to_generate),
            name=f"vocab-defs-{'-'.join(w.word for w in words_to_generate[:3])}",
        )

    # --- Annotation (HTML) ---
    student_level = await get_cefr_level(student_id) if student_id else "A1"
    anonymous = student_id is None
    owned_word_ids = existing_word_ids | (
        {w.id for w in new_words} if create_cards else set()
    )

    # Group matches by lemma for annotation.  When all matches for a lemma
    # point to the same dictionary entry, annotate all occurrences at once.
    # When they point to different entries (multi-POS), annotate one at a
    # time so each occurrence gets the correct entry's attributes.
    lemma_groups: dict[str, list[VocabMatch]] = {}
    for m in matches:
        lemma_groups.setdefault(m.lemma, []).append(m)

    for lemma, group in lemma_groups.items():
        word_ids_in_group = {str(m.word.id) for m in group}
        multi_pos = len(word_ids_in_group) > 1

        if not multi_pos:
            # Single dictionary entry — annotate all occurrences at once.
            m = group[0]
            word_id = str(m.word.id)
            wdef = _cache.get_definition(word_id, student_level)
            if wdef is None and student_level == "A0":
                wdef = _cache.get_definition(word_id, "A1")
            count = _annotate_in_elements(
                lang_elements,
                m.word,
                wdef,
                anonymous=anonymous,
                in_vocab=m.word.id in owned_word_ids,
                surface_forms=m.surface_forms,
            )
            logger.debug(
                "[discover] annotate %r (headword=%r, pos=%s, surfaces=%s, has_def=%s) → %d matches",
                m.lemma,
                m.word.word,
                m.word.part_of_speech,
                m.surface_forms,
                wdef is not None,
                count,
            )
        else:
            # Multi-POS: different dictionary entries for the same lemma.
            # Annotate each occurrence individually in document order so each
            # gets the correct entry's attributes and only its own surface form.
            all_occs: list[tuple[TokenOccurrence, VocabMatch]] = []
            for m in group:
                for occ in m.occurrences:
                    all_occs.append((occ, m))
            all_occs.sort(key=lambda x: x[0].index)

            for occ, m in all_occs:
                word_id = str(m.word.id)
                wdef = _cache.get_definition(word_id, student_level)
                if wdef is None and student_level == "A0":
                    wdef = _cache.get_definition(word_id, "A1")
                count = _annotate_in_elements(
                    lang_elements,
                    m.word,
                    wdef,
                    anonymous=anonymous,
                    in_vocab=m.word.id in owned_word_ids,
                    surface_forms=[occ.surface],
                    max_count=1,
                )
                logger.debug(
                    "[discover] annotate %r (headword=%r, pos=%s, surface=%r, has_def=%s, multi_pos=True) → %d matches",
                    m.lemma,
                    m.word.word,
                    m.word.part_of_speech,
                    occ.surface,
                    wdef is not None,
                    count,
                )

    return str(soup)


async def _generate_and_cache(words: list[VocabularyWord]) -> None:
    """Background task: generate CEFR-aware definitions and update the cache."""
    for word in words:
        word_id_str = str(word.id)
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
        finally:
            _pending_def_gen.discard(word_id_str)
