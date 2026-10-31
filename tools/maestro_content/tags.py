"""Mapping from source morphology tags to our form tags (HANDOFF.md 6.5).

Form tags: mood.tense[.person][+aux]. Gender-number for nouns and adjectives: ms fs mp fp.
The build fails on a verb form whose tags can't be mapped (unmapped() lists them).
"""

from __future__ import annotations

MOODS = {"ind", "sub", "cond", "imp", "inf", "ger", "part"}
TENSES = {"pres", "impf", "prem", "fut", "pp", "tpp", "tpr", "futa", "pass", "neg"}
PERSONS = {"1s", "2s", "3s", "1p", "2p", "3p"}
FINITE = {"ind", "sub", "cond", "imp"}


def is_valid(tag: str) -> bool:
    core, _, aux = tag.partition("+")
    if aux and aux not in ("e", "a"):
        return False
    parts = core.split(".")
    if len(parts) not in (2, 3) or parts[0] not in MOODS or parts[1] not in TENSES:
        return False
    if parts[0] in FINITE:
        return len(parts) == 3 and parts[2] in PERSONS
    return len(parts) == 2


# --- kaikki / wiktextract ---------------------------------------------------------------

_K_PERSON = {"first-person": "1", "second-person": "2", "third-person": "3"}
_K_NUMBER = {"singular": "s", "plural": "p"}
# Forms carrying any of these are compound or periphrastic tenses, which the app generates.
_K_SKIP = {"perfect", "pluperfect", "anterior", "multiword-construction", "compound", "progressive"}
_K_IGNORE = {"canonical", "romanization", "table-tags", "inflection-template", "class", "auxiliary"}


def kaikki_form_tag(tags: list[str]) -> str | None:
    """Our form tag for a kaikki verb form, or None when it isn't a simple verb form we keep."""
    t = set(tags)
    if t & _K_SKIP or t & _K_IGNORE:
        return None
    person = next((_K_PERSON[x] for x in t if x in _K_PERSON), None)
    number = next((_K_NUMBER[x] for x in t if x in _K_NUMBER), None)
    pn = f".{person}{number}" if person and number else None

    if "infinitive" in t:
        return "inf.pres"
    if "gerund" in t:
        return "ger.pres"
    if "participle" in t:
        if "past" in t:
            return "part.pass"
        if "present" in t:
            return "part.pres"
        return None
    if "imperative" in t:
        if "negative" in t:
            return "imp.neg.2s" if pn == ".2s" else None
        return f"imp.pres{pn}" if pn and pn != ".1s" else None
    if "conditional" in t:
        return f"cond.pres{pn}" if pn else None
    if "subjunctive" in t:
        if "imperfect" in t:
            return f"sub.impf{pn}" if pn else None
        if "present" in t or not (t & {"past", "imperfect"}):
            return f"sub.pres{pn}" if pn else None
        return None
    if "indicative" in t or t & {"present", "imperfect", "future", "historic"}:
        if not pn:
            return None
        if "historic" in t or ("past" in t and "imperfect" not in t):
            return f"ind.prem{pn}"
        if "imperfect" in t:
            return f"ind.impf{pn}"
        if "future" in t:
            return f"ind.fut{pn}"
        if "present" in t:
            return f"ind.pres{pn}"
    return None


def kaikki_gender_number(tags: list[str]) -> str | None:
    t = set(tags)
    g = "m" if "masculine" in t else "f" if "feminine" in t else None
    n = "s" if "singular" in t else "p" if "plural" in t else None
    if g and n:
        return g + n
    return None


# --- Morph-it! -----------------------------------------------------------------------------
# Morph-it! writes passato remoto as ind+past, which must become ind.prem, never a compound tense.

_M_MOOD = {"ind": "ind", "sub": "sub", "cond": "cond", "impr": "imp", "inf": "inf", "ger": "ger", "part": "part"}
_M_TENSE = {"pres": "pres", "impf": "impf", "past": "prem", "fut": "fut"}


def morphit_tag(analysis: str) -> str | None:
    """Our tag for a Morph-it! analysis such as VER:ind+pres+1+s, or None to skip the line."""
    cat, _, feats = analysis.partition(":")
    if "-cli" in cat or "-cli" in feats:
        return None  # forms with attached clitics; the app splits clitics itself
    parts = feats.split("+") if feats else []
    if cat.startswith(("VER", "AUX", "MOD", "CAU", "ASP")):
        if len(parts) < 2 or parts[0] not in _M_MOOD:
            return None
        mood, tense = _M_MOOD[parts[0]], parts[1]
        if mood == "part":
            return "part.pass" if tense == "past" else "part.pres" if tense == "pres" else None
        if mood in ("inf", "ger"):
            return f"{mood}.pres" if tense == "pres" else None
        if len(parts) < 4 or tense not in _M_TENSE:
            return None
        pn = f"{parts[2]}{parts[3]}"
        if pn not in PERSONS:
            return None
        if mood == "ind":
            return f"ind.{_M_TENSE[tense]}.{pn}"
        if mood == "imp":
            return f"imp.pres.{pn}" if tense == "pres" else None
        if mood == "cond":
            return f"cond.pres.{pn}" if tense == "pres" else None
        if mood == "sub":
            return f"sub.{_M_TENSE[tense]}.{pn}" if tense in ("pres", "impf") else None
        return None
    if cat.startswith(("NOUN", "ADJ", "ART", "DET", "PRO")):
        gender = None
        if cat.endswith("-M"):
            gender = "m"
        elif cat.endswith("-F"):
            gender = "f"
        number = None
        for p in parts:
            if p in ("m", "f"):
                gender = gender or p
            elif p in ("s", "p"):
                number = p
        if gender and number:
            return gender + number
        return ""
    return ""


def morphit_pos(analysis: str) -> str | None:
    cat = analysis.partition(":")[0]
    for prefix, pos in (("VER", "v"), ("AUX", "v"), ("MOD", "v"), ("CAU", "v"), ("ASP", "v"),
                        ("NOUN", "n"), ("ADJ", "adj"), ("ADV", "adv"), ("ART", "art"), ("DET", "det"),
                        ("PRE", "prep"), ("CON", "conj"), ("PRO", "pron"), ("NPR", "propn"), ("INT", "intj"),
                        ("CARD", "num"), ("NUM", "num")):
        if cat.startswith(prefix):
            return pos
    return None
