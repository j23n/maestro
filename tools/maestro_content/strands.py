"""The session's strands beyond grammar (HANDOFF.md 3.9): Words, Verbs and Say it, and the Grammar
strand's find drill. drills.generate calls these after it picks the grammar drills.

    Words    sense-choice    what a new word means here              (choice, English options)
             gloss-match     new words to their meanings              (match)
             word-recall     the English meaning as cue: type the word (gap)
             dictation-word  hear the word, type it                   (listen)
    Verbs    form-identify   which tense and person a form is         (choice)
             tense-row       fill a verb's tense, the text's form given (row)
             person-switch   the same verb for another person         (gap, no gap in the sentence)
             lemma-recall    the infinitive of a form                 (gap, no gap in the sentence)
    Grammar  find-forms      tap every form of the introduced tense   (find)
    Say it   function-pick   what a line does                         (choice, English options)
             function-match  lines to what they do                    (match)
             function-say    say a line from its English              (say: an open answer)
             roleplay        take one side of the dialogue            (roleplay)

Words and verbs come from the tokens' lemmas, senses and form tags and the content database; Say it
comes from the sentences' `@fn` tags and the language's functions.yaml (functions.py). Every recipe
works from the text alone, so a text without tags or glosses simply gets fewer drills.
"""

from __future__ import annotations

import sqlite3

from . import patterns
from .drills import Candidate, Forms, _neutral, _seed, form_key, form_person, headword
from .normalize import drill_key, fold, utf16_len

LIMITS = {"words": 6, "verbs": 6, "say": 5}
CORE = 3  # the first drills of each strand are the Short session's
CONTENT_POS = {"NOUN", "ADJ", "ADV", "VERB"}
TYPED_WORD_POS = {"NOUN", "ADJ", "ADV"}
AUXILIARIES = {"essere", "avere", "stare", "sein", "haben", "werden"}
NEW_WORDS = 6
LANGUAGE_NAME = {"it": "Italian", "de": "German"}
INFINITIVE_HINT = {"it": "Italian infinitives end in -are, -ere or -ire.",
                   "de": "German infinitives end in -en or -n."}
# The person a person-switch drill asks for.
SWITCH = {"1s": "1p", "2s": "2p", "3s": "3p", "1p": "1s", "2p": "2s", "3p": "3s"}
# Functions too close to tell apart in a role-play: a reply from one of these never stands as the
# wrong chip for another.
CLOSE = [
    {"accept", "agree", "confirm", "thank", "reassure", "ask-permission"},
    {"greet", "say-goodbye", "wish-well", "thank", "reply-thanks"},
    {"ask-time", "ask-plans", "ask-what-if", "ask-why", "ask-availability"},
    {"invite", "suggest", "propose-politely", "offer-help", "ask-help"},
    {"say-time", "say-price", "explain"},
    {"say-wish", "state-preference", "describe-wish", "give-opinion", "express-doubt", "order"},
]


# Functions of buying and ordering; the rest are social. A role-play's wrong chips come from the kind
# its dialogue isn't, so they are wrong at any turn: "Quanto costa?" in a chat about plans.
TRANSACTION = {"order", "offer-service", "ask-price", "say-price", "give-something", "ask-choice",
               "ask-availability"}
# Formulas that fit almost any turn, so they never stand as a wrong chip.
ANY_TURN = {"thank", "reply-thanks", "greet", "say-goodbye", "wish-well", "agree", "accept", "say-unsure",
            "state-preference", "confirm", "give-opinion"}


def language_of(text: dict) -> str:
    return "de" if text["id"].startswith("de:") else "it"


def _bare(fid: str) -> str:
    return fid.split(":")[-1]


def _close(a: str, b: str) -> bool:
    a, b = _bare(a), _bare(b)
    return a == b or any(a in group and b in group for group in CLOSE)


def short_gloss(gloss: str) -> str:
    """A sense gloss as a short option: the first meaning, without notes in brackets."""
    g = gloss.split(";")[0].split("(")[0].strip().rstrip(",.:")
    if len(g) > 40:
        g = g[:40].rsplit(" ", 1)[0]
    return g


