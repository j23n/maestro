"""Coarse mapping from spaCy universal POS tags to EPUB dictionary POS prefixes."""

from __future__ import annotations

# spaCy universal POS → EPUB POS prefix(es)
#
# The EPUB dictionary uses Italian abbreviations (s.m., v.tr., agg., etc.)
# while spaCy uses Universal Dependencies POS tags (NOUN, VERB, ADJ, etc.).
# Each spaCy tag maps to one or more EPUB prefixes checked via startswith().
UPOS_TO_EPUB: dict[str, tuple[str, ...]] = {
    "NOUN": ("s.",),  # s.m., s.f., s.m.f., s.m.invar., …
    "VERB": ("v.",),  # v.tr., v.intr., v.pr., v.tr.e.v.intr., …
    "AUX": ("v.",),  # essere/avere as auxiliaries → same verb entries
    "ADJ": ("agg.",),  # agg., agg.invar., agg.e.s.m., …
    "ADV": ("avv.",),  # avv., avv.e.agg.invar., …
    "ADP": ("prep.",),  # prep., prep. articolata, prep.articolata
    "PRON": ("pronome",),  # pronome pers., pronome indef., pronome rel., …
    "DET": ("art.", "agg."),  # art.determ. + agg.dimostr., agg.poss., agg.indef., …
    "CCONJ": ("cong.",),  # congiunz.
    "SCONJ": ("cong.",),  # congiunz.
    "INTJ": ("inter.",),  # inter., inter.e.s.m.invar.
    "NUM": ("agg.num.", "num."),  # agg.num.card., agg.num.ord., …
}


def matches_pos(epub_pos: str, spacy_pos: str) -> bool:
    """Check if an EPUB POS abbreviation matches a spaCy universal POS tag."""
    prefixes = UPOS_TO_EPUB.get(spacy_pos)
    if not prefixes:
        return False
    return any(epub_pos.startswith(p) for p in prefixes)
