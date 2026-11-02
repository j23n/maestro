"""German linking for text packs (HANDOFF.md 6.3, 6.5).

packs.build_text calls `link_sentence` here for a German text. On top of what the Italian linker does,
it works out:

- case, gender and number (`case`, `gn`) of each noun phrase, from its noun, adjectives, determiner
  and preposition together, and the adjectives' declension (`decl`);
- contractions as multiword tokens (zum = zu + dem);
- which form a verb is from its place in the clause (V2, verb-final after a subordinator) and its
  subject pronoun;
- separable verbs (rufe … an) and compound tenses (habe … gegessen, werde … essen, würde … essen)
  as units.

A source can name a case the linker can't work out with a hint on the noun: Frau{acc}, Haus{dat.ns}.

Clauses joined by und or oder without a comma are split only in the simple cases: a subject pronoun, or
a determiner and one capitalized word, then the finite verb (und wir essen, und die Frau isst); or one
word, the finite verb and a subject pronoun (und dann essen wir). A longer subject (und die alte Frau
isst) stays in the clause before.
Two cases are known limits. A longer opening (und am Abend essen wir) stays in the clause before, which a
comma before und settles. A verb-final clause joined by und with words after its verbs (weil ich
koche und wir essen wollen wie immer) reads as a main clause.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import packs
from .normalize import utf16_len

CASES = ("nom", "acc", "dat", "gen")

# Prepositions and the cases they take. Two-way prepositions take the accusative for a direction
# and the dative for a place.
PREP_CASES: dict[str, set[str]] = {
    **{p: {"dat"} for p in ("aus", "bei", "mit", "nach", "seit", "von", "zu", "gegenüber", "ab")},
    **{p: {"acc"} for p in ("durch", "für", "gegen", "ohne", "um", "bis")},
    **{p: {"acc", "dat"} for p in ("an", "auf", "hinter", "in", "neben", "über", "unter", "vor", "zwischen")},
    **{p: {"gen", "dat"} for p in ("wegen", "trotz")},
    **{p: {"gen"} for p in ("während", "statt", "innerhalb", "außerhalb")},
}
TWO_WAY = {p for p, c in PREP_CASES.items() if c == {"acc", "dat"}}

# Contraction -> (preposition, article)
CONTRACTIONS = {
    "zum": ("zu", "dem"), "zur": ("zu", "der"), "im": ("in", "dem"), "ins": ("in", "das"), "am": ("an", "dem"),
    "ans": ("an", "das"), "vom": ("von", "dem"), "beim": ("bei", "dem"), "aufs": ("auf", "das"),
    "fürs": ("für", "das"), "durchs": ("durch", "das"), "ums": ("um", "das"),
}

Slot = tuple[str, str]  # (case, gender-number), such as ("dat", "ns")


def _slots(*tags: str) -> frozenset[Slot]:
    return frozenset(tuple(t.split(".")) for t in tags)  # type: ignore[misc]


DEFINITE = {
    "der": _slots("nom.ms", "dat.fs", "gen.fs", "gen.pl"),
    "die": _slots("nom.fs", "acc.fs", "nom.pl", "acc.pl"),
    "das": _slots("nom.ns", "acc.ns"),
    "den": _slots("acc.ms", "dat.pl"),
    "dem": _slots("dat.ms", "dat.ns"),
    "des": _slots("gen.ms", "gen.ns"),
}
# Endings of ein-words (ein, kein, mein, …) and der-words (dieser, jeder, …).
EIN_ENDINGS = {
    "": _slots("nom.ms", "nom.ns", "acc.ns"),
    "e": _slots("nom.fs", "acc.fs", "nom.pl", "acc.pl"),
    "en": _slots("acc.ms", "dat.pl"),
    "em": _slots("dat.ms", "dat.ns"),
    "er": _slots("dat.fs", "gen.fs", "gen.pl"),
    "es": _slots("gen.ms", "gen.ns"),
}
DER_ENDINGS = {
    "er": _slots("nom.ms", "dat.fs", "gen.fs", "gen.pl"),
    "e": _slots("nom.fs", "acc.fs", "nom.pl", "acc.pl"),
    "es": _slots("nom.ns", "acc.ns", "gen.ms", "gen.ns"),
    "en": _slots("acc.ms", "dat.pl"),
    "em": _slots("dat.ms", "dat.ns"),
}
# Stem -> headword. `eur` is euer without its e (eure, euren).
EIN_STEMS = {"ein": "ein", "kein": "kein", "mein": "mein", "dein": "dein", "sein": "sein", "ihr": "ihr",
             "unser": "unser", "eur": "euer"}
DER_STEMS = {"dies": "dieser", "jed": "jeder", "welch": "welcher", "jen": "jener", "manch": "mancher"}
# Bare forms that are also something else: sein (to be), ihr (you, her).
AMBIGUOUS_DETERMINERS = {"sein", "ihr"}

# Personal pronouns: surface -> (headword, case when the form has only one)
PRONOUNS: dict[str, tuple[str, str | None]] = {
    "ich": ("ich", "nom"), "mich": ("ich", "acc"), "mir": ("ich", "dat"),
    "du": ("du", "nom"), "dich": ("du", "acc"), "dir": ("du", "dat"),
    "er": ("er", "nom"), "ihn": ("er", "acc"), "ihm": ("er", "dat"),
    "es": ("es", None), "sie": ("sie", None), "ihnen": ("sie", "dat"),
    "wir": ("wir", "nom"), "uns": ("wir", None), "euch": ("ihr", None),
    "man": ("man", "nom"), "sich": ("sich", None), "ihr": ("ihr", None),
}
# Subject pronoun -> the persons its verb can have. Sie inside a sentence is the polite you (3p).
SUBJECT_PERSONS = {"ich": {"1s"}, "du": {"2s"}, "er": {"3s"}, "es": {"3s"}, "man": {"3s"}, "sie": {"3s", "3p"},
                   "wir": {"1p"}, "ihr": {"2p"}}

CCONJ = {"und", "oder", "aber", "denn", "sondern", "doch"}
SCONJ = {"dass", "weil", "wenn", "ob", "obwohl", "als", "bevor", "nachdem", "damit", "seit", "seitdem", "bis",
         "sobald", "solange", "falls", "während"}
ADVERBS = {"nicht": "nicht", "auch": "auch", "sehr": "sehr", "noch": "noch", "schon": "schon", "gern": "gern",
           "gerne": "gern", "hier": "hier", "dort": "dort", "da": "da", "jetzt": "jetzt", "dann": "dann"}
AUXILIARIES = {"haben", "sein", "werden"}
# Verbs whose dependent verb is an infinitive (werden: Futur I, würde-Form), not a participle.
TAKES_INFINITIVE = {"werden", "können", "müssen", "wollen", "sollen", "dürfen", "mögen", "möchten", "lassen"}
MODALS = {"können", "müssen", "wollen", "sollen", "dürfen", "mögen", "möchten"}
# Separable prefixes that stand alone at the end of a main clause.
PARTICLES = {"ab", "an", "auf", "aus", "bei", "ein", "fest", "fort", "her", "hin", "los", "mit", "nach", "vor",
             "weg", "zu", "zurück", "zusammen", "weiter", "fern", "heim", "teil", "statt", "vorbei", "herein",
             "hinaus", "heraus", "hinein", "kennen", "spazieren", "frei", "um", "durch", "wieder", "dabei"}
CLOSING_QUOTES = {"“", "”", "«", "»", "\"", "‘", "’"}
CLAUSE_BREAK = {",", ";", ":", ".", "!", "?", "–", "—", "(", ")", "«", "»", "„", "“", "\""}
SENTENCE_START = {".", "!", "?", "«", "\"", "—", ":", "„", "»", "“"}

MOOD_RANK = {"ind": 0, "k2": 1, "imp": 2, "k1": 3}
PERSON_RANK = {"3s": 0, "1s": 1, "3p": 2, "1p": 3, "2s": 4, "2p": 5}
COMPOUND = {("haben", "ind.pres"): "ind.perf", ("sein", "ind.pres"): "ind.perf",
            ("haben", "ind.prat"): "ind.pqp", ("sein", "ind.prat"): "ind.pqp",
            ("haben", "k2.prat"): "k2.pqp", ("sein", "k2.prat"): "k2.pqp"}
FUTURE = {"ind.pres": "ind.fut1", "k2.prat": "k2.wuerde"}
TOPIC = {"ind.perf": "de:perfekt", "k2.pqp": "de:konjunktiv-2", "k2.wuerde": "de:konjunktiv-2"}
CASE_TOPIC = {"acc": "de:akkusativ", "dat": "de:dativ"}
SEPARABLE_TOPIC = "de:trennbare-verben"
VERB_LAST_TOPIC = "de:nebensaetze"
REFLEXIVE_TOPIC = "de:reflexive-verben"
WORD_ORDER_TOPIC = "de:verbstellung"
NEGATION_TOPIC = "de:negation"
POSSESSIVE_TOPIC = "de:possessivartikel"
TIME_TOPIC = "de:praepositionen-zeit"
COMPARISON_TOPIC = "de:komparation"
ADJECTIVE_TOPIC = "de:adjektivdeklination"
TIME_PREPOSITIONS = {"um", "am", "im", "von", "bis", "seit", "ab", "vor", "nach", "in"}
TIME_WORDS = {"Uhr", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag", "Morgen",
              "Vormittag", "Mittag", "Nachmittag", "Abend", "Nacht", "Wochenende", "Januar", "Februar", "März",
              "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember", "Frühling",
              "Sommer", "Herbst", "Winter", "Jahr", "Monat", "Woche", "Tag", "Stunde", "Minute", "Mittagessen",
              "Abendessen", "Frühstück"}
POSSESSIVE_HEADWORDS = {"mein", "dein", "sein", "ihr", "unser", "euer"}
VERB_LAST_TOPIC_WORDS = {"dass", "weil", "wenn", "ob"}
TWO_WAY_TOPIC = "de:wechselpraepositionen"


@dataclass
class Info:
    """What the linker knows about one token while it works on the sentence."""
    pos: str | None = None              # our part of speech (v, n, adj, art, det, prep, pron, …)
    lemma: str | None = None
    headword: str | None = None
    tags: list[str] = field(default_factory=list)  # every tag the surface has for this lemma
    slots: frozenset[Slot] | None = None  # determiner: the case-gender-number slots it fits
    det: str | None = None              # "der" (definite and der-words) or "ein" (ein-words)
    prep: set[str] | None = None        # preposition or contraction: the cases it takes
    case_hint: str | None = None
    unresolved: bool = False            # no dictionary match yet; a unit may still claim it


def is_finite(tag: str) -> bool:
    return tag.split(".")[0] in MOOD_RANK and tag.count(".") >= 2


def person(tag: str) -> str | None:
    parts = tag.split("+")[0].split(".")
    return parts[2] if len(parts) == 3 else None


def determiner(lower: str) -> tuple[str, str, frozenset[Slot]] | None:
    """(headword, kind, slots) for a determiner's surface: der, die, einem, meine, dieses, …"""
    if lower in DEFINITE:
        return "der", "der", DEFINITE[lower]
    if lower == "euer":
        return "euer", "ein", EIN_ENDINGS[""]
    for stem, headword in EIN_STEMS.items():
        if lower.startswith(stem) and lower[len(stem):] in EIN_ENDINGS:
            if stem == "eur" and lower == "eur":
                return None
            slots = EIN_ENDINGS[lower[len(stem):]]
            if stem == "ein":
                slots = frozenset(s for s in slots if s[1] != "pl")
            return headword, "ein", slots
    for stem, headword in DER_STEMS.items():
        if lower.startswith(stem) and lower[len(stem):] in DER_ENDINGS:
            return headword, "der", DER_ENDINGS[lower[len(stem):]]
    return None


