"""Practice drills after a text (HANDOFF.md 3.9), generated from the text's own tagged sentences.

Every drill uses one sentence of the text (`match` uses several). The generator reads only the built
text (tokens, units, form tags, agreement) and, when it has one, the content database's forms, so a
build is reproducible and needs no model or network.

Recipes, by what the sentence holds:

    aux          compound tense: pick avere or essere            (choice)
    participle   compound tense: type the participle             (gap)
    agreement    compound with essere: pick the participle ending (choice)
    participles  every compound in the text: verb -> participle  (match)
    form         simple tense: pick the form, or type it         (choice | gap)
    article      definite or indefinite article                  (choice)
    contraction  articulated preposition                         (choice)
    unit         a hand-marked unit with a grammar topic         (gap)
    order        the sentence's words in order                   (build)

The first drills practise the topic the text introduces; up to two bring back an earlier topic the
text also uses (`recycled`).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field

from .normalize import fold, utf16_len, utf16_slice

# mood.tense -> the grammar topic that teaches it (the same table the curriculum checker uses).
FORM_TOPIC = {
    "ind.pres": "presente-indicativo", "ind.pp": "passato-prossimo", "ind.impf": "imperfetto",
    "imp.pres": "imperativo", "imp.neg": "imperativo", "ind.fut": "futuro-semplice",
    "cond.pres": "condizionale-presente", "ind.tpp": "trapassato-prossimo", "sub.pres": "congiuntivo-presente",
    "ind.prem": "passato-remoto", "ind.tpr": "passato-remoto", "cond.pass": "condizionale-passato",
    "ind.futa": "futuro-anteriore", "sub.pass": "congiuntivo-passato", "sub.impf": "congiuntivo-imperfetto",
    "sub.tpp": "congiuntivo-imperfetto",
}
COMPOUND_TENSES = {"ind.pp", "ind.tpp", "ind.tpr", "ind.futa", "sub.pass", "sub.tpp", "cond.pass"}
COMPOUND_TOPICS = {"passato-prossimo", "trapassato-prossimo", "futuro-anteriore", "condizionale-passato",
                   "congiuntivo-passato"}
TENSE_LABEL = {
    "ind.pres": "presente", "ind.impf": "imperfetto", "ind.fut": "futuro", "ind.prem": "passato remoto",
    "cond.pres": "condizionale presente", "sub.pres": "congiuntivo presente", "sub.impf": "congiuntivo imperfetto",
    "imp.pres": "imperativo",
}
# Which reading names a form that has several (vada: congiuntivo before imperativo).
TAG_PRIORITY = {"ind.pres": 0, "ind.impf": 1, "ind.fut": 2, "ind.prem": 3, "cond.pres": 4, "sub.pres": 5,
                "sub.impf": 6, "imp.pres": 7}
PERSON_LABEL = {"1s": "io", "2s": "tu", "3s": "lui, lei", "1p": "noi", "2p": "voi", "3p": "loro"}

# The auxiliaries' forms, by the auxiliary token's own form tag.
AUX_FORMS = {
    "essere": {
        "ind.pres": ["sono", "sei", "è", "siamo", "siete", "sono"],
        "ind.impf": ["ero", "eri", "era", "eravamo", "eravate", "erano"],
        "ind.prem": ["fui", "fosti", "fu", "fummo", "foste", "furono"],
        "ind.fut": ["sarò", "sarai", "sarà", "saremo", "sarete", "saranno"],
        "cond.pres": ["sarei", "saresti", "sarebbe", "saremmo", "sareste", "sarebbero"],
        "sub.pres": ["sia", "sia", "sia", "siamo", "siate", "siano"],
        "sub.impf": ["fossi", "fossi", "fosse", "fossimo", "foste", "fossero"],
    },
    "avere": {
        "ind.pres": ["ho", "hai", "ha", "abbiamo", "avete", "hanno"],
        "ind.impf": ["avevo", "avevi", "aveva", "avevamo", "avevate", "avevano"],
        "ind.prem": ["ebbi", "avesti", "ebbe", "avemmo", "aveste", "ebbero"],
        "ind.fut": ["avrò", "avrai", "avrà", "avremo", "avrete", "avranno"],
        "cond.pres": ["avrei", "avresti", "avrebbe", "avremmo", "avreste", "avrebbero"],
        "sub.pres": ["abbia", "abbia", "abbia", "abbiamo", "abbiate", "abbiano"],
        "sub.impf": ["avessi", "avessi", "avesse", "avessimo", "aveste", "avessero"],
    },
}
PERSONS = ["1s", "2s", "3s", "1p", "2p", "3p"]
REFLEXIVE_CLITICS = {"mi", "ti", "si", "ci", "vi"}
DEFINITE = {"sg": ["il", "lo", "la", "l'"], "pl": ["i", "gli", "le"]}
INDEFINITE = ["un", "uno", "una", "un'"]
GN_LABEL = {"ms": "masculine singular", "fs": "feminine singular", "mp": "masculine plural",
            "fp": "feminine plural"}
# Articulated prepositions by preposition, in article order (il lo la l' i gli le).
CONTRACTION_FAMILY = {
    "a": ["al", "allo", "alla", "all'", "ai", "agli", "alle"],
    "da": ["dal", "dallo", "dalla", "dall'", "dai", "dagli", "dalle"],
    "di": ["del", "dello", "della", "dell'", "dei", "degli", "delle"],
    "in": ["nel", "nello", "nella", "nell'", "nei", "negli", "nelle"],
    "su": ["sul", "sullo", "sulla", "sull'", "sui", "sugli", "sulle"],
}
ARTICLE_ORDER = ["il", "lo", "la", "l'", "i", "gli", "le"]

MIN_DRILLS = 3
MAX_DRILLS = 8
MAIN_DRILLS = 6  # drills of the text's own topic, including its match and build drills
RECYCLED_DRILLS = 2
PER_RECIPE = 3
BUILD_WORDS = (4, 9)

CHOICE_RECIPES = ("aux", "agreement", "form-choice", "article", "contraction")


@dataclass
class TopicInfo:
    id: str
    title: str
    level: str
    order: int
    summary: str = ""


@dataclass
class Candidate:
    recipe: str
    topic: str
    sentence: str
    drill: dict = field(default_factory=dict)


# --- helpers -----------------------------------------------------------------------------

def headword(lemma_id: str | None) -> str:
    """it:andare:v -> andare; it:dare_retta:phr -> dare retta"""
    if not lemma_id:
        return ""
    parts = lemma_id.split(":")
    return parts[1].replace("_", " ") if len(parts) > 1 else lemma_id


def form_key(tag: str) -> str:
    return ".".join(tag.split("+")[0].split(".")[:2])


def form_person(tag: str) -> str | None:
    parts = tag.split("+")[0].split(".")
    return parts[2] if len(parts) == 3 else None


def match_case(word: str, model: str) -> str:
    """Capitalise word like model (sentence-initial gaps keep their capital)."""
    return word[:1].upper() + word[1:] if model[:1].isupper() else word


def regular_participle(infinitive: str) -> str | None:
    for ending, participle in (("are", "ato"), ("ere", "uto"), ("ire", "ito")):
        if infinitive.endswith(ending) and len(infinitive) > 3:
            return infinitive[: -len(ending)] + participle
    return None


def _span(sentence: dict, first: int, last: int) -> tuple[int, int]:
    """UTF-16 [start, length] covering tokens first..last."""
    toks = sentence["tokens"]
    start = toks[first]["r"][0]
    end = toks[last]["r"][0] + toks[last]["r"][1]
    return start, end - start


def _gap(sentence: dict, start: int, length: int) -> dict:
    text = sentence["text"]
    return {"before": utf16_slice(text, 0, start), "after": utf16_slice(text, start + length, utf16_len(text)),
            "r": [start, length], "surface": utf16_slice(text, start, length)}


def _next_noun(sentence: dict, index: int) -> dict | None:
    for tok in sentence["tokens"][index + 1: index + 4]:
        if tok.get("pos") == "NOUN":
            return tok
        if tok.get("pos") in ("PUNCT", "VERB", "AUX"):
            return None
    return None


def _seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def _neutral(options: list[str], seed: str) -> list[str]:
    """Options in an order that doesn't depend on which one is the answer."""
    return sorted(options, key=lambda o: _seed(seed, fold(o)))


