"""German practice drills (HANDOFF.md 3.9): the recipes drills.generate uses for a German text.

    aux          Perfekt: pick haben or sein                         (choice)
    participle   Perfekt: type the participle                        (gap)
    participles  every Perfekt in the text: verb -> participle       (match)
    form         simple tense: pick the form, or type it             (choice | gap)
    case         an article or possessive in the case its phrase needs (choice)
    contraction  im or ins, am or ans, zum or zur                    (choice)
    particle     a separable verb's particle at the end of the clause (gap)
    order        the sentence's words in order                       (build)

Hints and rules are in English and name German forms in German, like the grammar pages.
"""

from __future__ import annotations

from .drills import (BUILD_WORDS, Candidate, Forms, TopicInfo, _gap, _neutral, _seed, form_key, form_person,
                     headword, match_case)
from .normalize import german_key
from .packs_de import VERB_LAST_TOPIC_WORDS

FORM_TOPIC = {
    "ind.pres": "de:praesens", "imp.pres": "de:imperativ", "ind.prat": "de:praeteritum",
    "k2.prat": "de:konjunktiv-2", "ind.perf": "de:perfekt", "k2.wuerde": "de:konjunktiv-2", "k2.pqp": "de:konjunktiv-2",
}
COMPOUND_TENSES = {"ind.perf", "ind.pqp", "k2.pqp"}
COMPOUND_TOPICS = {"de:perfekt"}
TENSE_LABEL = {"ind.pres": "Präsens", "ind.prat": "Präteritum", "k2.prat": "Konjunktiv II", "k1.pres": "Konjunktiv I",
               "imp.pres": "Imperativ"}
PERSONS = ["1s", "2s", "3s", "1p", "2p", "3p"]
PERSON_LABEL = {"1s": "ich", "2s": "du", "3s": "er, sie, es", "1p": "wir", "2p": "ihr", "3p": "sie, Sie"}
MODALS = {"können", "müssen", "wollen", "sollen", "dürfen", "mögen", "möchten"}

AUX_FORMS = {
    "haben": {"ind.pres": ["habe", "hast", "hat", "haben", "habt", "haben"],
              "ind.prat": ["hatte", "hattest", "hatte", "hatten", "hattet", "hatten"],
              "k2.prat": ["hätte", "hättest", "hätte", "hätten", "hättet", "hätten"]},
    "sein": {"ind.pres": ["bin", "bist", "ist", "sind", "seid", "sind"],
             "ind.prat": ["war", "warst", "war", "waren", "wart", "waren"],
             "k2.prat": ["wäre", "wärst", "wäre", "wären", "wärt", "wären"]},
}

CASE_NAME = {"nom": "nominative", "acc": "accusative", "dat": "dative", "gen": "genitive"}
CASE_TOPIC = {"acc": "de:akkusativ", "dat": "de:dativ", "nom": "de:artikel"}
CASE_ORDER = ("nom", "acc", "dat", "gen")
DEFINITE = {
    "ms": {"nom": "der", "acc": "den", "dat": "dem", "gen": "des"},
    "fs": {"nom": "die", "acc": "die", "dat": "der", "gen": "der"},
    "ns": {"nom": "das", "acc": "das", "dat": "dem", "gen": "des"},
    "pl": {"nom": "die", "acc": "die", "dat": "den", "gen": "der"},
}
EIN_ENDING = {
    "ms": {"nom": "", "acc": "en", "dat": "em", "gen": "es"},
    "fs": {"nom": "e", "acc": "e", "dat": "er", "gen": "er"},
    "ns": {"nom": "", "acc": "", "dat": "em", "gen": "es"},
    "pl": {"nom": "e", "acc": "e", "dat": "en", "gen": "er"},
}
DER_ENDING = {
    "ms": {"nom": "er", "acc": "en", "dat": "em", "gen": "es"},
    "fs": {"nom": "e", "acc": "e", "dat": "er", "gen": "er"},
    "ns": {"nom": "es", "acc": "es", "dat": "em", "gen": "es"},
    "pl": {"nom": "e", "acc": "e", "dat": "en", "gen": "er"},
}
EIN_STEMS = {"ein": "ein", "kein": "kein", "mein": "mein", "dein": "dein", "sein": "sein", "ihr": "ihr",
             "unser": "unser", "euer": "eur"}