class Lexicon:
    """What the strands need from the content database, cached; empty answers without one."""

    def __init__(self, conn: sqlite3.Connection | None):
        self.conn = conn
        self._lemma: dict[str, tuple | None] = {}
        self._senses: dict[str, list[tuple[str, str]]] = {}

    def lemma(self, lemma_id: str) -> tuple | None:
        """(headword, pos, freq_rank) of a lemma."""
        if self.conn is None:
            return None
        if lemma_id not in self._lemma:
            self._lemma[lemma_id] = self.conn.execute(
                "SELECT headword, pos, freq_rank FROM lemma WHERE id = ?", (lemma_id,)).fetchone()
        return self._lemma[lemma_id]

    def senses(self, lemma_id: str) -> list[tuple[str, str]]:
        """(sense ID, gloss) of a lemma's current senses, in order."""
        if self.conn is None:
            return []
        if lemma_id not in self._senses:
            self._senses[lemma_id] = self.conn.execute(
                "SELECT id, gloss FROM sense WHERE lemma_id = ? AND retired = 0 ORDER BY ord", (lemma_id,)).fetchall()
        return self._senses[lemma_id]

    def gloss(self, lemma_id: str, sense_id: str | None) -> str | None:
        for sid, gloss in self.senses(lemma_id):
            if sid == sense_id:
                return gloss
        senses = self.senses(lemma_id)
        return senses[0][1] if senses and not sense_id else None

    def word(self, lemma_id: str) -> str:
        row = self.lemma(lemma_id)
        return row[0] if row else headword(lemma_id)


def _sentences(text: dict):
    for block in text["blocks"]:
        for s in block["sentences"]:
            yield block, s


def _compound_tokens(sentence: dict, compound_tenses: set[str]) -> set[int]:
    return {i for u in sentence.get("units", []) if form_key(u.get("form") or "") in compound_tenses
            for i in u["tokens"]}


# --- Words -------------------------------------------------------------------------------

def new_words(text: dict, lex: Lexicon, known_rank: int | None) -> list[dict]:
    """The text's new words, in order: content words with a meaning in context and a frequency rank past
    what the level knows (or none), plus every word the text glosses by hand. One per lemma."""
    out: list[dict] = []
    seen: set[str] = set()
    for _, s in _sentences(text):
        units = {i for u in s.get("units", []) for i in u["tokens"]}
        for i, tok in enumerate(s["tokens"]):
            lemma_id = tok.get("lemmaID")
            if not lemma_id or tok.get("pos") not in CONTENT_POS or i in units or lemma_id in seen:
                continue
            if headword(lemma_id) in AUXILIARIES or tok.get("pos") == "AUX":
                continue
            row = lex.lemma(lemma_id)
            rank = row[2] if row else None
            hand = tok.get("gloss")
            gloss = hand or lex.gloss(lemma_id, tok.get("senseID"))
            if not gloss:
                continue
            if not hand and known_rank is not None and rank is not None and rank <= known_rank:
                continue
            seen.add(lemma_id)
            out.append({"lemmaID": lemma_id, "senseID": tok.get("senseID"), "word": lex.word(lemma_id),
                        "surface": tok["t"], "gloss": short_gloss(gloss), "pos": tok["pos"], "sentence": s["id"],
                        "r": tok["r"]})
            if len(out) == NEW_WORDS:
                return out
    return out


