"""Italian-specific morphology: clitic/reflexive handling for vocab lookup."""
from __future__ import annotations

import re

# Compiled once at module level
_CLITIC_TRAILING_RE = re.compile(r"(\s+(si|ci|ne|lo|la|li|le|se|mi|ti|vi))+$")
_CLITIC_SUFFIX_RE = re.compile(
    r"r(si|sela|sele|sene|seli|ci|cela|celo|cene|ne|la|lo|li|le|mi|ti|vi)$"
)


def make_lookup(by_form: dict, nlp):
    """
    Return a lookup(word) callable that searches the EPUB index using:

    1. Direct form match against EPUB headwords.
    2. spaCy lemma — md model gives e.g. "alzare si" for reflexives;
       strip trailing clitic words (" si", " se ne" ...) -> clean lemma.
    3. Regex stripping of enclitic pronoun clusters from the original word
       (handles cavarsela, farcela, prendersela, andarsene ...).
    4. Adverbs in -mente: derive the base adjective and try variants.
    """
    by_lemma: dict[str, object] = {}
    forms = list(by_form.keys())
    for form, doc in zip(forms, nlp.pipe(forms, disable=["parser", "senter", "ner"])):
        by_lemma.setdefault(doc[0].lemma_.lower(), by_form[form])

    def _lookup(word: str):
        # 1. Direct form
        if word in by_form:
            return by_form[word]

        # 2. spaCy lemma with trailing clitics stripped
        spacy_lemma = nlp(word)[0].lemma_.lower()
        clean_lemma = _CLITIC_TRAILING_RE.sub("", spacy_lemma).strip()
        for candidate in dict.fromkeys([spacy_lemma, clean_lemma]):
            if candidate in by_form:
                return by_form[candidate]
            hit = by_lemma.get(candidate)
            if hit:
                return hit

        # 3. Enclitic pronoun cluster on infinitive stem
        m = _CLITIC_SUFFIX_RE.search(word)
        if m:
            base = word[: m.start()] + "re"
            if base in by_form:
                return by_form[base]
            hit = by_lemma.get(nlp(base)[0].lemma_.lower())
            if hit:
                return hit

        # 4. Adverbs in -mente -> derive base adjective
        if word.endswith("mente") and len(word) > 8:
            stem = word[:-5]
            candidates = [stem]
            if stem.endswith(("l", "r")):
                candidates.append(stem + "e")       # "cordial" -> "cordiale"
            elif stem.endswith("a"):
                candidates.append(stem[:-1] + "o")  # "lenta" -> "lento"
            elif stem.endswith("i"):
                candidates.append(stem[:-1] + "e")  # "felici" -> "felice"
            for v in candidates:
                if v in by_form:
                    return by_form[v]
                hit = by_lemma.get(nlp(v)[0].lemma_.lower())
                if hit:
                    return hit

        return None

    return _lookup


# Italian-specific wordlist sources and POS mapping
WORDLISTS = [
    ("A1", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a1.html"),
    ("A2", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a2.html"),
    ("B1", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b1.html"),
    ("B2", "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b2.html"),
]

# UniStraPG POS abbreviations -> keep raw for consistency with EPUB
POS_MAP = {
    "v.t.": "v.tr.",
    "v. t.": "v.tr.",
    "v.int.": "v.intr.",
    "v. int.": "v.intr.",
    "v.": "v.",
    "s.m.": "s.m.",
    "s.f.": "s.f.",
    "s.m./f.": "s.m./f.",
    "agg.": "agg.",
    "avv.": "avv.",
    "prep.": "prep.",
    "pron.": "pron.",
    "art.": "art.",
    "cong.": "cong.",
    "inter.": "inter.",
    "num.": "num.",
}