def _lemma(lex: packs.Lexicon, headword: str, *pos: str) -> tuple[str | None, str]:
    for p in pos:
        lemma_id = lex.lemma(headword, p)
        if lemma_id:
            return lemma_id, p
    return None, pos[0]


def _candidates(lex: packs.Lexicon, surface: str, sentence_start: bool) -> list[tuple[str, str, str, str]]:
    """Exact spelling first. Only a lowercase word or the sentence's first word falls back to lowercase:
    German capitalises nouns, so a capitalised word inside a sentence is a noun or a name."""
    rows = lex.conn.execute(
        "SELECT f.lemma_id, f.tag, l.pos, l.headword FROM form f JOIN lemma l ON l.id = f.lemma_id "
        "WHERE f.form = ? AND l.retired = 0", (surface,)).fetchall()
    if not rows and sentence_start and surface != surface.lower():
        rows = lex.conn.execute(
            "SELECT f.lemma_id, f.tag, l.pos, l.headword FROM form f JOIN lemma l ON l.id = f.lemma_id "
            "WHERE f.form = ? AND l.retired = 0", (surface.lower(),)).fetchall()
    return rows


def _tags(rows: list[tuple[str, str, str, str]], lemma_id: str) -> list[str]:
    return sorted({tag for lid, tag, _, _ in rows if lid == lemma_id and tag})