def words_strand(text: dict, words: list[dict], lex: Lexicon) -> list[Candidate]:
    out: list[Candidate] = []
    lang = language_of(text)
    topic = "de:words" if lang == "de" else "words"
    glosses = [w["gloss"] for w in words]

    # sense-choice: the meaning here, against the lemma's other senses and the text's other new words
    for w in words:
        if sum(1 for c in out if c.recipe == "sense-choice") == 2:
            break
        others = [short_gloss(g) for sid, g in lex.senses(w["lemmaID"]) if sid != w["senseID"]]
        others = [g for g in dict.fromkeys(others) if g and fold(g) != fold(w["gloss"])][:2]
        same_lemma = set(others)
        pool = [g for g in glosses if g != w["gloss"] and g not in others]
        others += sorted(pool, key=lambda g: _seed(w["lemmaID"], g))[: 2 - len(others)]
        if len(others) < 2:
            continue
        options = _neutral([w["gloss"]] + others, w["lemmaID"])
        near = {fold(o): (f"That's another meaning of {w['word']}. Read the sentence again." if o in same_lemma
                          else f"That's {next(x['word'] for x in words if x['gloss'] == o)}.") for o in others}
        out.append(Candidate("sense-choice", topic, w["sentence"], {
            "kind": "choice", "prompt": "What does it mean here?", "focus": w["r"], "cue": w["surface"],
            "options": options, "answers": [w["gloss"]], "near": near, "optionLang": "en", "lemma": w["lemmaID"],
            "rule": f"{w['surface']}: {w['gloss']}."}))

    # gloss-match: up to four new words to their meanings
    pairs = [w for w in words if w["gloss"] not in {x["gloss"] for x in words if x is not w}][:4]
    if len(pairs) >= 3:
        out.append(Candidate("gloss-match", topic, pairs[0]["sentence"], {
            "kind": "match", "prompt": "Match each word to its meaning.",
            "pairs": [[w["word"], w["gloss"]] for w in pairs], "sentences": [w["sentence"] for w in pairs],
            "optionLang": "en", "rule": "; ".join(f"{w['word']}: {w['gloss']}" for w in pairs) + "."}))

    # word-recall: the meaning as the cue, the word typed into its sentence
    typed = [w for w in words if w["pos"] in TYPED_WORD_POS and len(w["surface"]) >= 3]
    for w in typed[:2]:
        s = _sentence(text, w["sentence"])
        out.append(Candidate("word-recall", topic, w["sentence"], {
            "kind": "gap", "prompt": "Type the word.", **_gap_at(s, w["r"]), "cue": w["gloss"],
            "answers": [w["surface"]], "lemma": w["lemmaID"],
            "hint": f"It starts with {w['surface'][:1].lower()}.", "rule": f"{w['surface']}: {w['gloss']}."}))

    # dictation-word: a word heard and typed
    asked = {c.drill.get("lemma") for c in out}
    heard = sorted((w for w in words if len(w["surface"]) >= 4), key=lambda w: w["lemmaID"] in asked)
    for w in heard[:1]:
        s = _sentence(text, w["sentence"])
        out.append(Candidate("dictation-word", topic, w["sentence"], {
            "kind": "listen", "prompt": "Listen and type the word.", **_gap_at(s, w["r"]), "speak": w["surface"],
            "answers": [w["surface"]], "lemma": w["lemmaID"],
            "hint": f"It has {len(w['surface'])} letters.", "rule": f"{w['surface']}: {w['gloss']}."}))
    return out


def _sentence(text: dict, sid: str) -> dict:
    return next(s for _, s in _sentences(text) if s["id"] == sid)


def _gap_at(sentence: dict, r: list[int]) -> dict:
    from .drills import _gap
    g = _gap(sentence, *r)
    g.pop("surface", None)
    return g


# --- Verbs -------------------------------------------------------------------------------

def verb_tokens(text: dict, recipes) -> list[tuple[dict, int, dict]]:
    """(sentence, token index, token) of each verb form the strand can label, one per lemma, in text
    order, auxiliaries last."""
    found: list[tuple[dict, int, dict]] = []
    seen: set[str] = set()
    for _, s in _sentences(text):
        compound = _compound_tokens(s, recipes.COMPOUND_TENSES)
        for i, tok in enumerate(s["tokens"]):
            tag = tok.get("form") or ""
            lemma_id = tok.get("lemmaID")
            if i in compound or not lemma_id or lemma_id in seen or tok.get("pos") not in ("VERB", "AUX"):
                continue
            if form_key(tag) not in recipes.TENSE_LABEL or form_person(tag) not in recipes.PERSONS:
                continue
            seen.add(lemma_id)
            found.append((s, i, tok))
    return sorted(found, key=lambda x: headword(x[2]["lemmaID"]) in AUXILIARIES)


def _label(recipes, key: str, person: str) -> str:
    return f"{recipes.TENSE_LABEL[key]}, {recipes.PERSON_LABEL[person]}"


