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


# --- German (HANDOFF.md 6.5, "German form tags") -------------------------------------------
# Verb forms: mood.tense[.person][+aux], German codes. Nouns, adjectives, articles and pronouns get a
# case tag instead: [comp.|sup.][decl.]case[.gn], such as gen.ns (Hauses), dat.pl (Häusern),
# str.nom.ms (guter), wk.dat.fs (guten); comp and sup alone are the bare comparative and superlative.

DE_MOODS = {"ind", "k1", "k2", "imp", "inf", "part"}
DE_TENSES = {"pres", "prat", "perf", "pqp", "fut1", "fut2", "wuerde", "zu", "pass"}
DE_FINITE = {"ind", "k1", "k2", "imp"}
DE_CASES = {"nom", "acc", "dat", "gen"}
DE_GN = {"ms", "fs", "ns", "pl"}
DE_DECL = {"str", "wk", "mix"}


def is_valid_de(tag: str) -> bool:
    """True for a German verb form tag (ind.prat.1s, inf.zu, ind.perf.3s+s)."""
    core, _, aux = tag.partition("+")
    if aux and aux not in ("h", "s"):
        return False
    parts = core.split(".")
    if len(parts) not in (2, 3) or parts[0] not in DE_MOODS or parts[1] not in DE_TENSES:
        return False
    mood, tense = parts[0], parts[1]
    if mood == "inf":
        return len(parts) == 2 and tense in ("pres", "zu", "perf")
    if mood == "part":
        return len(parts) == 2 and tense in ("pres", "pass")
    if tense in ("zu", "pass") or (tense == "wuerde" and mood != "k2"):
        return False
    if mood == "imp":
        return len(parts) == 3 and tense == "pres" and parts[2] in ("2s", "1p", "2p", "3p")
    return len(parts) == 3 and parts[2] in PERSONS


def is_valid_de_case(tag: str) -> bool:
    """True for a German case tag (gen.ns, str.nom.ms, comp, comp.wk.dat.pl, acc)."""
    parts = tag.split(".")
    if parts[0] in ("comp", "sup"):
        parts = parts[1:]
        if not parts:
            return True
    if parts and parts[0] in DE_DECL:
        parts = parts[1:]
    if not parts or parts[0] not in DE_CASES:
        return False
    return len(parts) == 1 or (len(parts) == 2 and parts[1] in DE_GN)


_DE_PERSON = {"first-person": "1", "second-person": "2", "third-person": "3"}
_DE_CASE = {"nominative": "nom", "accusative": "acc", "dative": "dat", "genitive": "gen"}
_DE_DECL = {"strong": "str", "weak": "wk", "mixed": "mix"}
_DE_GENDER = {"masculine": "m", "feminine": "f", "neuter": "n"}
# Compound and periphrastic forms (bin gegangen, werde gehen, würde gehen): the app builds them.
_DE_SKIP = {"perfect", "pluperfect", "future", "future-i", "future-ii", "multiword-construction", "passive",
            "progressive", "compound"}
# Tags that never change which form this is.
_DE_IGNORE_VERB = {"subordinate-clause", "dependent", "main-clause", "error-unknown-tag", "colloquial",
                   "archaic", "rare", "dated", "nonstandard", "regional"}


def kaikki_verb_tags_de(tags: list[str]) -> list[str]:
    """Our form tags for a kaikki German verb form; empty when it isn't a simple form we keep.

    One source row can name several persons (gehen is 1p and 3p), so this returns every tag it covers."""
    t = set(tags) - _DE_IGNORE_VERB
    if t & _DE_SKIP or "auxiliary" in t or "canonical" in t or "table-tags" in t or "inflection-template" in t:
        return []
    persons = sorted(_DE_PERSON[x] for x in t if x in _DE_PERSON)
    numbers = [n for x, n in (("singular", "s"), ("plural", "p")) if x in t]

    if "infinitive" in t or "zu-infinitive" in t:
        return ["inf.zu"] if ("zu" in t or "zu-infinitive" in t) else ["inf.pres"]
    if "participle" in t:
        if "past" in t or "perfect" in t:
            return ["part.pass"]
        if "present" in t:
            return ["part.pres"]
        return []
    if "imperative" in t:
        if persons and persons != ["2"]:
            return []
        return [f"imp.pres.2{n}" for n in numbers]
    if not persons or not numbers:
        return []
    tense = "prat" if t & {"past", "preterite", "imperfect"} else "pres"
    if "subjunctive-ii" in t:
        mood = "k2"
        tense = "prat"
    elif "subjunctive-i" in t or "subjunctive" in t:
        mood = "k1"
        tense = "pres"
    else:
        mood = "ind"
    return [f"{mood}.{tense}.{p}{n}" for p in persons for n in numbers]


_DE_IGNORE_NOMINAL = {"error-unknown-tag", "archaic", "rare", "dated", "colloquial", "nonstandard", "regional",
                      "predicative", "attributive", "table-tags", "inflection-template", "class"}
_DE_NOT_A_FORM = {"diminutive", "augmentative", "feminine-equivalent", "masculine-equivalent", "abbreviation",
                  "canonical", "romanization", "article", "definite", "indefinite", "adverbial", "alternative"}


def kaikki_case_tags_de(tags: list[str], gender: str | None = None, pos: str = "n") -> list[str]:
    """Our case tags for a kaikki German noun, adjective, article or pronoun form; empty to skip it.

    A noun's singular forms take the lemma's gender (gen.ns); plurals have none (dat.pl). With gender "?"
    (a form-of entry, which doesn't know its lemma's gender) a singular gets "s" (gen.s). One row can name
    several cases (nominative/accusative/genitive plural), so this returns every tag it covers."""
    t = set(tags) - _DE_IGNORE_NOMINAL
    if t & _DE_NOT_A_FORM:
        return []
    degree = "comp." if "comparative" in t else "sup." if "superlative" in t else ""
    cases = [c for x, c in _DE_CASE.items() if x in t]
    decl = next((d for x, d in _DE_DECL.items() if x in t), None)
    if not cases:
        if degree and len(t - {"comparative", "superlative"}) == 0:
            return [degree[:-1]]
        return []
    if pos == "n" and decl:
        decl = None  # strong and weak describe the noun's class, not this form
    genders = [g for x, g in _DE_GENDER.items() if x in t]
    if pos == "n" and "feminine" in t and gender != "f":
        return []  # a female-equivalent listed among a masculine noun's forms
    gns: list[str] = []
    if "plural" in t:
        gns.append("pl")
    if "singular" in t or (genders and "plural" not in t):
        if pos == "n":
            g = (gender or "")[:1]
            if g in ("m", "f", "n"):
                gns.append(g + "s")
            elif gender == "?":
                gns.append("s")  # a form-of entry: build_db fills in the lemma's gender
        else:
            gns.extend(g + "s" for g in genders)
    if not gns and pos == "n":
        return []
    prefix = degree + (decl + "." if decl and pos == "adj" else "")
    if not gns:
        return [f"{prefix}{c}" for c in cases]
    return [f"{prefix}{c}.{gn}" for c in cases for gn in gns]