def _link(tok: dict, lex: packs.Lexicon, lemma_id: str | None, upos: str, sense: bool = True) -> None:
    tok["pos"] = upos
    if lemma_id:
        tok["lemmaID"] = lemma_id
        if sense:
            sid = lex.first_sense(lemma_id)
            if sid:
                tok["senseID"] = sid


def _reads_as_determiner(lex: packs.Lexicon, surface: str, following: tuple[str, int, int, str],
                         before: list[Info]) -> bool:
    """Whether a word spelled like a determiner is one. sein, ihr and verb look-alikes (meinen) are
    only before a noun, an adjective or a number, and ihr after a verb for ihr (habt ihr) is the pronoun."""
    lower = surface.lower()
    previous = next((x for x in reversed(before) if x.pos is not None), None)
    if lower == "ihr" and previous is not None and previous.pos == "v":
        persons = {person(t) for t in previous.tags}
        if "2p" in persons and "3s" not in persons:
            return False
    if lower not in AMBIGUOUS_DETERMINERS and not _is_verb_form(lex, surface):
        return True
    word = following[0]
    if word.lower() in PRONOUNS or word.lower() in SUBJECT_PERSONS:
        return False
    return word[:1].isupper() or following[3] == "n" or _is_adjective(lex, word)


def _is_verb_form(lex: packs.Lexicon, surface: str) -> bool:
    return lex.conn.execute("SELECT 1 FROM form f JOIN lemma l ON l.id = f.lemma_id WHERE f.form = ? AND l.pos = 'v' "
                            "AND l.retired = 0 LIMIT 1", (surface.lower(),)).fetchone() is not None


def _is_adjective(lex: packs.Lexicon, surface: str) -> bool:
    return lex.conn.execute("SELECT 1 FROM form f JOIN lemma l ON l.id = f.lemma_id WHERE f.form = ? AND l.pos = 'adj' "
                            "AND l.retired = 0 LIMIT 1", (surface,)).fetchone() is not None


def _upos(pos: str | None, headword: str | None, lower: str) -> str:
    """sein and the modal verbs are AUX; haben and werden are AUX only in a compound tense (set later)."""
    if pos == "v" and (headword == "sein" or headword in MODALS):
        return "AUX"
    if pos == "conj":
        return "CCONJ" if lower in CCONJ else "SCONJ"
    return packs.UPOS.get(pos or "", "X")