def verbs_strand(text: dict, recipes, forms: Forms, introduces: list[str],
                 topics: dict | None = None) -> tuple[list[Candidate], list[dict]]:
    """The Verbs drills, and the verbs for the strand's intro. Wrong tenses come only from tenses the
    text's level has met (their grammar topic's level), so an A1 learner never sees the Konjunktiv I."""
    lang = language_of(text)
    level = text.get("level", "B2")
    if topics is not None:
        known = {k for k, t in recipes.FORM_TOPIC.items() if t in topics and topics[t].level <= level}
        recipes = _Labels(recipes, {k: v for k, v in recipes.TENSE_LABEL.items() if k in known})
    verbs = verb_tokens(text, recipes)
    # Forms of the tense the text introduces come first: the session shows them after its grammar intro.
    verbs.sort(key=lambda v: recipes.FORM_TOPIC.get(form_key(v[2]["form"])) not in introduces)
    out: list[Candidate] = []
    intro: list[dict] = []
    for s, i, tok in verbs:
        intro.append({"lemmaID": tok["lemmaID"], "word": headword(tok["lemmaID"]), "surface": tok["t"],
                      "form": tok["form"], "sentence": s["id"], "r": tok["r"]})
    for s, i, tok in verbs:
        if sum(1 for c in out if c.recipe == "form-identify") == 2:
            break
        c = _form_identify(s, tok, recipes, forms)
        if c:
            out.append(c)
    for s, i, tok in verbs:
        c = _tense_row(s, tok, recipes, forms)
        if c:
            out.append(c)
            break
    for s, i, tok in verbs:
        c = _person_switch(s, tok, recipes, forms)
        if c:
            out.append(c)
            break
    recalled = 0
    for s, i, tok in verbs:
        word = headword(tok["lemmaID"])
        if recalled == 2 or fold(tok["t"]) == fold(word) or word in AUXILIARIES:
            continue
        recalled += 1
        out.append(Candidate("lemma-recall", _topic(recipes, tok), s["id"], {
            "kind": "gap", "prompt": "Type the infinitive.", "focus": tok["r"], "cue": tok["t"], "answers": [word],
            "lemma": tok["lemmaID"], "hint": INFINITIVE_HINT[lang], "rule": f"{tok['t']} → {word}."}))
    return out, intro[:6]


class _Labels:
    """A language's recipes with fewer tense labels."""

    def __init__(self, recipes, tense_label: dict[str, str]):
        self._recipes = recipes
        self.TENSE_LABEL = tense_label

    def __getattr__(self, name):
        return getattr(self._recipes, name)


def _topic(recipes, tok: dict) -> str:
    return recipes.FORM_TOPIC.get(form_key(tok["form"]), "")


def _form_identify(s: dict, tok: dict, recipes, forms: Forms) -> Candidate | None:
    key, person = form_key(tok["form"]), form_person(tok["form"])
    lemma_forms = forms.of(tok["lemmaID"])
    if not lemma_forms:
        return None
    surface = fold(tok["t"])
    readings = {_label(recipes, form_key(t), form_person(t)) for f, t in lemma_forms
                if fold(f) == surface and form_key(t) in recipes.TENSE_LABEL and form_person(t) in recipes.PERSONS}
    right = _label(recipes, key, person)
    readings.add(right)
    near: dict[str, str] = {}
    by_tag = {}
    for f, t in lemma_forms:
        by_tag.setdefault(t.split("+")[0], f)
    # Another person of the same tense, then the same person in another tense.
    distractors: list[str] = []
    for p in sorted(recipes.PERSONS, key=lambda p: _seed(s["id"], p)):
        label = _label(recipes, key, p)
        f = by_tag.get(f"{key}.{p}")
        if p != person and f and fold(f) != surface and label not in readings:
            distractors.append(label)
            near[fold(label)] = f"Check the person: that would be {f}."
            break
    for k in sorted(recipes.TENSE_LABEL, key=lambda k: _seed(s["id"], k)):
        label = _label(recipes, k, person)
        f = by_tag.get(f"{k}.{person}")
        if k != key and k in recipes.TENSE_LABEL and f and fold(f) != surface and label not in readings:
            distractors.append(label)
            near[fold(label)] = f"Check the tense: that would be {f}."
            break
    if len(distractors) < 2:
        return None
    return Candidate("form-identify", _topic(recipes, tok), s["id"], {
        "kind": "choice", "prompt": "Which form is it?", "focus": tok["r"], "cue": tok["t"],
        "options": _neutral([right] + distractors, s["id"] + tok["t"]), "answers": [right], "near": near,
        "lemma": tok["lemmaID"], "rule": f"{tok['t']}: {headword(tok['lemmaID'])}, {right}."})


