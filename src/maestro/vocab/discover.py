"""Vocab annotation of rendered HTML from pre-verified mappings.

discover() wraps known dictionary words in popover spans and creates
UserVocabularyCards — driven exclusively by VocabAnnotation lists produced
at content-creation time (content banks or vocab.annotate's LLM post-pass)
and validated against the word index. The former runtime NLP pipeline
(spaCy lemmatization, simplemma fallback, elision repair) was removed: its
mis-lemmatizations were the source of polluted user vocabulary, and content
without verified annotations now simply renders unannotated.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from beanie import PydanticObjectId
from bs4 import BeautifulSoup, NavigableString, Tag
from bson import DBRef

from maestro.models import (
    Sense,
    VocabAnnotation,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.learning.profile import get_cefr_level
from maestro.utils import create_background_task, utcnow
from maestro.vocab.generate_definitions import generate_definitions_for_word
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


@dataclass
class TokenOccurrence:
    """A single token occurrence in the input text."""

    surface: str  # exact text as it appeared
    pos: str  # spaCy UPOS tag
    index: int  # position among kept tokens (document order)


@dataclass
class VocabMatch:
    """A single vocabulary match: one lemma resolved to one dictionary entry."""

    lemma: str  # dictionary headword the annotation resolved to
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

    word_id = "" if anonymous else str(word.id)

    return (
        f' class="vocab-word"'
        f' data-word="{word.word}"'
        f' data-pos="{word.part_of_speech or ""}"'
        f' data-syllabization="{word.syllabization or ""}"'
        f' data-ipa="{word.ipa or ""}"'
        f" data-senses='{senses_json}'"
        f' data-translation="{translation}"'
        f' data-word-id="{word_id}"'
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
    headword_ends_alnum = word.word and word.word[-1].isalnum()
    forms = {word.word.lower(): word.word}
    if surface_forms:
        for f in surface_forms:
            # Strip trailing apostrophes from elision artifacts (e.g. Dov' → Dov,
            # l' → l) when the headword itself ends in a word character.  Phrases
            # like "un po'" keep their apostrophe because the headword also ends
            # with it.
            if headword_ends_alnum and f and not f[-1].isalnum():
                f = f.rstrip("'")
                if not f:
                    continue
            key = f.lower()
            # Keep the longest form per lowercased key
            if key not in forms or len(f) > len(forms[key]):
                forms[key] = f

    alternatives = "|".join(re.escape(f) for f in forms.values())
    # Use lookaround boundaries instead of \b so phrases ending in non-word
    # characters (un po', come si chiama?) are matched correctly.
    pattern = re.compile(rf"(?<!\w)({alternatives})(?!\w)", re.IGNORECASE)
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


def matches_from_annotations(
    annotations: list[VocabAnnotation],
    *,
    language: str,
) -> list[VocabMatch]:
    """Resolve pre-verified annotations to dictionary entries — no NLP.

    Each annotation's lemma is looked up directly in the word index (or
    phrase index for multi-word lemmas); among multiple POS variants, the
    entry matching the annotation's UPOS wins. Unresolvable lemmas are
    skipped — they can never create cards.
    """
    word_idx = _cache.word_index(language)
    phrase_idx = _cache.phrase_index(language)

    matches: list[VocabMatch] = []
    seen: set[tuple[str, str]] = set()
    for i, ann in enumerate(annotations):
        key = ann.lemma.lower()
        entries = word_idx.get(key) or phrase_idx.get(key)
        if not entries:
            logger.debug("[discover] annotation lemma %r unresolved — skipped", key)
            continue
        if len(entries) == 1:
            word = entries[0]
        else:
            word = (
                next(
                    (
                        e
                        for e in entries
                        if matches_pos(e.part_of_speech, ann.upos, language)
                    ),
                    None,
                )
                or sorted(entries, key=lambda e: e.part_of_speech)[0]
            )
        dedup = (key, str(word.id))
        if dedup in seen:
            continue
        seen.add(dedup)
        matches.append(
            VocabMatch(
                lemma=key,
                word=word,
                occurrences=[
                    TokenOccurrence(surface=s, pos=ann.upos, index=i)
                    for s in ann.surface_forms
                ],
            )
        )
    return matches


async def discover(
    response_text: str,
    student_id: PydanticObjectId | None = None,
    message=None,
    create_cards: bool = True,
    *,
    language: str,
    annotations: list[VocabAnnotation] | None = None,
) -> str:
    """Annotate vocab words in rendered HTML and create user cards.

    Operates exclusively on pre-verified `annotations` (from content banks or
    the generation-time post-pass in vocab.annotate) — there is no runtime
    NLP matching, so only verified mappings can be annotated or create cards.
    Content without annotations is returned unchanged.
    """
    target_lang = language

    if not annotations:
        return response_text

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
            "[discover] scoped to <main>, found %d lang='%s' elements",
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

    all_text = get_target_text(lang_elements)
    matches = matches_from_annotations(annotations, language=target_lang)
    logger.debug(
        "[discover] pre-annotated: %d/%d mappings resolved",
        len(matches),
        len(annotations),
    )
    return await _finish_discover(
        soup,
        lang_elements=lang_elements,
        matches=matches,
        all_text=all_text,
        target_lang=target_lang,
        student_id=student_id,
        message=message,
        create_cards=create_cards,
    )


async def _finish_discover(
    soup,
    *,
    lang_elements: list,
    matches: list[VocabMatch],
    all_text: str,
    target_lang: str,
    student_id,
    message,
    create_cards: bool,
) -> str:
    """Shared tail of discover(): card creation, definition/audio generation,
    and HTML annotation of the resolved matches."""
    # Split into saveable (create cards) vs no-save (tooltip only) elements
    save_elements = [el for el in lang_elements if not el.has_attr("data-no-save")]
    nosave_elements = [el for el in lang_elements if el.has_attr("data-no-save")]

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
                UserVocabularyCard(
                    student_id=student_id, word=w, message=message, language=w.language
                )
                for w in new_words
            ]
        )

    # --- Definition generation (background) ---
    # For ANY discovered word missing A1–B2 definitions, regardless of auth
    # state or card creation.  A0 words have hardcoded A0-level definitions
    # (shown to A0 students) but still need LLM-generated A1–B2 ones.
    def _no_defs(w):
        return not any(
            _cache.get_definition(str(w.id), lvl, target_lang)
            for lvl in ("A1", "A2", "B1", "B2")
        )

    # Words WITH senses but no definitions → standard LLM rewrite path
    words_without_defs = [
        m.word for m in unique_words.values() if m.word.senses and _no_defs(m.word)
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

    # Words WITHOUT senses and no definitions → enrich from DWDS then generate.
    # Only German words go through this path — Italian words always have senses
    # from the EPUB dictionary.  An Italian word with empty senses is a data
    # issue, not something to send to DWDS.
    #
    # Include ALL word_index siblings (other POS variants under the same
    # lowercase key) that also lack senses, not just the single matched entry.
    # This ensures every POS variant gets enriched so that future POS
    # disambiguation works correctly.
    _seen_enrich_ids: set[str] = set()
    words_needing_enrichment: list[VocabularyWord] = []
    for m in unique_words.values():
        if (
            not m.word.senses
            and _no_defs(m.word)
            and getattr(m.word, "language", "") == "de"
        ):
            # Add the matched word itself
            wid = str(m.word.id)
            if wid not in _seen_enrich_ids:
                _seen_enrich_ids.add(wid)
                words_needing_enrichment.append(m.word)
            # Also add unenriched siblings from the same word_index key
            siblings = _cache.word_index(target_lang).get(m.lemma, [])
            for sib in siblings:
                sid = str(sib.id)
                if sid not in _seen_enrich_ids and not sib.senses and _no_defs(sib):
                    _seen_enrich_ids.add(sid)
                    words_needing_enrichment.append(sib)
    words_to_enrich = [
        w for w in words_needing_enrichment if str(w.id) not in _pending_def_gen
    ]
    if words_to_enrich:
        _pending_def_gen.update(str(w.id) for w in words_to_enrich)
        create_background_task(
            _enrich_and_generate(words_to_enrich),
            name=f"vocab-enrich-{'-'.join(w.word for w in words_to_enrich[:3])}",
        )

    # --- Audio generation (background, parallel to defs) ---
    words_missing_audio = [
        m.word for m in unique_words.values() if m.word.audio_url is None
    ]
    if words_missing_audio:
        create_background_task(
            _generate_missing_audio(words_missing_audio),
            name=f"vocab-audio-{'-'.join(w.word for w in words_missing_audio[:3])}",
        )

    # --- Annotation (HTML) ---
    student_level = await get_cefr_level(student_id) if student_id else "A1"
    anonymous = student_id is None
    owned_word_ids = existing_word_ids | (
        {w.id for w in new_words} if create_cards else set()
    )

    # Annotate multi-word (phrase) matches FIRST so their spans block
    # per-word annotation inside phrases (text nodes inside vocab-word spans
    # are skipped). Longest first so longer phrases win overlaps.
    phrase_matches = sorted(
        (m for m in matches if " " in m.lemma),
        key=lambda m: len(m.word.word),
        reverse=True,
    )
    word_matches = [m for m in matches if " " not in m.lemma]
    for m in phrase_matches:
        word_id = str(m.word.id)
        wdef = _cache.get_definition(word_id, student_level, target_lang)
        count = _annotate_in_elements(
            lang_elements,
            m.word,
            wdef,
            anonymous=anonymous,
            in_vocab=m.word.id in owned_word_ids,
            surface_forms=m.surface_forms,
        )
        logger.debug(
            "[discover] annotate phrase %r (headword=%r, pos=%s, has_def=%s) → %d matches",
            m.lemma,
            m.word.word,
            m.word.part_of_speech,
            wdef is not None,
            count,
        )

    # Group matches by lemma for annotation.  When all matches for a lemma
    # point to the same dictionary entry, annotate all occurrences at once.
    # When they point to different entries (multi-POS), annotate one at a
    # time so each occurrence gets the correct entry's attributes.
    lemma_groups: dict[str, list[VocabMatch]] = {}
    for m in word_matches:
        lemma_groups.setdefault(m.lemma, []).append(m)

    for lemma, group in lemma_groups.items():
        word_ids_in_group = {str(m.word.id) for m in group}
        multi_pos = len(word_ids_in_group) > 1

        if not multi_pos:
            # Single dictionary entry — annotate all occurrences at once.
            m = group[0]
            word_id = str(m.word.id)
            wdef = _cache.get_definition(word_id, student_level, target_lang)
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
                wdef = _cache.get_definition(word_id, student_level, target_lang)
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


async def _generate_missing_audio(words: list[VocabularyWord]) -> None:
    """Background task: generate missing word audio via Azure TTS."""
    from maestro.tts import generate_word_audio

    for word in words:
        try:
            await generate_word_audio(word.word, language=word.language)
        except Exception as exc:
            logger.warning(
                "[discover] audio generation failed for '%s': %s", word.word, exc
            )


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
                _cache.set_definition(str(word.id), d.student_level, d, word.language)
            logger.info(
                f"[discover] generated {len(defs)} definition(s) for '{word.word}'"
            )
        except Exception as exc:
            logger.warning(
                f"[discover] definition generation failed for '{word.word}': {exc}"
            )
        finally:
            _pending_def_gen.discard(word_id_str)


async def _enrich_and_generate(words: list[VocabularyWord]) -> None:
    """Background task: fetch DWDS page, populate senses, then generate defs.

    Used for German bare VocabularyWord docs that were ingested from the DWDS
    headwords JSON without senses.  Fetches the DWDS web page for each word,
    parses definitions/examples, saves senses to the VocabularyWord, then
    runs the standard LLM definition generation pipeline.
    """
    import httpx

    from maestro.vocab.dwds_parser import HEADERS as _DWDS_HEADERS
    from maestro.vocab.dwds_parser import fetch_and_parse

    async with httpx.AsyncClient(
        headers=_DWDS_HEADERS, timeout=15, follow_redirects=True
    ) as client:
        for word in words:
            word_id_str = str(word.id)
            try:
                entries = await fetch_and_parse(word.word, client=client)
                if not entries:
                    logger.info(
                        "[discover] DWDS returned no entries for '%s', skipping",
                        word.word,
                    )
                    continue

                # Merge senses from all homograph entries that share this word's
                # POS.  E.g. "Bank" has two Subst. articles (bench vs.
                # institution) — both map to the same VocabularyWord doc, so we
                # combine their senses.
                word.senses = [
                    Sense(definition=s.definition, examples=s.examples)
                    for entry in entries
                    for s in entry.senses
                    if s.definition
                ]
                if not word.part_of_speech and entries[0].pos_abbrev:
                    word.part_of_speech = entries[0].pos_abbrev
                word.updated_at = utcnow()
                await word.save()
                logger.info(
                    "[discover] enriched '%s' from DWDS: %d senses, POS=%s",
                    word.word,
                    len(word.senses),
                    word.part_of_speech,
                )

                # Now generate CEFR definitions using the enriched senses
                await generate_definitions_for_word(word)
                defs = await VocabularyWordDefinition.find(
                    {"word": DBRef(VocabularyWord.Settings.name, word.id)}
                ).to_list()
                for d in defs:
                    _cache.set_definition(
                        str(word.id), d.student_level, d, word.language
                    )
                logger.info(
                    "[discover] generated %d definition(s) for '%s'",
                    len(defs),
                    word.word,
                )
            except Exception as exc:
                logger.warning(
                    "[discover] enrich+generate failed for '%s': %s", word.word, exc
                )
            finally:
                _pending_def_gen.discard(word_id_str)