class Forms:
    """Other forms of a lemma from the content database, when there is one."""

    def __init__(self, conn: sqlite3.Connection | None):
        self.conn = conn
        self.cache: dict[str, list[tuple[str, str]]] = {}

    def of(self, lemma_id: str) -> list[tuple[str, str]]:
        if self.conn is None or not lemma_id:
            return []
        if lemma_id not in self.cache:
            rows = self.conn.execute("SELECT form, tag FROM form WHERE lemma_id = ? AND tag != ''",
                                     (lemma_id,)).fetchall()
            self.cache[lemma_id] = sorted({(f, t) for f, t in rows})
        return self.cache[lemma_id]


# --- recipes -----------------------------------------------------------------------------

def _compound(sentence: dict, unit: dict) -> tuple[int, int, str] | None:
    """(aux index, participle index, aux lemma) of a compound-tense unit."""
    toks = sentence["tokens"]
    aux = next((i for i in unit["tokens"] if headword(toks[i].get("lemmaID")) in AUX_FORMS and toks[i].get("form")),
               None)
    part = next((i for i in unit["tokens"] if toks[i].get("form") == "part.pass"), None)
    if aux is None:
        # The linker leaves the auxiliary's lemma off some tokens; fall back to its surface.
        for i in unit["tokens"]:
            low = toks[i]["t"].lower()
            for lemma, table in AUX_FORMS.items():
                if any(low in forms for forms in table.values()):
                    aux = i
                    break
            if aux is not None:
                break
    if part is None:
        part = unit["tokens"][-1] if len(unit["tokens"]) >= 2 else None
    if aux is None or part is None or part <= aux:
        return None
    low = toks[aux]["t"].lower()
    aux_lemma = headword(toks[aux].get("lemmaID"))
    if aux_lemma not in AUX_FORMS:
        aux_lemma = next(l for l, table in AUX_FORMS.items() if any(low in f for f in table.values()))
    return aux, part, aux_lemma