def link_sentence(lex: packs.Lexicon, sentence: packs.SourceSentence) -> tuple[list[dict], list[dict], list[str]]:
    """Tokens, units and warnings for one German sentence."""
    raw = packs.tokenize(sentence.text)
    tokens: list[dict] = []
    infos: list[Info] = []
    warnings: list[str] = []
    prev_pos: str | None = None
    words = [i for i, r in enumerate(raw) if r[3] != "p"]

    def next_word(idx: int) -> tuple[str, int, int, str] | None:
        return raw[idx + 1] if idx + 1 < len(raw) and raw[idx + 1][3] != "p" else None

    for idx, (surface, start, end, kind) in enumerate(raw):
        tok: dict = {"t": surface, "r": [utf16_len(sentence.text[:start]), utf16_len(surface)]}
        info = Info()
        lower = surface.lower()
        sentence_start = idx == 0 or raw[idx - 1][0] in SENTENCE_START
        hint = sentence.hints.get(end)
        if hint and hint.split(".")[0] in CASES:
            info.case_hint, hint = hint, None
        following = next_word(idx)
        if kind == "p":
            tok["pos"] = "PUNCT"
        elif kind == "n":
            tok["pos"] = "NUM"
            info.pos = "num"
        elif hint:
            lemma_id, pos = packs._lemma_for_hint(lex, hint, surface)
            if lemma_id:
                _link(tok, lex, lemma_id, _upos(pos, None, lower))
                info.pos, info.lemma = pos, lemma_id
                info.headword = hint.split(":")[0] if ":" in hint else None
                info.tags = _tags(_candidates(lex, surface, sentence_start), lemma_id)
            else:
                warnings.append(f"hint {hint!r} on {surface!r} did not resolve")
        elif lower in CONTRACTIONS and following:
            prep, art = CONTRACTIONS[lower]
            p_id, _ = _lemma(lex, prep, "prep")
            a_id, _ = _lemma(lex, "der", "art")
            tok["parts"] = [{"t": prep if surface[0].islower() else prep.capitalize(), "pos": "ADP",
                             **({"lemmaID": p_id} if p_id else {})},
                            {"t": art, "pos": "DET", **({"lemmaID": a_id} if a_id else {})}]
            info.pos, info.det, info.prep = "contr", "der", set(PREP_CASES[prep])
            info.slots = frozenset(s for s in DEFINITE[art] if s[0] in PREP_CASES[prep])
            if prep in TWO_WAY:
                tok["grammar"] = [TWO_WAY_TOPIC]
        elif (det := determiner(lower)) and following and _reads_as_determiner(lex, surface, following, infos):
            headword, det_kind, slots = det
            lemma_id, pos = _lemma(lex, headword, "art", "det", "pron")
            _link(tok, lex, lemma_id, "DET", sense=pos != "art")
            if headword in POSSESSIVE_HEADWORDS:
                tok["grammar"] = [POSSESSIVE_TOPIC]
            elif headword == "kein":
                tok["grammar"] = [NEGATION_TOPIC]
            info.pos, info.lemma, info.headword, info.det, info.slots = pos, lemma_id, headword, det_kind, slots
        elif lower in PREP_CASES and following and not (lower in SCONJ and following[0].lower() in SUBJECT_PERSONS):
            lemma_id, _ = _lemma(lex, lower, "prep")
            _link(tok, lex, lemma_id, "ADP", sense=False)
            info.pos, info.lemma, info.headword, info.prep = "prep", lemma_id, lower, set(PREP_CASES[lower])
            if lower in TWO_WAY:
                tok["grammar"] = [TWO_WAY_TOPIC]
        elif lower in PRONOUNS or (surface in ("Sie", "Ihnen") and not sentence_start):
            if surface in ("Sie", "Ihnen") and not sentence_start:
                headword, case = "Sie", "dat" if surface == "Ihnen" else None
            else:
                headword, case = PRONOUNS[lower]
            lemma_id, _ = _lemma(lex, headword, "pron")
            _link(tok, lex, lemma_id, "PRON")
            info.pos, info.lemma, info.headword = "pron", lemma_id, headword
            if case:
                tok["case"] = case
            if lower == "sich":
                tok["grammar"] = [REFLEXIVE_TOPIC]
        elif lower in CCONJ or lower in SCONJ:
            lemma_id, _ = _lemma(lex, lower, "conj")
            _link(tok, lex, lemma_id, "CCONJ" if lower in CCONJ else "SCONJ", sense=False)
            info.pos, info.lemma, info.headword = "conj", lemma_id, lower
            if lower in VERB_LAST_TOPIC_WORDS:
                tok["grammar"] = [VERB_LAST_TOPIC]
        else:
            rows = _candidates(lex, surface, sentence_start)
            choice = packs._choose(rows, surface, prev_pos, sentence_start)
            if choice is None and lower in ADVERBS:
                lemma_id, _ = _lemma(lex, ADVERBS[lower], "adv")
                choice = (lemma_id, "", "adv", ADVERBS[lower]) if lemma_id else None
            if choice is None:
                info.unresolved = True
                tok["pos"] = "PROPN" if surface[:1].isupper() and not sentence_start else "X"
            else:
                lemma_id, _, pos, headword = choice
                _link(tok, lex, lemma_id, _upos(pos, headword, lower))
                info.pos, info.lemma, info.headword = pos, lemma_id, headword
                info.tags = _tags(rows, lemma_id)
        gloss = sentence.glosses.get(surface)
        if gloss:
            tok["gloss"] = gloss
        tokens.append(tok)
        infos.append(info)
        if kind != "p":
            prev_pos = info.pos

    clauses = _clauses(raw, infos)
    _verb_forms(tokens, infos, clauses)
    _noun_phrases(lex, tokens, infos, words, clauses)
    _single_cases(tokens, infos)
    _topic_tags(tokens, infos, clauses)
    units = _separable_units(lex, tokens, infos, clauses)
    units += _compound_units(lex, tokens, infos, clauses, {i for u in units for i in u["tokens"]})
    units = packs._apply_manual_units(lex, sentence, tokens, sorted(units, key=lambda u: u["tokens"][0]), warnings)
    claimed = {i for u in units for i in u["tokens"] if u.get("lemmaID")}
    for i, info in enumerate(infos):
        if info.unresolved and i not in claimed:
            warnings.append(f"no dictionary match for {tokens[i]['t']!r}")
    return tokens, units, warnings


# --- clauses and verbs ---------------------------------------------------------------------

@dataclass
class Clause:
    words: list[int]        # token indices of the clause's words, in order
    subordinate: bool       # verb-final: opened by a subordinator, or joined by und to one with its verbs last


def _clauses(raw: list[tuple[str, int, int, str]], infos: list[Info]) -> list[Clause]:
    out: list[Clause] = []
    current: list[int] = []
    coordinated: set[int] = set()  # clauses split off at und or oder, which continue the clause before
    for i, (surface, _, _, kind) in enumerate(raw):
        if kind == "p":
            if surface in CLAUSE_BREAK and current:
                out.append(Clause(current, False))
                current = []
            continue
        if current and _starts_coordinated_clause(raw, infos, current, i):
            out.append(Clause(current, False))
            coordinated.add(len(out))
            current = []
        current.append(i)
    if current:
        out.append(Clause(current, False))
    for k, c in enumerate(out):
        if k in coordinated:
            # weil ich koche und wir essen wollen: still verb-final, its verbs all together at the end.
            # Otherwise it's a new main clause (weil ich koche und wir wollen heute essen).
            verbs = [pos for pos, w in enumerate(c.words) if infos[w].pos == "v"]
            verb_final = bool(verbs) and verbs == list(range(len(c.words) - len(verbs), len(c.words)))
            c.subordinate = out[k - 1].subordinate and verb_final
            continue
        first = raw[c.words[0]][0].lower()
        c.subordinate = first in SCONJ and infos[c.words[0]].pos == "conj" or _opens_relative_clause(raw, infos, c)
    return out


