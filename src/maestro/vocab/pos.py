"""Coarse mapping from spaCy universal POS tags to EPUB dictionary POS prefixes."""

from __future__ import annotations

# spaCy universal POS → EPUB POS prefix(es)
UPOS_TO_EPUB: dict[str, tuple[str, ...]] = {
    "NOUN": ("s.",),  # s.m., s.f., s.m./f.
    "VERB": ("v.",),  # v.tr., v.intr., v.rifl., v.
    "ADJ": ("agg.",),
    "ADV": ("avv.",),
    "ADP": ("prep.",),
    "PRON": ("pron.",),
    "DET": ("art.",),
    "CCONJ": ("cong.",),
    "SCONJ": ("cong.",),
    "INTJ": ("inter.",),
    "NUM": ("num.",),
}


def matches_pos(epub_pos: str, spacy_pos: str) -> bool:
    """Check if an EPUB POS abbreviation matches a spaCy universal POS tag."""
    prefixes = UPOS_TO_EPUB.get(spacy_pos)
    if not prefixes:
        return False
    return any(epub_pos.startswith(p) for p in prefixes)
