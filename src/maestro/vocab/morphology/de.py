"""German-specific morphology for vocabulary lookup."""

from __future__ import annotations

import simplemma


def make_lookup(by_form: dict, nlp):
    """
    Return a lookup(word) callable that searches the headword index using:

    1. Direct form match (exact headword).
    2. spaCy lemma lookup.
    3. simplemma fallback (catches cases where spaCy's lemmatizer misses).

    German morphology is simpler than Italian — no clitic/enclitic handling
    needed.  Compound noun decomposition is deferred to a future iteration;
    spaCy's German model handles most common cases.

    by_form maps headword → list[ParsedEntry] (one per POS variant).
    Returns list[ParsedEntry] for the matched headword, or None.
    """
    by_lemma: dict[str, list[object]] = {}
    forms = list(by_form.keys())
    for form, doc in zip(forms, nlp.pipe(forms, disable=["parser", "senter", "ner"])):
        by_lemma.setdefault(doc[0].lemma_.lower(), by_form[form])

    def _lookup(word: str):
        # 1. Direct form match
        if word in by_form:
            return by_form[word]

        # 2. spaCy lemma
        spacy_lemma = nlp(word)[0].lemma_.lower()
        if spacy_lemma in by_form:
            return by_form[spacy_lemma]
        hit = by_lemma.get(spacy_lemma)
        if hit:
            return hit

        # 3. simplemma fallback
        sm_lemma = simplemma.lemmatize(word, lang="de").lower()
        if sm_lemma != spacy_lemma:
            if sm_lemma in by_form:
                return by_form[sm_lemma]
            hit = by_lemma.get(sm_lemma)
            if hit:
                return hit

        return None

    return _lookup


# No CEFR wordlist source for German yet — LLM classifies level on demand.
WORDLISTS: list[tuple[str, str]] = []

# DWDS POS terms → short abbreviations (from dwds_parser.POS_ABBREV).
POS_MAP: dict[str, str] = {
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
}