RELATIVE = {"der", "die", "das", "dem", "den", "denen", "dessen", "deren"}


def _starts_coordinated_clause(raw: list[tuple[str, int, int, str]], infos: list[Info], current: list[int], i: int) -> bool:
    """ich koche und wir essen: und or oder after a verb, before a subject pronoun, or a determiner and one
    capitalized word, then the finite verb, starts a coordinated clause without a comma (und wir essen, und
    die Frau isst), and so does one word, a finite verb and a subject pronoun (und dann essen wir). _clauses
    decides whether it continues a verb-final clause before it.
    Before the clause has a verb it joins two subjects instead (die Frau und ich essen), and without a
    finite verb after the subject it joins two objects (Brot und eine Suppe gekauft)."""
    if raw[i][0].lower() not in CCONJ or infos[i].pos != "conj" or i + 1 >= len(raw) or raw[i + 1][3] == "p":
        return False
    if not any(infos[k].pos == "v" for k in current):
        return False

    def finite(j: int) -> bool:
        return j < len(raw) and infos[j].pos == "v" and any(is_finite(t) for t in infos[j].tags)

    def subject_pronoun(j: int) -> bool:
        return j < len(raw) and (raw[j][0].lower() in SUBJECT_PERSONS or raw[j][0] == "Sie")

    if subject_pronoun(i + 1):
        return finite(i + 2)
    if finite(i + 2) and subject_pronoun(i + 3) and infos[i + 1].pos != "v":
        return True  # und dann essen wir: inversion after one word
    return infos[i + 1].slots is not None and i + 2 < len(raw) and raw[i + 2][0][:1].isupper() and finite(i + 3)


def _opens_relative_clause(raw: list[tuple[str, int, int, str]], infos: list[Info], clause: Clause) -> bool:
    """das Buch, das ich lese: a der-word after a comma, not followed by its noun or adjective."""
    first = clause.words[0]
    if raw[first][0].lower() not in RELATIVE or first < 2 or raw[first - 1][0] != ",":
        return False
    if infos[first - 2].pos != "n" and not raw[first - 2][0][:1].isupper():
        return False  # ich weiß, das ist gut: no noun for it to refer to
    if len(clause.words) < 2:
        return False
    nxt = clause.words[1]
    return not raw[nxt][0][:1].isupper() and infos[nxt].pos not in ("adj", "num") or raw[nxt][0] == "Sie"


def _subject_persons(tokens: list[dict], infos: list[Info], clause: Clause, at: int) -> set[str] | None:
    """The persons a subject pronoun next to the verb allows (gehst du, du gehst), or after the
    subordinator for a verb at the end of its clause (weil wir … wollen)."""
    pos_in = clause.words.index(at)
    for j in (pos_in - 1, pos_in + 1, *((1,) if clause.subordinate else ())):
        if 0 <= j < len(clause.words):
            k = clause.words[j]
            if infos[k].pos != "pron":
                continue
            surface = tokens[k]["t"]
            if surface == "Sie" and infos[k].headword == "Sie":
                return {"3p"}
            persons = SUBJECT_PERSONS.get(surface.lower())
            if persons:
                return persons
    return None


def _rank(tag: str) -> tuple:
    parts = tag.split(".")
    return (MOOD_RANK.get(parts[0], 9), 0 if parts[1:2] == ["pres"] else 1, PERSON_RANK.get(person(tag) or "", 9), tag)


def _verb_forms(tokens: list[dict], infos: list[Info], clauses: list[Clause]) -> None:
    """Pick each verb's form from its place in the clause.

    In a main clause the first verb is finite and the others are infinitives or participles; after a
    subordinator the last verb is finite. A verb right after zu is an infinitive (um Brot zu kaufen), so
    a clause of zu-infinitives has no finite verb. A verb right after und or oder takes the form of the
    verb before it: finite in "ich esse und trinke", an infinitive in "ich möchte essen und trinken"."""
    for clause in clauses:
        verbs = [i for i in clause.words if infos[i].pos == "v" and infos[i].tags]
        if not verbs:
            continue

        def before(i: int) -> str:
            pos_in = clause.words.index(i)
            return tokens[clause.words[pos_in - 1]]["t"].lower() if pos_in > 0 else ""

        candidates = [i for i in verbs if before(i) != "zu"]
        finite_at = (candidates[-1] if clause.subordinate else candidates[0]) if candidates else None
        lead = infos[finite_at].headword if finite_at is not None else None
        order = ("inf.pres", "inf.zu", "part.pass", "part.pres") if lead in TAKES_INFINITIVE or lead is None else \
            ("part.pass", "inf.pres", "inf.zu", "part.pres")
        previous: str | None = None
        for i in verbs:
            tags = infos[i].tags
            pos_in = clause.words.index(i)
            nonfinite = [t for t in tags if not is_finite(t)]
            finite = [t for t in tags if is_finite(t)]
            if before(i) in CCONJ and previous is not None:
                wants_finite = is_finite(previous)
                like = previous if previous in nonfinite else None
            else:
                wants_finite = i == finite_at
                like = None
            if nonfinite and (not wants_finite or not finite):
                chosen = like or min(nonfinite, key=lambda t: order.index(t) if t in order else 9)
            else:
                persons = _subject_persons(tokens, infos, clause, i)
                if not persons and before(i) in CCONJ and previous and is_finite(previous):
                    persons = {person(previous)}  # wir kaufen und essen: the same subject
                pool = [t for t in finite if person(t) in persons] if persons else finite
                if not persons:
                    imperative = [t for t in finite if t.startswith("imp.")]
                    if imperative and pos_in == 0 and not clause.subordinate:
                        pool = imperative
                chosen = min(pool or finite, key=_rank)
            tokens[i]["form"] = chosen
            infos[i].tags = [chosen] + [t for t in tags if t != chosen]
            previous = chosen