def _paradigm(tok: dict, key: str, recipes, forms: Forms) -> dict[str, list[str]] | None:
    """Person -> the forms of a tense, when the database has every person."""
    cells: dict[str, list[str]] = {}
    for f, t in forms.of(tok["lemmaID"]):
        tag = t.split("+")[0]
        if form_key(tag) == key and form_person(tag) in recipes.PERSONS:
            cells.setdefault(form_person(tag), []).append(f)
    if set(cells) != set(recipes.PERSONS):
        return None
    # The text's own form first in its cell, lowercase (a capital only starts its sentence).
    person = form_person(tok["form"])
    own = tok["t"][:1].lower() + tok["t"][1:]
    cells[person] = [own] + [f for f in cells[person] if fold(f) != fold(own)]
    for p in cells:
        rest = sorted(dict.fromkeys(cells[p][1:] if p == person else cells[p]), key=lambda f: (len(f), f))
        cells[p] = ([own] if p == person else []) + rest
    return cells


def _tense_row(s: dict, tok: dict, recipes, forms: Forms) -> Candidate | None:
    key, person = form_key(tok["form"]), form_person(tok["form"])
    if key.startswith("imp."):
        return None
    cells = _paradigm(tok, key, recipes, forms)
    if not cells:
        return None
    word = headword(tok["lemmaID"])
    others = sorted((p for p in recipes.PERSONS if p != person), key=lambda p: _seed(s["id"], word, p))
    given = {person, *others[:2]}
    row = [{"p": p, "label": recipes.PERSON_LABEL[p], "forms": cells[p], "given": p in given} for p in recipes.PERSONS]
    return Candidate("tense-row", _topic(recipes, tok), s["id"], {
        "kind": "row", "prompt": f"Fill in the {recipes.TENSE_LABEL[key]} of {word}.", "focus": tok["r"],
        "cue": word, "tense": recipes.TENSE_LABEL[key], "cells": row, "lemma": tok["lemmaID"],
        "rule": ", ".join(c["forms"][0] for c in row) + "."})


def _person_switch(s: dict, tok: dict, recipes, forms: Forms) -> Candidate | None:
    key, person = form_key(tok["form"]), form_person(tok["form"])
    target = SWITCH[person]
    if key.startswith("imp.") and target == "1s":
        return None
    answers = sorted({f for f, t in forms.of(tok["lemmaID"]) if t.split("+")[0] == f"{key}.{target}"},
                     key=lambda f: (len(f), f))
    if not answers:
        return None
    word = headword(tok["lemmaID"])
    label = recipes.PERSON_LABEL[target]
    return Candidate("person-switch", _topic(recipes, tok), s["id"], {
        "kind": "gap", "prompt": f"Say it for {label}.", "focus": tok["r"], "cue": f"{word}, {label}",
        "answers": answers, "near": {drill_key(tok["t"], _topic(recipes, tok)): f"That's still {recipes.PERSON_LABEL[person]}."},
        "lemma": tok["lemmaID"], "rule": f"{word}, {recipes.TENSE_LABEL[key]}, {label}: {answers[0]}."})


# --- Grammar: find -------------------------------------------------------------------------

def find_forms(text: dict, topic: str, title: str, recipes) -> Candidate | None:
    """Tap every form of the introduced tense, in up to five lines of the text."""
    keys = {k for k, t in recipes.FORM_TOPIC.items() if t == topic}
    if not keys:
        return None
    lines: list[tuple[dict, list[int]]] = []
    for _, s in _sentences(text):
        hits: list[int] = []
        for u in s.get("units", []):
            if form_key(u.get("form") or "") in keys and topic in (u.get("grammar") or [topic]):
                hits += sorted(u["tokens"])
        covered = {i for u in s.get("units", []) for i in u["tokens"]}
        hits += [i for i, t in enumerate(s["tokens"]) if i not in covered and form_key(t.get("form") or "") in keys
                 and form_person(t.get("form") or "") and t.get("pos") in ("VERB", "AUX")]
        lines.append((s, sorted(set(hits))))
    with_hits = [n for n, (_, h) in enumerate(lines) if h]
    if sum(len(lines[n][1]) for n in with_hits) < 2:
        return None
    shown = with_hits[:4]
    without = [n for n, (_, h) in enumerate(lines) if not h and len(lines[n][0]["tokens"]) > 3]
    if without:
        first = min(without, key=lambda n: (abs(n - shown[0]), n))
        shown = sorted(shown + [first])
    shown_lines = [lines[n] for n in shown]
    targets = [{"s": s["id"], "t": i} for s, hits in shown_lines for i in hits]
    forms = [s["tokens"][i]["t"] for s, hits in shown_lines for i in hits]
    return Candidate("find-forms", topic, shown_lines[0][0]["id"], {
        "kind": "find", "prompt": f"Tap every word of the {title.lower()}.", "sentences": [s["id"] for s, _ in shown_lines],
        "targets": targets, "hint": f"There are {len(targets)}.", "rule": ", ".join(forms) + "."})