DER_STEMS = {"dieser": "dies", "jeder": "jed", "welcher": "welch", "jener": "jen", "mancher": "manch"}
POSSESSIVES = {"mein", "dein", "sein", "ihr", "unser", "euer"}
# Contraction -> (preposition, the other contraction of the same preposition)
CONTRACTION_PAIRS = {"im": ("in", "ins"), "ins": ("in", "im"), "am": ("an", "ans"), "ans": ("an", "am"),
                     "zum": ("zu", "zur"), "zur": ("zu", "zum")}
CONTRACTION_WHY = {
    "im": "im = in dem: a place (wo?), dative.", "ins": "ins = in das: a direction (wohin?), accusative.",
    "am": "am = an dem: a place or a day (wo? wann?), dative.", "ans": "ans = an das: a direction (wohin?), accusative.",
    "zum": "zum = zu dem: for a masculine or neuter noun.", "zur": "zur = zu der: for a feminine noun.",
}
TWO_WAY = {"an", "auf", "hinter", "in", "neben", "über", "unter", "vor", "zwischen"}
NO_GE = ("be", "emp", "ent", "er", "ge", "miss", "ver", "zer")
PARTICLES = {"ab", "an", "auf", "aus", "bei", "ein", "fest", "fort", "her", "hin", "los", "mit", "nach", "vor", "weg",
             "zu", "zurück", "zusammen", "weiter", "vorbei", "herein", "hinaus", "heraus", "hinein", "kennen"}


# --- helpers -----------------------------------------------------------------------------

def weak_participle(infinitive: str) -> str | None:
    """The participle a regular (weak) verb would have: machen -> gemacht, anrufen -> angeruft."""
    stem = infinitive[:-2] if infinitive.endswith("en") else infinitive[:-1] if infinitive.endswith("n") else None
    if not stem:
        return None
    particle = next((p for p in sorted(PARTICLES, key=len, reverse=True)
                     if stem.startswith(p) and len(stem) > len(p) + 2), "")
    rest = stem[len(particle):]
    ending = "et" if rest.endswith(("t", "d")) else "t"
    inseparable = any(rest.startswith(p) and len(rest) > len(p) + 2 for p in NO_GE)
    if rest.endswith("ier") or inseparable:
        return particle + rest + ending
    return particle + "ge" + rest + ending


def is_irregular_participle(infinitive: str, participle: str) -> bool:
    """A participle is irregular when it doesn't end in t or doesn't hold the infinitive's stem:
    gegangen, gebracht (bring), gekannt (kenn). geöffnet, geantwortet, wiederholt and eingekauft are regular."""
    inf, part = infinitive.lower(), participle.lower()
    stem = inf[:-2] if inf.endswith("en") else inf[:-1] if inf.endswith("n") else inf
    # A separable verb puts ge between its particle and its stem: einkaufen -> eingekauft.
    particle = next((p for p in sorted(PARTICLES, key=len, reverse=True)
                     if stem.startswith(p) and part.startswith(p + "ge")), "")
    return not part.endswith("t") or stem[len(particle):] not in part


def _compound(sentence: dict, unit: dict) -> tuple[int, int, str] | None:
    """(aux index, participle index, auxiliary) of a Perfekt-like unit; the auxiliary may come last."""
    toks = sentence["tokens"]
    part = next((i for i in unit["tokens"] if toks[i].get("form") == "part.pass"), None)
    aux = next((i for i in unit["tokens"] if headword(toks[i].get("lemmaID")) in AUX_FORMS and i != part), None)
    if part is None or aux is None:
        return None
    return aux, part, headword(toks[aux]["lemmaID"])


def _aux_tense(token: dict, aux: str) -> tuple[str, int] | None:
    key, person = form_key(token.get("form") or ""), form_person(token.get("form") or "")
    if key in AUX_FORMS[aux] and person in PERSONS:
        return key, PERSONS.index(person)
    return None


def _governor(sentence: dict, index: int) -> str | None:
    """The preposition right before a determiner, if any."""
    if index > 0 and sentence["tokens"][index - 1].get("pos") == "ADP":
        return sentence["tokens"][index - 1]["t"].lower()
    return None


def _next_noun(sentence: dict, index: int) -> dict | None:
    for tok in sentence["tokens"][index + 1: index + 4]:
        if tok.get("pos") == "NOUN":
            return tok
        if tok.get("pos") in ("PUNCT", "VERB", "AUX"):
            return None
    return None