# --- cases ---------------------------------------------------------------------------------

def _noun_slots(lex: packs.Lexicon, info: Info, surface: str) -> frozenset[Slot]:
    """The case and number slots a noun form fits. The headword is the singular wherever the
    declension lists no singular form: every case for a feminine noun, all but the genitive otherwise."""
    slots = set()
    for tag in info.tags:
        parts = tag.split(".")
        if len(parts) >= 2 and parts[-2] in CASES:
            slots.add((parts[-2], parts[-1]))
    if info.lemma and surface == info.headword:
        row = lex.conn.execute("SELECT gender FROM lemma WHERE id = ?", (info.lemma,)).fetchone()
        for g in (row[0] if row and row[0] else ""):
            if g == "f":
                slots |= {(c, "fs") for c in CASES}
            elif g in "mn" and not any(gn == g + "s" for _, gn in slots):
                slots |= {(c, g + "s") for c in ("nom", "acc", "dat")}
    return frozenset(slots)


def _adjective_slots(info: Info, decl: str) -> frozenset[Slot]:
    by_decl: dict[str, set[Slot]] = {}
    for tag in info.tags:
        parts = tag.split(".")
        if len(parts) == 3 and parts[0] in ("str", "wk", "mix") and parts[1] in CASES:
            by_decl.setdefault(parts[0], set()).add((parts[1], parts[2]))
    return frozenset(by_decl.get(decl, set()))


@dataclass
class Phrase:
    noun: int
    det: int | None
    adjectives: list[int]
    governed: bool          # after a preposition
    options: set[Slot]


# Verbs whose second noun phrase is a nominative too (Er ist der Lehrer).
COPULAS = {"sein", "werden", "bleiben", "heißen"}


def _noun_phrases(lex: packs.Lexicon, tokens: list[dict], infos: list[Info], words: list[int],
                  clauses: list[Clause]) -> None:
    """Agree each noun with its adjectives, determiner and preposition (in dem neuen Haus: dat.ns).

    Where that leaves nominative or accusative, a phrase that opens the sentence is the subject
    unless a subject pronoun follows, and once a clause has its subject the other phrases are objects. Determiners that end up in
    no phrase stand alone (Das ist gut) and become pronouns."""
    phrases: list[Phrase] = []
    # Die Suppe esse ich: with a subject pronoun right after the verb, the opening phrase is the object.
    opening_has_subject_pronoun = False
    if clauses:
        first = clauses[0].words
        verb = next((n for n, x in enumerate(first) if is_finite(tokens[x].get("form", ""))), None)
        if verb is not None and verb + 1 < len(first):
            after = first[verb + 1]
            opening_has_subject_pronoun = infos[after].pos == "pron" and tokens[after].get("case") == "nom"
    for n, i in enumerate(words):
        info = infos[i]
        if info.pos != "n":
            continue
        options = set(_noun_slots(lex, info, tokens[i]["t"]))
        if not options:
            continue
        k = n - 1
        adjectives: list[int] = []
        while k >= 0 and (infos[words[k]].pos == "adj" or (
                infos[words[k]].pos == "adv" and adjectives and infos[words[k + 1]].pos == "adj")):
            if infos[words[k]].pos == "adj":
                adjectives.append(words[k])
            k -= 1
        det = words[k] if k >= 0 and infos[words[k]].slots is not None else None
        if det is not None:
            k -= 1
        governor = det if det is not None and infos[det].prep else (
            words[k] if k >= 0 and infos[words[k]].prep and infos[words[k]].pos == "prep" else None)
        decl = "str" if det is None else ("wk" if infos[det].det == "der" else "mix")
        if det is not None:
            options &= infos[det].slots or set()
        for a in adjectives:
            fits = _adjective_slots(infos[a], decl)
            if fits:
                options &= fits
        if governor is not None:
            options = {s for s in options if s[0] in (infos[governor].prep or set())}
        hint = next((infos[x].case_hint for x in [i, *adjectives, det] if x is not None and infos[x].case_hint), None)
        if hint:
            parts = hint.split(".")
            options = {s for s in options if s[0] == parts[0] and (len(parts) == 1 or s[1] == parts[1])}
        first = det if det is not None else (adjectives[-1] if adjectives else i)
        if not hint and governor is None and first == words[0] and any(c == "nom" for c, _ in options) \
                and not opening_has_subject_pronoun:
            options = {s for s in options if s[0] == "nom"}
        phrases.append(Phrase(i, det, adjectives, governor is not None, options))

    for clause in clauses:
        if any(infos[i].pos == "v" and infos[i].headword in COPULAS for i in clause.words):
            continue
        inside = [p for p in phrases if p.noun in clause.words and not p.governed]
        has_subject = any(tokens[i].get("case") == "nom" for i in clause.words) or any(
            {c for c, _ in p.options} == {"nom"} for p in inside)
        if not has_subject:
            continue
        for p in inside:
            cases = {c for c, _ in p.options}
            if cases == {"nom", "acc"} and not infos[p.noun].case_hint:
                p.options = {s for s in p.options if s[0] == "acc"}

    in_phrase: set[int] = set()
    for p in phrases:
        members = [x for x in [p.det, *p.adjectives, p.noun] if x is not None]
        in_phrase.update(members)
        cases = {c for c, _ in p.options}
        gns = {g for _, g in p.options}
        case = next(iter(cases)) if len(cases) == 1 else None
        gn = next(iter(gns)) if len(gns) == 1 else None
        for x in members:
            target = tokens[x]["parts"][1] if "parts" in tokens[x] else tokens[x]
            if case:
                target["case"] = case
            if gn:
                target["gn"] = gn
        if case or gn:
            decl = "str" if p.det is None else ("wk" if infos[p.det].det == "der" else "mix")
            for a in p.adjectives:
                tokens[a]["decl"] = decl
        if case in CASE_TOPIC and p.det is not None:
            grammar = tokens[p.det].setdefault("grammar", [])
            if CASE_TOPIC[case] not in grammar:
                grammar.append(CASE_TOPIC[case])
    for i in words:
        if infos[i].det and infos[i].pos in ("art", "det", "pron") and i not in in_phrase:
            tokens[i]["pos"] = "PRON"


