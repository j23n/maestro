"""Coarse mapping from spaCy universal POS tags to dictionary POS prefixes."""

from __future__ import annotations

from maestro.language import DEFAULT_LANGUAGE

# ---------------------------------------------------------------------------
# Italian: EPUB dictionary POS abbreviations
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# German: DWDS dictionary POS abbreviations
# ---------------------------------------------------------------------------
UPOS_TO_DWDS: dict[str, tuple[str, ...]] = {
    "NOUN": ("Subst.",),
    "VERB": ("V.",),
    "AUX": ("V.",),
    "ADJ": ("Adj.",),
    "ADV": ("Adv.",),
    "ADP": ("Praep.",),
    "PRON": ("Pron.",),
    "DET": ("Art.", "Adj."),
    "CCONJ": ("Konj.",),
    "SCONJ": ("Konj.",),
    "INTJ": ("Interj.",),
    "NUM": ("Num.",),
}

_LANG_TO_MAP: dict[str, dict[str, tuple[str, ...]]] = {
    "it": UPOS_TO_EPUB,
    "de": UPOS_TO_DWDS,
}


def matches_pos(dict_pos: str, spacy_pos: str, language: str | None = None) -> bool:
    """Check if a dictionary POS abbreviation matches a spaCy universal POS tag."""
    mapping = _LANG_TO_MAP.get(language or DEFAULT_LANGUAGE, UPOS_TO_EPUB)
    prefixes = mapping.get(spacy_pos)
    if not prefixes:
        return False
    return any(dict_pos.startswith(p) for p in prefixes)