def _aux_tense(token: dict, aux_lemma: str) -> tuple[str, int] | None:
    """(tense key, person index) of an auxiliary token, from its tag or its surface."""
    tag = token.get("form") or ""
    key, person = form_key(tag), form_person(tag)
    if key in AUX_FORMS[aux_lemma] and person in PERSONS:
        return key, PERSONS.index(person)
    low = token["t"].lower()
    for key, forms in AUX_FORMS[aux_lemma].items():
        if low in forms:
            return key, forms.index(low)
    return None


def compound_candidates(text: dict, sentence: dict, topics: dict[str, TopicInfo]) -> list[Candidate]:
    out: list[Candidate] = []
    toks = sentence["tokens"]
    for unit in sentence.get("units", []):
        tag = unit.get("form") or ""
        if form_key(tag) not in COMPOUND_TENSES:
            continue
        found = _compound(sentence, unit)
        if not found:
            continue
        aux_i, part_i, aux_lemma = found
        topic = (unit.get("grammar") or [FORM_TOPIC.get(form_key(tag), "")])[0]
        if not topic:
            continue
        infinitive = headword(unit.get("lemmaID"))
        participle = toks[part_i]["t"]
        aux_tok = toks[aux_i]
        reflexive = aux_i > 0 and toks[aux_i - 1]["t"].lower() in REFLEXIVE_CLITICS and aux_lemma == "essere"
        both = tag.endswith("+e") or tag.endswith("+a")

        # aux: avere or essere
        tense = _aux_tense(aux_tok, aux_lemma)
        if tense and infinitive and not both:
            key, person = tense
            other = "avere" if aux_lemma == "essere" else "essere"
            right = aux_tok["t"]
            wrong = match_case(AUX_FORMS[other][key][person], right)
            if fold(wrong) != fold(right):
                why = ("Reflexive verbs take essere." if reflexive
                       else f"{infinitive} takes {aux_lemma}.")
                g = _gap(sentence, *aux_tok["r"])
                out.append(Candidate("aux", topic, sentence["id"], {
                    "kind": "choice", "prompt": "Pick the auxiliary.", **g, "cue": infinitive,
                    "options": [right, wrong] if aux_lemma == "avere" else [wrong, right],  # avere first, always
                    "answers": [right], "near": {fold(wrong): why},
                    "rule": f"{why[:-1]}: {right.lower()} {participle}."}))

        # participle: type it
        if infinitive:
            g = _gap(sentence, *toks[part_i]["r"])
            near: dict[str, str] = {}
            regular = regular_participle(infinitive)
            irregular = regular is not None and fold(regular) != fold(participle) and \
                fold(regular[:-1]) != fold(participle[:-1])
            if irregular:
                near[fold(regular)] = f"{infinitive} has an irregular participle."
            if aux_lemma == "essere" and participle[-1:] in "oaie":
                for ending in "oaie":
                    alt = participle[:-1] + ending
                    if fold(alt) != fold(participle):
                        near.setdefault(fold(alt), "With essere, the participle agrees with the subject.")
            out.append(Candidate("participle", topic, sentence["id"], {
                "kind": "gap", "prompt": "Type the past participle.", **g, "cue": infinitive,
                "answers": [participle], "near": near,
                "hint": "It's irregular." if irregular else None,
                "rule": f"{infinitive} → {participle[:-1] + 'o' if aux_lemma == 'essere' else participle}."}))

        # agreement: pick the ending
        if aux_lemma == "essere" and participle[-1:].lower() in "oaie" and len(participle) > 3:
            stem = participle[:-1]
            options = [stem + e for e in "oaie"]
            right = participle
            near = {fold(o): "With essere, the participle agrees with the subject." for o in options if o != right}
            subject = unit.get("agree")
            label = GN_LABEL.get(subject or "", "")
            out.append(Candidate("agreement", topic, sentence["id"], {
                "kind": "choice", "prompt": "Pick the right ending.", **_gap(sentence, *toks[part_i]["r"]),
                "cue": infinitive, "options": options, "answers": [right], "near": near,
                "rule": "With essere, the participle agrees with the subject" + (f" ({label})." if label else ".")}))
    return out