# --- Say it ------------------------------------------------------------------------------

def tagged_lines(text: dict, inventory: dict) -> list[tuple[dict, dict, str]]:
    """(block, sentence, function ID) of each sentence tagged with a function the inventory has."""
    out = []
    for block, s in _sentences(text):
        for fid in s.get("fn", []):
            if fid in inventory:
                out.append((block, s, fid))
                break
    return out


def say_strand(text: dict, inventory: dict) -> tuple[list[Candidate], list[dict]]:
    """The Say it drills, and the functions for the strand's intro."""
    lines = tagged_lines(text, inventory)
    if not lines:
        return [], []
    lang = language_of(text)
    topic = "de:functions" if lang == "de" else "functions"
    level = text.get("level", "B2")
    used = list(dict.fromkeys(fid for _, _, fid in lines))
    at_level = [f for f in inventory.values() if f.level <= level]
    out: list[Candidate] = []

    # function-pick: what a line does
    picked: set[str] = set()
    for block, s, fid in lines:
        if len(picked) == 2:
            break
        if fid in picked:
            continue
        pool = [f for f in used if not _close(f, fid)] + \
            sorted((f.id for f in at_level if f.id not in used and not _close(f.id, fid)), key=lambda x: _seed(s["id"], x))
        wrong = list(dict.fromkeys(pool))[:2]
        if len(wrong) < 2:
            continue
        picked.add(fid)
        names = {f: inventory[f].name for f in [fid] + wrong}
        who = block.get("speaker")
        near = {fold(names[f]): (f"Not here. {names[f]} would sound like «{inventory[f].phrases[0]}»."
                                 if inventory[f].phrases else "Not here. Read the line again.") for f in wrong}
        out.append(Candidate("function-pick", topic, s["id"], {
            "kind": "choice", "prompt": f"What is {who} doing here?" if who else "What does this sentence do?",
            "focus": [0, utf16_len(s["text"])], "options": _neutral(list(names.values()), s["id"]),
            "answers": [names[fid]], "near": near, "optionLang": "en", "function": fid,
            "rule": f"«{s['text']}»: {names[fid].lower()}."}))

    # function-match: short lines to what they do
    short = []
    for _, s, fid in lines:
        if len(s["text"].split()) <= 7 and fid not in {f for _, f in short}:
            short.append((s, fid))
    if len(short) >= 3:
        short = short[:4]
        out.append(Candidate("function-match", topic, short[0][0]["id"], {
            "kind": "match", "prompt": "Match each line to what it does.",
            "pairs": [[s["text"], inventory[fid].name] for s, fid in short], "sentences": [s["id"] for s, _ in short],
            "optionLang": "en", "rule": "; ".join(f"{s['text']} → {inventory[fid].name.lower()}" for s, fid in short) + "."}))

    # function-say: the line from its English, any way the patterns allow
    said = 0
    for n, (block, s, fid) in enumerate(lines):
        if said == 1 or len(s["text"].split()) > 7:
            continue
        said += 1
        accept = [s["text"]] + s.get("accept", [])
        also = [p for p in inventory[fid].phrases if fold(p) not in {fold(x) for a in accept for x in patterns.expand(a)}][:3]
        out.append(Candidate("function-say", topic, s["id"], {
            "kind": "say", "prompt": f"Say it in {LANGUAGE_NAME[lang]}.", "cue": s["translation"],
            "label": inventory[fid].name, "answers": [s["text"]], "accept": accept, "also": also, "function": fid,
            "hint": f"It starts with «{s['text'].split()[0].strip('«»,.!?')}».", "rule": s["text"]}))

    play = roleplay(text, inventory)
    if play:
        out.append(play)
    intro = [{"id": f, "name": inventory[f].name, "label": inventory[f].label} for f in used]
    return out, intro