def _single_cases(tokens: list[dict], infos: list[Info]) -> None:
    """Nouns, adjectives and pronouns outside a phrase whose form has only one case and number."""
    for tok, info in zip(tokens, infos):
        if tok.get("case") or info.pos not in ("n", "adj", "pron"):
            continue
        slots = {tuple(t.split(".")[-2:]) for t in info.tags if t.split(".")[-2:][0] in CASES}
        cases = {s[0] for s in slots}
        if len(cases) == 1:
            tok["case"] = next(iter(cases))
            gns = {s[1] for s in slots}
            if len(gns) == 1:
                tok["gn"] = next(iter(gns))


def _tag(tok: dict, topic: str) -> None:
    grammar = tok.setdefault("grammar", [])
    if topic not in grammar:
        grammar.append(topic)


def _is_comparison(tok: dict, info: Info) -> bool:
    """Whether an adjective is a comparative or superlative. kleiner is also the strong positive
    (ein kleiner Hund): with its ending resolved, only a comp. or sup. tag for that ending counts."""
    degrees = [t for t in info.tags if t.split(".")[0] in ("comp", "sup")]
    if not degrees:
        return False
    if tok.get("decl") and tok.get("case") and tok.get("gn"):
        resolved = f"{tok['decl']}.{tok['case']}.{tok['gn']}"
        return any(t in (f"comp.{resolved}", f"sup.{resolved}") for t in degrees)
    return True


def _topic_tags(tokens: list[dict], infos: list[Info], clauses: list[Clause]) -> None:
    """Grammar points a token shows by itself: nicht, comparatives, adjective endings, time
    prepositions (um acht Uhr, am Montag), and a main clause's verb second after something
    other than its subject (Morgen fahre ich)."""
    for i, (tok, info) in enumerate(zip(tokens, infos)):
        low = tok["t"].lower()
        if low == "nicht":
            _tag(tok, NEGATION_TOPIC)
        if info.pos == "adj" and _is_comparison(tok, info):
            _tag(tok, COMPARISON_TOPIC)
        if tok.get("decl"):
            _tag(tok, ADJECTIVE_TOPIC)
        if low in TIME_PREPOSITIONS and infos[i].pos in ("prep", "contr"):
            ahead = [t for t in tokens[i + 1:i + 4] if t.get("pos") != "PUNCT"]
            if any(t["t"] in TIME_WORDS or t.get("pos") == "NUM" for t in ahead[:3]):
                _tag(tok, TIME_TOPIC)
    for n, clause in enumerate(clauses):
        # A leading und or aber stands outside the clause (aber heute gehe ich). doch right before the
        # verb is an adverb in the first place (Doch kommt er nicht).
        w0, lead = clause.words[0], tokens[clause.words[0]]["t"].lower()
        adverb = lead == "doch" and len(clause.words) > 1 and is_finite(tokens[clause.words[1]].get("form", ""))
        words = clause.words[1:] if lead in CCONJ and infos[w0].pos == "conj" and not adverb else clause.words
        if clause.subordinate or len(words) < 2:
            continue
        verb = next((i for i in words if is_finite(tokens[i].get("form", ""))), None)
        if verb is None or tokens[verb]["form"].startswith("imp."):
            continue  # Dann kauf ihr Blumen: an imperative has no subject to invert
        at = words.index(verb)
        # Wenn ich Zeit habe, gehe ich: the subordinate clause takes the first place. A relative clause
        # inside the subject doesn't (Die Frau, die ich kenne, besucht sie).
        after_subordinate = at == 0 and n > 0 and all(c.subordinate for c in clauses[:n])
        if not after_subordinate and (at == 0 or len(words) < 3):
            continue
        after = words[at + 1] if at + 1 < len(words) else None
        first = tokens[words[0]]
        if words[0] != verb and (first["t"].lower() in SUBJECT_PERSONS or first.get("case") == "nom"):
            continue  # Er freut sich, Ich besuche sie: the subject comes first
        if after is not None and tokens[after]["t"] == "Sie" and tokens[verb]["form"] == "ind.pres.3p" \
                and next((t["t"] for t in reversed(tokens) if t["t"] not in CLOSING_QUOTES), "") == "!":
            continue  # Dann kaufen Sie Brot! is a Sie imperative; without the ! it reads either way
        if after is not None and infos[after].pos == "pron" and tokens[after].get("case") in (None, "nom") \
                and tokens[after]["t"].lower() in SUBJECT_PERSONS:
            _tag(tokens[verb], WORD_ORDER_TOPIC)


# --- units ---------------------------------------------------------------------------------

def _unit_surface(tokens: list[dict], idx: list[int]) -> str:
    idx = sorted(idx)
    out = tokens[idx[0]]["t"]
    for a, b in zip(idx, idx[1:]):
        out += (" " if b == a + 1 else " … ") + tokens[b]["t"]
    return out