def form_candidates(sentence: dict, covered: set[int], forms: Forms) -> list[Candidate]:
    out: list[Candidate] = []
    for i, tok in enumerate(sentence["tokens"]):
        tag = tok.get("form") or ""
        key, person = form_key(tag), form_person(tag)
        topic = FORM_TOPIC.get(key)
        if i in covered or not topic or key in COMPOUND_TENSES or not person or tok.get("pos") == "AUX":
            continue
        infinitive = headword(tok.get("lemmaID"))
        if not infinitive:
            continue
        surface = tok["t"]
        g = _gap(sentence, *tok["r"])
        cue = f"{infinitive}, {PERSON_LABEL.get(person, person)}"
        near: dict[str, str] = {}
        others = []
        lemma_forms = forms.of(tok["lemmaID"])
        # A surface that is also this tense and person (sono: 1s and 3p) is never a wrong answer.
        right = {fold(f) for f, t in lemma_forms if form_key(t) == key and form_person(t) == person} | {fold(surface)}
        for form, other in sorted(lemma_forms, key=lambda ft: TAG_PRIORITY.get(form_key(ft[1]), 9)):
            okey, operson = form_key(other), form_person(other)
            if fold(form) in right or not operson:
                continue
            if operson == person and okey != key and okey in TENSE_LABEL:
                near.setdefault(fold(form), f"That's the {TENSE_LABEL[okey]}. We need the {TENSE_LABEL.get(key, key)}.")
                if okey in ("ind.pres", "ind.impf", "ind.fut", "cond.pres", "sub.pres", "sub.impf", "ind.prem"):
                    others.append(match_case(form, surface))
            elif okey == key and operson != person:
                near.setdefault(fold(form), f"Check the person: we need {PERSON_LABEL.get(person, person)}.")
        rule = f"{infinitive}, {TENSE_LABEL.get(key, key)}, {PERSON_LABEL.get(person, person)} → {surface.lower()}."
        others = sorted(set(others), key=lambda f: _seed(sentence["id"], f))[:2]
        if len(others) == 2:
            out.append(Candidate("form-choice", topic, sentence["id"], {
                "kind": "choice", "prompt": "Pick the form.", **g, "cue": cue, "options": _neutral([surface] + others, sentence["id"]),
                "answers": [surface], "near": {k: v for k, v in near.items() if k in {fold(o) for o in others}},
                "rule": rule}))
        out.append(Candidate("form", topic, sentence["id"], {
            "kind": "gap", "prompt": "Type the verb.", **g, "cue": cue, "answers": [surface], "near": near,
            "rule": rule}))
    return out


