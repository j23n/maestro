"""
DWDS (Digitales Wörterbuch der deutschen Sprache) web page parser.

Fetches dictionary pages from dwds.de and extracts structured entries
analogous to what epub_parser produces for Italian.

Rate-limited to be polite to the DWDS servers.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup, Tag

from maestro.vocab.epub_parser import ParsedEntry, ParsedSense

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.dwds.de/wb"
HEADERS = {
    "User-Agent": "maestro-language-tutor/1.0 (language learning app; contact via github)"
}
_SEMAPHORE = asyncio.Semaphore(3)
_DELAY = 0.5  # seconds between requests


# ---------------------------------------------------------------------------
# POS extraction
# ---------------------------------------------------------------------------

# First word in the grammar block is the POS, e.g. "Substantiv (Neutrum)"
_POS_RE = re.compile(
    r"^(Substantiv|Verb|Adjektiv|Adverb|Pr[aä]position|Pronomen|Artikel"
    r"|Konjunktion|Interjektion|Numerale|Partikel|Affix)"
)

# Normalise DWDS POS terms to short abbreviations stored on VocabularyWord.
POS_ABBREV: dict[str, str] = {
    "Substantiv": "Subst.",
    "Verb": "V.",
    "Adjektiv": "Adj.",
    "Adverb": "Adv.",
    "Präposition": "Praep.",
    "Praeposition": "Praep.",
    "Pronomen": "Pron.",
    "Artikel": "Art.",
    "Konjunktion": "Konj.",
    "Interjektion": "Interj.",
    "Numerale": "Num.",
    "Partikel": "Part.",
    "Affix": "Affix",
}


def _extract_pos(artikel: Tag) -> str:
    """Extract abbreviated POS from a dwdswb-artikel container."""
    ft_blocks = artikel.find("div", class_="dwdswb-ft-blocks")
    if not ft_blocks:
        return ""
    first_block = ft_blocks.find("span", class_="dwdswb-ft-blocktext")
    if not first_block:
        return ""
    text = first_block.get_text(" ", strip=True)
    m = _POS_RE.match(text)
    if not m:
        return ""
    return POS_ABBREV.get(m.group(1), m.group(1))


# ---------------------------------------------------------------------------
# Sense extraction
# ---------------------------------------------------------------------------

_MAX_EXAMPLES = 3  # max examples per sense


def _extract_senses(artikel: Tag) -> list[ParsedSense]:
    """Extract senses from a dwdswb-artikel, flattening depth 0 + 1."""
    lesarten = artikel.find("div", class_="dwdswb-lesarten")
    if not lesarten:
        return []

    senses: list[ParsedSense] = []
    top_lesarts = lesarten.find_all("div", class_="dwdswb-lesart", recursive=False)

    for la in top_lesarts:
        defn_el = la.find("span", class_="dwdswb-definition")
        definition = defn_el.get_text(strip=True) if defn_el else ""

        content = la.find("div", class_="dwdswb-lesart-content")
        sub_lesarts = (
            content.find_all("div", class_="dwdswb-lesart", recursive=False)
            if content
            else []
        )

        if sub_lesarts:
            # Collect examples from sub-senses
            examples = _collect_examples(sub_lesarts)
        else:
            # Leaf sense — examples within content
            examples = _examples_from(content)[:_MAX_EXAMPLES] if content else []

        if definition:
            senses.append(ParsedSense(definition=definition, examples=examples))

    return senses


def _collect_examples(sub_lesarts: list[Tag]) -> list[str]:
    """Gather up to _MAX_EXAMPLES from a list of sub-lesart tags."""
    examples: list[str] = []
    for sub in sub_lesarts:
        if len(examples) >= _MAX_EXAMPLES:
            break
        for ex in _examples_from(sub):
            examples.append(ex)
            if len(examples) >= _MAX_EXAMPLES:
                break
    return examples


def _examples_from(container: Tag) -> list[str]:
    """Extract example texts from kompetenzbeispiel divs in a container.

    Examples live inside ``dwdswb-verwendungsbeispiele`` wrappers at varying
    depths, so we search the entire subtree.
    """
    examples: list[str] = []
    for ex_div in container.find_all("div", class_="dwdswb-kompetenzbeispiel"):
        text = ex_div.get_text(" ", strip=True)
        if text:
            examples.append(text)
    return examples


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_and_parse(
    word: str, *, client: httpx.AsyncClient | None = None
) -> list[ParsedEntry]:
    """Fetch the DWDS page for *word* and return parsed entries.

    Returns one ParsedEntry per homograph (e.g. Bank¹ bench vs Bank² bank).
    Returns ``[]`` on network/parse failure.

    Pass a shared *client* to avoid per-request connection overhead when
    enriching a batch of words.
    """
    url = f"{_BASE_URL}/{word}"
    async with _SEMAPHORE:
        try:
            if client is not None:
                resp = await client.get(url)
            else:
                async with httpx.AsyncClient(
                    headers=HEADERS, timeout=15, follow_redirects=True
                ) as _client:
                    resp = await _client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("DWDS fetch failed for %r: %s", word, exc)
            return []
        finally:
            await asyncio.sleep(_DELAY)

    return parse_html(resp.text, word)


def parse_html(html: str, word: str) -> list[ParsedEntry]:
    """Parse DWDS HTML into a list of ParsedEntry (one per homograph).

    Exposed as a standalone function for testing with saved HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    artikels = soup.find_all("div", class_="dwdswb-artikel")

    if not artikels:
        logger.debug("no dwdswb-artikel found for %r", word)
        return []

    entries: list[ParsedEntry] = []
    for i, art in enumerate(artikels):
        pos = _extract_pos(art)
        senses = _extract_senses(art)

        if not senses:
            logger.debug("no senses found for %r artikel %d", word, i)
            continue

        entries.append(
            ParsedEntry(
                entry_id=f"DWDS-{word}-{i}",
                headword=word,
                hyph=None,  # DWDS doesn't provide syllabization
                pos_abbrev=pos,
                senses=senses,
            )
        )

    return entries