def _separable_units(lex: packs.Lexicon, tokens: list[dict], infos: list[Info],
                     clauses: list[Clause]) -> list[dict]:
    """A main clause's finite verb and the particle at its end (rufe … an) as one unit of the joined verb."""
    units = []
    for clause in clauses:
        if clause.subordinate or len(clause.words) < 2:
            continue
        last = clause.words[-1]
        particle = tokens[last]["t"].lower()
        if particle not in PARTICLES:
            continue
        # The finite verb first; then words the dictionary only knows joined to the particle (anrufe).
        tries = [i for i in clause.words[:-1] if infos[i].pos == "v" and is_finite(tokens[i].get("form", ""))]
        tries += [i for i in clause.words[:-1] if infos[i].unresolved and i not in tries]
        verb, finite = None, []
        for i in tries:
            rows = lex.conn.execute(
                "SELECT f.lemma_id, f.tag FROM form f JOIN lemma l ON l.id = f.lemma_id "
                "WHERE f.form = ? AND l.pos = 'v' AND l.retired = 0", (particle + tokens[i]["t"].lower(),)).fetchall()
            finite = [(lid, tag) for lid, tag in rows if is_finite(tag)]
            if finite:
                verb = i
                break
        if verb is None:
            continue
        persons = _subject_persons(tokens, infos, clause, verb)
        pool = [r for r in finite if person(r[1]) in persons] if persons else finite
        if not persons and clause.words.index(verb) == 0 and any(t.startswith("imp.") for _, t in finite):
            pool = [r for r in finite if r[1].startswith("imp.")]
        own = tokens[verb].get("form")
        lemma_id, tag = min(pool or finite, key=lambda r: (r[1] != own, _rank(r[1])))
        sid = lex.first_sense(lemma_id)
        tokens[verb].update({"pos": "VERB", "lemmaID": lemma_id, "form": tag})
        tokens[verb].pop("senseID", None)
        if sid:
            tokens[verb]["senseID"] = sid
        infos[verb] = Info(pos="v", lemma=lemma_id, headword=lemma_id.split(":")[1], tags=[tag])
        tokens[last]["pos"] = "ADP"
        for key in ("lemmaID", "senseID", "grammar", "case", "gn"):
            tokens[last].pop(key, None)
        infos[last] = Info(pos="particle")
        unit = {"tokens": [verb, last], "surface": _unit_surface(tokens, [verb, last]), "lemmaID": lemma_id,
                "form": tag, "grammar": [SEPARABLE_TOPIC]}
        if sid:
            unit["senseID"] = sid
        units.append(unit)
    return units


def _participle(lex: packs.Lexicon, surface: str) -> tuple[str, str] | None:
    """(lemma, headword) of the verb whose past participle this is."""
    row = lex.conn.execute(
        "SELECT f.lemma_id, l.headword FROM form f JOIN lemma l ON l.id = f.lemma_id "
        "WHERE f.form = ? AND f.tag = 'part.pass' AND l.pos = 'v' AND l.retired = 0 ORDER BY length(f.lemma_id)",
        (surface.lower(),)).fetchone()
    return (row[0], row[1]) if row else None


def _compound_units(lex: packs.Lexicon, tokens: list[dict], infos: list[Info], clauses: list[Clause],
                    taken: set[int]) -> list[dict]:
    """haben or sein with a past participle (Perfekt, Plusquamperfekt, Konjunktiv II), werden or würde
    with an infinitive (Futur I, würde-Form). Main clauses put the participle after the auxiliary,
    subordinate clauses before it."""
    units = []
    for clause in clauses:
        used = set(taken)
        for a in clause.words:
            aux = infos[a].headword
            form = tokens[a].get("form", "")
            if infos[a].pos != "v" or aux not in AUXILIARIES or not is_finite(form) or a in used:
                continue
            key = ".".join(form.split(".")[:2])
            p = person(form)
            if p is None or (aux == "werden" and key not in FUTURE) or (aux != "werden" and (aux, key) not in COMPOUND):
                continue
            after = [i for i in clause.words if i > a and i not in used]
            before = [i for i in reversed(clause.words) if i < a and i not in used]
            partner = None
            for i in (before + after if clause.subordinate else after + before):
                if aux == "werden":
                    if tokens[i].get("form") == "inf.pres" and infos[i].pos == "v":
                        partner = (i, infos[i].lemma, f"{FUTURE[key]}.{p}")
                        break
                    continue
                found = _participle(lex, tokens[i]["t"])
                if not found:
                    continue
                lemma_id, _ = found
                verb_aux = lex.auxiliary(lemma_id)
                if (aux == "sein" and verb_aux == "haben") or (aux == "haben" and verb_aux == "sein"):
                    break  # ist geschlossen: a state, not a compound tense
                tag = f"{COMPOUND[(aux, key)]}.{p}"
                if verb_aux == "both":
                    tag += "+s" if aux == "sein" else "+h"
                partner = (i, lemma_id, tag)
                break
            if partner is None:
                continue
            i, lemma_id, tag = partner
            if aux != "werden":
                tokens[i].update({"pos": "VERB", "lemmaID": lemma_id, "form": "part.pass"})
                tokens[i].pop("senseID", None)
                for key_ in ("case", "gn", "decl"):
                    tokens[i].pop(key_, None)
                infos[i] = Info(pos="v", lemma=lemma_id, tags=["part.pass"])
            tokens[a]["pos"] = "AUX"
            unit = {"tokens": sorted([a, i]), "surface": _unit_surface(tokens, [a, i]), "form": tag}
            if lemma_id:
                unit["lemmaID"] = lemma_id
                sid = lex.first_sense(lemma_id)
                if sid:
                    unit["senseID"] = sid
                    tokens[i]["senseID"] = sid
            topic = TOPIC.get(".".join(tag.split("+")[0].split(".")[:2]))
            if topic:
                unit["grammar"] = [topic]
            used |= {a, i}
            units.append(unit)
    return units