def article_candidates(sentence: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for i, tok in enumerate(sentence["tokens"]):
        low = tok["t"].lower()
        if tok.get("pos") != "DET" or tok.get("parts"):
            continue
        if low in INDEFINITE:
            family = INDEFINITE
        elif low in DEFINITE["sg"]:
            family = DEFINITE["sg"]
        elif low in DEFINITE["pl"]:
            family = DEFINITE["pl"]
        else:
            continue
        noun = _next_noun(sentence, i)
        if noun is None:
            continue
        right = tok["t"]
        options = [match_case(o, right) for o in family]
        why = f"{noun['t']} is {GN_LABEL[noun['gn']]}." if noun.get("gn") in GN_LABEL else \
            f"Which article does {noun['t']} take?"
        near = {fold(o): why for o in options if fold(o) != fold(right)}
        out.append(Candidate("article", "articles", sentence["id"], {
            "kind": "choice", "prompt": "Pick the article.", **_gap(sentence, *tok["r"]), "options": options,
            "answers": [right], "near": near, "rule": f"{right.lower()} {noun['t']}."}))
    return out


def contraction_candidates(sentence: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for i, tok in enumerate(sentence["tokens"]):
        parts = tok.get("parts") or []
        if len(parts) != 2 or "preposition-contractions" not in (tok.get("grammar") or []):
            continue
        prep, art = parts[0]["t"].lower(), parts[1]["t"].lower()
        family = CONTRACTION_FAMILY.get(prep)
        right = tok["t"]
        if not family or fold(right) not in {fold(f) for f in family}:
            continue
        idx = [fold(f) for f in family].index(fold(right))
        plural = idx >= 4
        pool = [f for n, f in enumerate(family) if n != idx and (n >= 4) == plural]
        pool = sorted(pool, key=lambda f: _seed(sentence["id"], f))[:3]
        options = _neutral([match_case(o, right) for o in [family[idx]] + pool], sentence["id"])
        noun = _next_noun(sentence, i)
        why = f"{noun['t']} takes {ARTICLE_ORDER[idx] if idx < len(ARTICLE_ORDER) else art}." if noun else \
            f"{prep} + {art} → {right.lower()}."
        out.append(Candidate("contraction", "preposition-contractions", sentence["id"], {
            "kind": "choice", "prompt": "Pick the preposition.", **_gap(sentence, *tok["r"]),
            "cue": f"{prep} + …", "options": options, "answers": [right],
            "near": {fold(o): why for o in options if fold(o) != fold(right)},
            "rule": f"{prep} + {art} → {right.lower()}."}))
    return out


def unit_candidates(sentence: dict, topics: dict[str, TopicInfo]) -> list[Candidate]:
    """Hand-marked units with a topic the other recipes don't cover (si impersonale, pronouns, …)."""
    out: list[Candidate] = []
    for unit in sentence.get("units", []):
        topics_of = [g for g in unit.get("grammar") or [] if g in topics]
        tokens = sorted(unit["tokens"])
        if not topics_of or topics_of[0] in COMPOUND_TOPICS:
            continue  # compound tenses have their own recipes
        if tokens != list(range(tokens[0], tokens[-1] + 1)) or len(tokens) > 4:
            continue
        g = _gap(sentence, *_span(sentence, tokens[0], tokens[-1]))
        cue = unit.get("gloss") or headword(unit.get("lemmaID"))
        topic = topics_of[0]
        out.append(Candidate("unit", topic, sentence["id"], {
            "kind": "gap", "prompt": "Fill the gap.", **g, "cue": cue, "answers": [g["surface"]], "near": {},
            "rule": unit.get("note") or topics[topic].summary or f"{g['surface']}."}))
    return out


def order_candidate(sentence: dict, topic: str) -> Candidate | None:
    words = [t for t in sentence["tokens"] if t.get("pos") != "PUNCT"]
    if not (BUILD_WORDS[0] <= len(words) <= BUILD_WORDS[1]):
        return None
    if any(t.get("pos") == "NUM" for t in words):
        return None
    tiles = []
    for n, tok in enumerate(words):
        w = tok["t"]
        if n == 0 and tok.get("pos") != "PROPN" and not (len(w) > 1 and w.isupper()):
            w = w[:1].lower() + w[1:]
        tiles.append(w)
    distractors: list[str] = []
    for unit in sentence.get("units", []):
        found = _compound(sentence, unit) if form_key(unit.get("form") or "") in COMPOUND_TENSES else None
        if found:
            tense = _aux_tense(sentence["tokens"][found[0]], found[2])
            if tense:
                other = "avere" if found[2] == "essere" else "essere"
                wrong = AUX_FORMS[other][tense[0]][tense[1]]
                if fold(wrong) not in {fold(t) for t in tiles}:
                    distractors = [wrong]
            break
    return Candidate("order", topic, sentence["id"], {
        "kind": "build", "prompt": "Put the words in order.", "translation": sentence["translation"],
        "tiles": tiles, "distractors": distractors, "answers": [" ".join(tiles)],
        "rule": sentence["text"]})


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
            if found[2] == "essere" and participle[-1:] in "aie":
                participle = participle[:-1] + "o"
            if participle in seen:  # è stato (essere) and sono stata (stare) both give stato
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


# --- selection ---------------------------------------------------------------------------

def candidates(text: dict, topics: dict[str, TopicInfo], forms: Forms) -> list[Candidate]:
    out: list[Candidate] = []
    for s in (s for b in text["blocks"] for s in b["sentences"]):
        covered = {i for u in s.get("units", []) for i in u["tokens"]}
        out += compound_candidates(text, s, topics)
        out += form_candidates(s, covered, forms)
        out += article_candidates(s)
        out += contraction_candidates(s)
        out += unit_candidates(s, topics)
    return [c for c in out if c.topic in topics]


def _pick(pool: list[Candidate], limit: int, used: set[str], seed: int, allow_reuse: bool = False,
          reserved: frozenset[str] = frozenset()) -> list[Candidate]:
    """Round-robin over recipes so a set mixes formats, one drill per sentence, choices first."""
    by_recipe: dict[str, list[Candidate]] = {}
    for c in pool:
        by_recipe.setdefault(c.recipe, []).append(c)
    order = sorted(by_recipe, key=lambda r: (r not in CHOICE_RECIPES, _seed(str(seed), r)))
    picked: list[Candidate] = []
    count = lambda r: sum(1 for c in picked if c.recipe == r)  # noqa: E731
    while len(picked) < limit and any(by_recipe.values()):
        progressed = False
        for recipe in order:
            queue = by_recipe[recipe]
            while queue and queue[0].sentence in used:
                queue.pop(0)
            if queue and len(picked) < limit and count(recipe) < PER_RECIPE:
                c = queue.pop(0)
                picked.append(c)
                used.add(c.sentence)
                progressed = True
        if not progressed:
            break
    if len(picked) < limit and allow_reuse:
        # A rare topic: a second drill on a sentence already used, never the same gap twice.
        gaps = {(c.sentence, tuple(c.drill.get("r", ()))) for c in picked}
        for c in pool:
            key = (c.sentence, tuple(c.drill.get("r", ())))
            if len(picked) >= limit:
                break
            if c not in picked and key not in gaps and c.drill.get("r") and count(c.recipe) < PER_RECIPE \
                    and c.sentence not in reserved:
                picked.append(c)
                gaps.add(key)
    return picked


def generate(text: dict, introduces: list[str], topics: dict[str, TopicInfo],
             conn: sqlite3.Connection | None = None) -> list[dict]:
    """The practice set for one built text, or [] when it can't fill a set."""
    forms = Forms(conn)
    pool = candidates(text, topics, forms)
    level_rank = {lvl: n for n, lvl in enumerate(["A1", "A2", "B1", "B2"])}
    text_rank = level_rank.get(text.get("level", ""), 9)
    present = {c.topic for c in pool}
    main = [t for t in introduces if t in present]
    if not main:
        fitting = [t for t in present if level_rank.get(topics[t].level, 9) <= text_rank]
        main = sorted(fitting, key=lambda t: -topics[t].order)[:1]
    if not main:
        return []
    seed = _seed(text["id"])
    used: set[str] = set()
    chosen: list[tuple[Candidate, bool]] = []

    sentences = {s["id"]: s for b in text["blocks"] for s in b["sentences"]}
    for topic in main:
        room = min(MAIN_DRILLS, MAX_DRILLS - RECYCLED_DRILLS - len(chosen))
        if room <= 0:
            break
        own = [c for c in pool if c.topic == topic]
        # One word-order drill, on the last sentence that carries the topic and is short enough.
        build = None
        if not any(x.recipe == "order" for x, _ in chosen):
            for sid in reversed(list(dict.fromkeys(c.sentence for c in own))):
                build = order_candidate(sentences[sid], topic)
                if build:
                    break
        match = participles_match(text, topic) if topic in COMPOUND_TOPICS else None
        extras = [x for x in (match, build) if x][:max(room - 1, 0)]
        if build and build not in extras:
            build = None
        if build:
            used.add(build.sentence)
        reserved = frozenset({build.sentence}) if build else frozenset()
        picked = _pick(own, room - len(extras), used, seed, allow_reuse=True, reserved=reserved)
        chosen += [(c, False) for c in picked]
        chosen += [(c, False) for c in extras]

    main_order = max(topics[t].order for t in main)
    earlier = sorted({c.topic for c in pool if c.topic not in main and topics[c.topic].order < main_order},
                     key=lambda t: (-topics[t].order, t))
    recycled: list[Candidate] = []
    room = min(RECYCLED_DRILLS, MAX_DRILLS - len(chosen))
    for topic in earlier:
        if len(recycled) >= room:
            break
        recycled += _pick([c for c in pool if c.topic == topic], 1, used, seed)
    chosen += [(c, True) for c in recycled]

    if len(chosen) < MIN_DRILLS:
        return []
    drills = []
    for n, (c, is_recycled) in enumerate(chosen, start=1):
        d = {"id": f"d{n}", "kind": c.drill["kind"], "recipe": c.recipe, "topic": c.topic, "sentence": c.sentence}
        for key, value in c.drill.items():
            if key in ("kind", "surface") or value is None or value == {} and key == "near":
                continue
            d[key] = value
        if is_recycled:
            d["recycled"] = True
        drills.append(d)
    return drills


def validate(text: dict, drills: list[dict]) -> list[str]:
    """Errors that fail the build: every drill must point into its text and be answerable."""
    errors = []
    if len(drills) > MAX_DRILLS:
        errors.append(f"{text['id']}: {len(drills)} drills, more than {MAX_DRILLS}")
    sentences = {s["id"]: s for b in text["blocks"] for s in b["sentences"]}
    for d in drills:
        where = f"{text['id']} {d['id']}"
        if d["sentence"] not in sentences:
            errors.append(f"{where}: sentence {d['sentence']} not in text")
            continue
        s = sentences[d["sentence"]]
        if d["kind"] in ("choice", "gap"):
            start, length = d["r"]
            if d["before"] + utf16_slice(s["text"], start, length) + d["after"] != s["text"]:
                errors.append(f"{where}: gap does not rebuild the sentence")
            if utf16_slice(s["text"], start, length) not in d["answers"]:
                errors.append(f"{where}: the sentence's own words are not an accepted answer")
        if d["kind"] == "choice" and not set(d["answers"]) <= set(d["options"]):
            errors.append(f"{where}: answer missing from options")
        if d["kind"] == "choice" and len(set(map(fold, d["options"]))) != len(d["options"]):
            errors.append(f"{where}: duplicate options")
        if d["kind"] == "build" and sorted(d["answers"][0].split(" ")) != sorted(d["tiles"]):
            errors.append(f"{where}: answer doesn't use exactly the tiles")
        if d["kind"] == "match" and len(d["pairs"]) < 2:
            errors.append(f"{where}: fewer than two pairs")
    return errors