def _clause_after_subordinator(sentence: dict, index: int) -> bool:
    """Whether a token is in a clause that one of the subordinators the Nebensätze page teaches opens
    (the linker's set; ambiguous words like damit and als stay out)."""
    for tok in reversed(sentence["tokens"][:index]):
        if tok.get("pos") == "PUNCT" and tok["t"] in (",", ";", ":", ".", "!", "?"):
            return False
        if tok["t"].lower() in VERB_LAST_TOPIC_WORDS and tok.get("pos") == "SCONJ":
            return True
    return False


# --- recipes -----------------------------------------------------------------------------

def compound_candidates(sentence: dict, topics: dict[str, TopicInfo]) -> list[Candidate]:
    out: list[Candidate] = []
    toks = sentence["tokens"]
    for unit in sentence.get("units", []):
        tag = unit.get("form") or ""
        if form_key(tag) not in COMPOUND_TENSES:
            continue
        found = _compound(sentence, unit)
        topic = (unit.get("grammar") or [FORM_TOPIC.get(form_key(tag), "")])[0]
        infinitive = headword(unit.get("lemmaID"))
        if not found or not topic or not infinitive:
            continue
        aux_i, part_i, aux = found
        participle = toks[part_i]["t"]
        aux_tok = toks[aux_i]
        both = tag.endswith("+h") or tag.endswith("+s")

        tense = _aux_tense(aux_tok, aux)
        if tense and not both:
            key, person = tense
            other = "haben" if aux == "sein" else "sein"
            right = aux_tok["t"]
            wrong = match_case(AUX_FORMS[other][key][person], right)
            why = f"{infinitive} takes {aux}." + (" Verbs of movement and change usually do." if aux == "sein" else "")
            out.append(Candidate("aux", topic, sentence["id"], {
                "kind": "choice", "prompt": "Pick the auxiliary.", **_gap(sentence, *aux_tok["r"]), "cue": infinitive,
                "options": [right, wrong] if aux == "haben" else [wrong, right],  # haben first, always
                "answers": [right], "near": {german_key(wrong): why},
                "rule": f"{infinitive} takes {aux}: " + (f"{right.lower()} … {participle}." if aux_i < part_i
                                                          else f"{participle} … {right.lower()}.")}))

        irregular = is_irregular_participle(infinitive, participle)
        weak = weak_participle(infinitive)
        near = {german_key(weak): f"{infinitive} has an irregular participle."} \
            if irregular and weak and german_key(weak) != german_key(participle) else {}
        out.append(Candidate("participle", topic, sentence["id"], {
            "kind": "gap", "prompt": "Type the past participle.", **_gap(sentence, *toks[part_i]["r"]),
            "cue": infinitive, "answers": [participle], "near": near,
            "hint": "It's irregular." if irregular else None, "rule": f"{infinitive} → {participle}."}))
    return out


def form_candidates(sentence: dict, covered: set[int], forms: Forms) -> list[Candidate]:
    out: list[Candidate] = []
    for i, tok in enumerate(sentence["tokens"]):
        tag = tok.get("form") or ""
        key, person = form_key(tag), form_person(tag)
        infinitive = headword(tok.get("lemmaID"))
        if i in covered or key not in TENSE_LABEL or not person or not infinitive:
            continue
        topics = [FORM_TOPIC[key]] if key in FORM_TOPIC else []
        if infinitive in MODALS:
            topics = ["de:modalverben"]
        elif infinitive in ("sein", "haben") and key == "ind.pres":
            topics = ["de:sein-haben"]
        if _clause_after_subordinator(sentence, i):
            topics.append("de:nebensaetze")
        if not topics:
            continue
        surface = tok["t"]
        g = _gap(sentence, *tok["r"])
        cue = f"{infinitive}, {PERSON_LABEL.get(person, person)}"
        lemma_forms = forms.of(tok["lemmaID"])
        right = {german_key(f) for f, t in lemma_forms if form_key(t) == key and form_person(t) == person} \
            | {german_key(surface)}
        near: dict[str, str] = {}
        same_tense: list[str] = []
        other_tense: list[str] = []
        for form, other in lemma_forms:
            okey, operson = form_key(other), form_person(other)
            if german_key(form) in right or not operson:
                continue
            if okey == key and operson != person:
                near.setdefault(german_key(form), f"Check the person: we need {PERSON_LABEL.get(person, person)}.")
                same_tense.append(match_case(form, surface))
            elif operson == person and okey != key and okey in TENSE_LABEL:
                near.setdefault(german_key(form), f"That's the {TENSE_LABEL[okey]}. We need the {TENSE_LABEL[key]}.")
                other_tense.append(match_case(form, surface))
        # Present and imperative drill the person; the other tenses drill the tense.
        pool = same_tense if key in ("ind.pres", "imp.pres") else other_tense or same_tense
        others = sorted({german_key(f): f for f in pool}.values(), key=lambda f: _seed(sentence["id"], f))[:2]
        rule = f"{infinitive}, {TENSE_LABEL[key]}, {PERSON_LABEL.get(person, person)} → {surface.lower()}."
        for topic in topics:
            if len(others) == 2:
                out.append(Candidate("form-choice", topic, sentence["id"], {
                    "kind": "choice", "prompt": "Pick the form.", **g, "cue": cue,
                    "options": _neutral([surface] + others, sentence["id"]), "answers": [surface],
                    "near": {k: v for k, v in near.items() if k in {german_key(o) for o in others}}, "rule": rule}))
            out.append(Candidate("form", topic, sentence["id"], {
                "kind": "gap", "prompt": "Type the verb.", **g, "cue": cue, "answers": [surface], "near": near,
                "rule": rule}))
    return out