def roleplay(text: dict, inventory: dict) -> Candidate | None:
    """One side of the text's dialogue: the learner plays the speaker with the most tagged lines."""
    turns_src = [b for b in text["blocks"] if b["type"] == "dialogue" and b.get("speaker")]
    speakers = list(dict.fromkeys(b["speaker"] for b in turns_src))
    if len(speakers) != 2 or len(turns_src) < 4:
        return None
    tagged = {sp: sum(1 for b in turns_src if b["speaker"] == sp for s in b["sentences"]
                      if any(f in inventory for f in s.get("fn", []))) for sp in speakers}
    learner = max(reversed(speakers), key=lambda sp: tagged[sp])
    if tagged[learner] < 2:
        return None
    other = next(sp for sp in speakers if sp != learner)
    level = text.get("level", "B2")
    in_text = {f for b in turns_src for s in b["sentences"] for f in s.get("fn", [])}
    shop = sum(_bare(f) in TRANSACTION for f in in_text) >= 3
    turns: list[dict] = []
    goals: list[dict] = []
    mine = 0
    for b in turns_src:
        sids = [s["id"] for s in b["sentences"]]
        if b["speaker"] != learner:
            turns.append({"who": other, "s": sids})
            continue
        if mine == 6:
            break
        mine += 1
        fns = [f for s in b["sentences"] for f in s.get("fn", []) if f in inventory]
        goal = fns[0] if fns else None
        if goal and goal not in {g["id"] for g in goals}:
            goals.append({"id": goal, "label": inventory[goal].goal.replace("them", other)})
        seed = text["id"] + sids[0]
        pool = sorted((f for f in inventory.values() if f.level <= level and f.phrases and f.id not in in_text
                       and _bare(f.id) not in ANY_TURN and (_bare(f.id) in TRANSACTION) != shop), key=lambda f: _seed(seed, f.id))
        wrong = [f.phrases[_seed(seed, f.id) % len(f.phrases)] for f in pool[:2]]
        if len(wrong) < 2:
            return None
        line = b["text"]
        # Each sentence of the line as itself or any of its patterns, in order.
        accept = " ".join("{" + "|".join([x["text"]] + x["accept"]) + "}" if x.get("accept") else x["text"]
                          for x in b["sentences"])
        turn = {"who": learner, "s": sids, "chips": _neutral([line] + wrong, seed), "answers": [line],
                "accept": [accept]}
        if goal:
            turn["goal"] = goal
        turns.append(turn)
    lang = language_of(text)
    return Candidate("roleplay", "de:functions" if lang == "de" else "functions", turns_src[0]["sentences"][0]["id"], {
        "kind": "roleplay", "prompt": f"You're {learner}. Talk to {other}.", "speaker": learner, "other": other,
        "goals": goals, "turns": turns, "rule": f"The whole conversation, as {learner}."})


# --- checks ------------------------------------------------------------------------------

def validate(text: dict, d: dict) -> list[str]:
    """Errors in one strand drill; drills.validate calls it for the kinds it adds."""
    errors: list[str] = []
    where = f"{text['id']} {d['id']}"
    sentences = {s["id"]: s for _, s in _sentences(text)}
    kind = d["kind"]
    if kind == "find":
        shown = set(d["sentences"])
        if any(t["s"] not in shown or t["t"] >= len(sentences[t["s"]]["tokens"]) for t in d["targets"]):
            errors.append(f"{where}: a target is not in the lines shown")
        if len(d["targets"]) < 2:
            errors.append(f"{where}: fewer than two targets")
    elif kind == "row":
        if not any(not c["given"] for c in d["cells"]) or not all(c["forms"] for c in d["cells"]):
            errors.append(f"{where}: a row needs blank cells and a form in every cell")
    elif kind == "say":
        accepted = {fold(x) for p in d["accept"] for x in patterns.expand(p)}
        if fold(d["answers"][0]) not in accepted:
            errors.append(f"{where}: the patterns don't accept the text's own line")
    elif kind == "roleplay":
        for t in d["turns"]:
            if "chips" not in t:
                continue
            if t["chips"].count(t["answers"][0]) != 1 or len(set(t["chips"])) != len(t["chips"]):
                errors.append(f"{where}: a turn's chips must hold its line once and no repeats")
            try:
                accepted = {fold(x) for p in t["accept"] for x in patterns.expand(p)}
            except patterns.PatternError as exc:
                errors.append(f"{where}: {exc}")
                continue
            if fold(t["answers"][0]) not in accepted:
                errors.append(f"{where}: a turn's patterns don't accept its line")
    return errors