def _determiner_family(token: dict) -> tuple[str, dict[str, str]] | None:
    """(headword, case -> form) of the determiner a token is, for its gender and number."""
    gn = token.get("gn")
    if gn not in DEFINITE:
        return None
    lemma = headword(token.get("lemmaID"))
    if lemma == "der":
        return "der", DEFINITE[gn]
    if lemma in EIN_STEMS:
        if lemma == "ein" and gn == "pl":
            return None
        stem = EIN_STEMS[lemma]
        out = {}
        for case, ending in EIN_ENDING[gn].items():
            out[case] = (lemma if not ending else stem + ending)
        return lemma, out
    if lemma in DER_STEMS:
        return lemma, {c: DER_STEMS[lemma] + e for c, e in DER_ENDING[gn].items()}
    return None


def case_candidates(sentence: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for i, tok in enumerate(sentence["tokens"]):
        case = tok.get("case")
        if tok.get("pos") != "DET" or tok.get("parts") or case not in CASE_NAME:
            continue
        family = _determiner_family(tok)
        noun = _next_noun(sentence, i)
        if family is None or noun is None:
            continue
        lemma, by_case = family
        right = tok["t"]
        if german_key(by_case.get(case, "")) != german_key(right):
            continue  # the token isn't the form the tables give; don't guess
        options = [match_case(by_case[c], right) for c in CASE_ORDER if c != "gen" or case == "gen"]
        options = list(dict.fromkeys(options))
        if len(options) < 2:
            continue
        prep = _governor(sentence, i)
        if prep and prep in TWO_WAY:
            topic = "de:wechselpraepositionen"
            reason = (f"{prep} with the dative says where something is (wo?)." if case == "dat" else
                      f"{prep} with the accusative says where something goes (wohin?).")
        elif prep:
            topic = CASE_TOPIC.get(case, "de:artikel")
            reason = f"{prep} takes the {CASE_NAME[case]}."
        else:
            topic = CASE_TOPIC.get(case, "de:artikel")
            # Without a preposition, the case alone: an accusative can be a time (jeden Tag) and a
            # dative the object of helfen, so naming a role would often be wrong.
            reason = {"nom": "It's the subject, so it's in the nominative.",
                      "acc": "Here it's in the accusative.",
                      "dat": "Here it's in the dative.",
                      "gen": "It says whose, so it's in the genitive."}[case]
        if lemma in POSSESSIVES:
            topic = "de:possessivartikel"
        out.append(Candidate("case", topic, sentence["id"], {
            "kind": "choice", "prompt": "Pick the article.", **_gap(sentence, *tok["r"]), "cue": noun["t"],
            "options": options, "answers": [right],
            "near": {german_key(o): reason for o in options if german_key(o) != german_key(right)},
            "rule": f"{reason[:-1]}: {right.lower()} {noun['t']}."}))
    return out


def contraction_candidates(sentence: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for tok in sentence["tokens"]:
        low = tok["t"].lower()
        if not tok.get("parts") or low not in CONTRACTION_PAIRS:
            continue
        prep, other = CONTRACTION_PAIRS[low]
        right = tok["t"]
        wrong = match_case(other, right)
        topic = "de:dativ" if prep == "zu" else "de:wechselpraepositionen"
        out.append(Candidate("contraction", topic, sentence["id"], {
            "kind": "choice", "prompt": "Pick the preposition.", **_gap(sentence, *tok["r"]),
            "cue": f"{prep} + …", "options": sorted([right, wrong], key=german_key), "answers": [right],
            "near": {german_key(wrong): CONTRACTION_WHY[low]}, "rule": CONTRACTION_WHY[low]}))
    return out


def particle_candidates(sentence: dict) -> list[Candidate]:
    out: list[Candidate] = []
    toks = sentence["tokens"]
    for unit in sentence.get("units", []):
        if "de:trennbare-verben" not in (unit.get("grammar") or []) or len(unit["tokens"]) != 2:
            continue
        verb_i, particle_i = sorted(unit["tokens"])
        infinitive = headword(unit.get("lemmaID"))
        particle = toks[particle_i]["t"]
        if not infinitive or not infinitive.startswith(particle.lower()):
            continue
        out.append(Candidate("particle", "de:trennbare-verben", sentence["id"], {
            "kind": "gap", "prompt": "Finish the verb.", **_gap(sentence, *toks[particle_i]["r"]), "cue": infinitive,
            "answers": [particle], "near": {}, "hint": "Its first part goes to the end of the clause.",
            "rule": f"{infinitive}: {toks[verb_i]['t'].lower()} … {particle}."}))
    return out


def order_candidate(sentence: dict, topic: str) -> Candidate | None:
    words = [t for t in sentence["tokens"] if t.get("pos") != "PUNCT"]
    if not (BUILD_WORDS[0] <= len(words) <= BUILD_WORDS[1]) or any(t.get("pos") == "NUM" for t in words):
        return None
    tiles = []
    for n, tok in enumerate(words):
        w = tok["t"]
        # Nouns, names and polite Sie keep their capital; other words lose the sentence's.
        if n == 0 and tok.get("pos") not in ("NOUN", "PROPN") and tok.get("lemmaID") != "de:Sie:pron":
            w = w[:1].lower() + w[1:]
        tiles.append(w)
    distractors: list[str] = []
    for unit in sentence.get("units", []):
        found = _compound(sentence, unit) if form_key(unit.get("form") or "") in COMPOUND_TENSES else None
        if found and not (unit.get("form") or "").endswith(("+h", "+s")):
            tense = _aux_tense(sentence["tokens"][found[0]], found[2])
            if tense:
                wrong = AUX_FORMS["haben" if found[2] == "sein" else "sein"][tense[0]][tense[1]]
                if german_key(wrong) not in {german_key(t) for t in tiles}:
                    distractors = [wrong]
            break
    return Candidate("order", topic, sentence["id"], {
        "kind": "build", "prompt": "Put the words in order.", "translation": sentence["translation"],
        "tiles": tiles, "distractors": distractors, "answers": [" ".join(tiles)], "rule": sentence["text"]})


def participles_match(text: dict, topic: str) -> Candidate | None:
    pairs: list[list[str]] = []
    seen: set[str] = set()
    sentences = []
    for s in (s for b in text["blocks"] for s in b["sentences"]):
        for unit in s.get("units", []):
            if form_key(unit.get("form") or "") not in COMPOUND_TENSES:
                continue
            found = _compound(s, unit)
            infinitive = headword(unit.get("lemmaID"))
            if not found or not infinitive or infinitive in seen:
                continue
            participle = s["tokens"][found[1]]["t"].lower()
            if participle in seen:
                continue
            seen.update((infinitive, participle))
            pairs.append([infinitive, participle])
            sentences.append(s["id"])
            if len(pairs) == 4:
                break
        if len(pairs) == 4:
            break
    if len(pairs) < 3:
        return None
    return Candidate("participles", topic, sentences[0], {
        "kind": "match", "prompt": "Match each verb to its participle.", "pairs": pairs,
        "sentences": sentences, "rule": "; ".join(f"{a} → {b}" for a, b in pairs) + "."})


def candidates(text: dict, topics: dict[str, TopicInfo], forms: Forms) -> list[Candidate]:
    out: list[Candidate] = []
    for s in (s for b in text["blocks"] for s in b["sentences"]):
        covered = {i for u in s.get("units", []) for i in u["tokens"]}
        out += compound_candidates(s, topics)
        out += form_candidates(s, covered, forms)
        out += case_candidates(s)
        out += contraction_candidates(s)
        out += particle_candidates(s)
    return [c for c in out if c.topic in topics]
