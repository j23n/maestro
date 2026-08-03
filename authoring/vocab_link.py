"""Link authored lesson text to the leveled vocabulary list.

Surface forms are generated *forward* from each spec lemma and matched
literally; the text is never lemmatised. The direction is the whole point.
Guessing a lemma from a surface is what filled the web app's learner
vocabularies with headwords like "capiscare" (see the note at the top of
its `vocab/discover.py`), and it eventually had to be replaced by verified
annotations. A generator can only ever emit forms for lemmas the spec
already lists, so a bad guess cannot invent a word.

Over-generating within one lemma is free: "partisco" is not Italian, so it
simply never matches. What is not free is one surface belonging to two
lemmas, so those are dropped rather than guessed at. The failure mode is a
word discovered later than it might have been, never a word discovered
wrong.
"""

from __future__ import annotations

import re
import unicodedata

# Verbs whose present indicative can't be derived from the ending. Only the
# ones the A0-A2 list actually contains — an unlisted irregular still gets
# its regular forms, which mostly miss, costing recall and nothing else.
_IRREGULAR: dict[str, tuple[str, ...]] = {
    "essere": ("sono", "sei", "è", "siamo", "siete", "stato", "stata"),
    "avere": ("ho", "hai", "ha", "abbiamo", "avete", "hanno", "avuto"),
    "andare": ("vado", "vai", "va", "andiamo", "andate", "vanno", "andato"),
    "fare": ("faccio", "fai", "fa", "facciamo", "fate", "fanno", "fatto"),
    "stare": ("sto", "stai", "sta", "stiamo", "state", "stanno", "stato"),
    "dare": ("do", "dai", "dà", "diamo", "date", "danno", "dato"),
    "dire": (
        "dico",
        "dici",
        "dice",
        "diciamo",
        "dite",
        "dicono",
        "detto",
        "dica",
        "dicevo",
        "dicevi",
        "diceva",
        "dicevano",
    ),
    "volere": ("voglio", "vuoi", "vuole", "vogliamo", "volete", "vogliono", "vorrei"),
    "potere": ("posso", "puoi", "può", "possiamo", "potete", "possono"),
    "dovere": ("devo", "devi", "deve", "dobbiamo", "dovete", "devono"),
    "sapere": ("so", "sai", "sa", "sappiamo", "sapete", "sanno", "saputo"),
    "venire": ("vengo", "vieni", "viene", "veniamo", "venite", "vengono", "venuto"),
    "uscire": ("esco", "esci", "esce", "usciamo", "uscite", "escono", "uscito"),
    "bere": ("bevo", "bevi", "beve", "beviamo", "bevete", "bevono", "bevuto"),
    "piacere": ("piaccio", "piaci", "piace", "piacciono", "piaciuto", "piaceva"),
    "prendere": (
        "prendo",
        "prendi",
        "prende",
        "prendiamo",
        "prendete",
        "prendono",
        "preso",
    ),
    "vedere": ("vedo", "vedi", "vede", "vediamo", "vedete", "vedono", "visto"),
    "chiamarsi": ("chiamo", "chiami", "chiama", "chiamiamo", "chiamate", "chiamano"),
    # Listed in full rather than left regular: the past participle is
    # "perso", which no ending-based rule reaches from "perdere".
    "perdere": (
        "perdo",
        "perdi",
        "perde",
        "perdiamo",
        "perdete",
        "perdono",
        "perso",
        "persa",
        "perduto",
        "perdendo",
    ),
}

_INVARIABLE_POS = {"art", "inter", "adv", "conj", "prep", "num", "pron", "phrase"}

# Elisions whose apostrophe fragment can't be derived by dropping a final
# vowel. Keyed by lemma, so an entry only ever fires for a word the spec
# actually lists — the map names candidates, it doesn't require them.
_ELIDED: dict[str, str] = {
    "il": "l'",
    "una": "un'",
    "di": "d'",
    "dove": "dov'",
    "ci": "c'",
    "quanto": "quant'",
    # "che cos'è?" is the whole of the `che_cose` grammar point, and it is
    # what a learner actually hears — the unelided "cosa è" is the form
    # nobody says.
    "cosa": "cos'",
    "anche": "anch'",
}

# Written variants that are the same word: "ad" and "ed" before a vowel,
# the truncations Italian makes before a masculine noun ("buon giorno",
# "bel posto"), and the demonstratives — which inflect like adjectives but
# are listed as pronouns, because pointing at a thing is grammar, not a
# word to memorise. Keyed by lemma, so they only fire for words the spec
# lists.
_VARIANTS: dict[str, tuple[str, ...]] = {
    "a": ("ad",),
    "e": ("ed",),
    "o": ("od",),
    "buono": ("buon",),
    "bello": ("bel",),
    "grande": ("gran",),
    "santo": ("san",),
    "questo": ("questa", "questi", "queste", "quest'"),
    "quello": ("quella", "quelli", "quelle", "quell'", "quel", "quei", "quegli"),
}

# Articles and preposition-article contractions in -lo/-la elide
# predictably, so "della" -> "dell'" falls out without naming every one.
_ELIDING_POS = {"art", "prep"}


def _elided_form(lemma: str, pos: str) -> str | None:
    """The apostrophe fragment `lemma` leaves when it elides, if it does."""
    if lemma in _ELIDED:
        return _ELIDED[lemma]
    if pos in _ELIDING_POS and lemma.endswith(("lo", "la")):
        return lemma[:-1] + "'"
    return None


# Preposizioni articolate: five prepositions fuse with the seven definite
# articles into a closed, fully regular grid — "a" + "il" is "al", never
# "a il". They are generated rather than listed because that is 35 written
# forms from five lemmas, and because a learner tapping "alla" wants the
# preposition's meaning ("to / at"), which is what the fusion carries.
#
# The article half is deliberately dropped: attributing "alla" to both "a"
# and "la" would make it ambiguous, and `build_index` would then discard
# it — leaving the commonest words in the language unlinkable, which is
# the bug this exists to fix.
_ARTICULATED: dict[str, str] = {
    "a": "a",
    "di": "de",
    "da": "da",
    "in": "ne",
    "su": "su",
    "con": "co",
}
_ARTICLE_TAILS = ("l", "llo", "lla", "i", "gli", "lle", "ll'")


def _articulated_forms(lemma: str, pos: str) -> set[str]:
    """The fused preposition+article forms of `lemma`, if it fuses."""
    stem = _ARTICULATED.get(lemma) if pos == "prep" else None
    if stem is None:
        return set()
    # "con" only fuses with "il" in current usage ("col"); the rest are
    # archaic and would claim surfaces nobody writes.
    tails = ("l",) if lemma == "con" else _ARTICLE_TAILS
    return {stem + tail for tail in tails}


# Numbers 21-99 are written as one word, and the rule that makes them is
# closed and fully regular: tens + unit, with the tens dropping its final
# vowel before "uno" and "otto" ("ventuno", "quarantotto") and "tre"
# taking an accent ("ventitré"). Generated for the same reason the
# articulated prepositions are — 72 written forms from eight lemmas —
# and attributed to the tens, because a learner reading "quarantacinque"
# is reading the "-anta" rule, which is exactly what num_20_100 teaches.
_TENS = (
    "venti",
    "trenta",
    "quaranta",
    "cinquanta",
    "sessanta",
    "settanta",
    "ottanta",
    "novanta",
)
_UNITS = ("uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove")


def _compound_numerals(lemma: str, pos: str) -> set[str]:
    """The 21-99 compounds `lemma` heads, if it is a tens."""
    if pos != "num" or lemma not in _TENS:
        return set()
    return {
        (lemma[:-1] if unit in ("uno", "otto") else lemma)
        + ("tré" if unit == "tre" else unit)
        for unit in _UNITS
    }


def normalize(text: str) -> str:
    """Lowercase and unify the apostrophes Italian elision uses.

    Deliberately *not* the pack's `normalize()`: that strips punctuation
    entirely, which would fuse "l'acqua" into one token and lose the word.
    """
    text = unicodedata.normalize("NFC", text)
    return text.lower().replace("’", "'").replace("ʼ", "'")


def _plural(lemma: str) -> set[str]:
    """The plural(s) of one written singular."""
    if lemma.endswith("io"):
        return {lemma[:-2] + "i"}
    if lemma.endswith("co"):
        return {lemma[:-2] + "chi", lemma[:-2] + "ci"}
    if lemma.endswith("go"):
        return {lemma[:-2] + "ghi", lemma[:-2] + "gi"}
    if lemma.endswith("ca"):
        return {lemma[:-2] + "che"}
    if lemma.endswith("ga"):
        return {lemma[:-2] + "ghe"}
    if lemma.endswith("o"):
        return {lemma[:-1] + "i"}
    if lemma.endswith("a"):
        return {lemma[:-1] + "e"}
    if lemma.endswith("e"):
        return {lemma[:-1] + "i"}
    return set()


def _noun_forms(lemma: str) -> set[str]:
    # Deliberately masculine-only. Deriving "amica" from "amico" also
    # derives "aiuta" from "aiuto" and "lavora" from "lavoro" — which are
    # the third-person forms of `aiutare` and `lavorare`, two of the
    # commonest verbs at this level. Those surfaces then belong to two
    # lemmas and get dropped, so a blanket feminine rule costs more links
    # than it wins. Animate feminines are their own dictionary entries.
    return {lemma} | _plural(lemma)


def _adjective_forms(lemma: str) -> set[str]:
    forms = _noun_forms(lemma)
    if lemma.endswith("o"):
        # Four-way agreement: bello / bella / belli / belle.
        forms |= {lemma[:-1] + "a", lemma[:-1] + "e"}
    return forms


def _verb_forms(lemma: str) -> set[str]:
    forms = {lemma}
    if lemma in _IRREGULAR:
        return forms | set(_IRREGULAR[lemma])
    if lemma.endswith("arsi") or lemma.endswith("ersi") or lemma.endswith("irsi"):
        # Reflexives conjugate on the bare stem; the clitic is a separate word.
        return forms | _verb_forms(lemma[:-2] + "e")
    stem, ending = lemma[:-3], lemma[-3:]
    # Imperfect, in all three conjugations — "capivo", "diceva". A0
    # readings narrate in it, so leaving it out orphaned real words.
    forms |= {
        stem + ("av" if ending == "are" else "ev" if ending == "ere" else "iv") + s
        for s in ("o", "i", "a", "amo", "ate", "ano")
    }
    if ending == "are":
        forms |= {
            stem + s
            for s in ("o", "i", "a", "iamo", "ate", "ano", "ato", "ata", "ando")
        }
    elif ending == "ere":
        forms |= {
            stem + s
            for s in ("o", "i", "e", "iamo", "ete", "ono", "uto", "uta", "endo")
        }
    elif ending == "ire":
        # Both conjugations; the wrong one yields a non-word that never matches.
        forms |= {
            stem + s
            for s in ("o", "i", "e", "iamo", "ite", "ono", "ito", "ita", "endo")
        }
        forms |= {stem + s for s in ("isco", "isci", "isce", "iscono")}
    return forms


def surface_forms(lemma: str, pos: str) -> set[str]:
    """Every written form of `lemma` this linker is willing to recognise."""
    lemma = normalize(lemma)
    if pos in _INVARIABLE_POS:
        forms = {lemma}
    elif pos == "verb":
        forms = _verb_forms(lemma)
    elif pos == "adj":
        forms = _adjective_forms(lemma)
    else:
        forms = _noun_forms(lemma)
    elided = _elided_form(lemma, pos)
    if elided is not None:
        forms.add(elided)
    forms |= set(_VARIANTS.get(lemma, ()))
    forms |= _articulated_forms(lemma, pos)
    forms |= _compound_numerals(lemma, pos)
    return forms


def build_index(entries) -> tuple[dict[str, str], set[str]]:
    """Map every unambiguous surface form to its lemma.

    Returns the index and the surfaces that were dropped for belonging to
    more than one lemma, so the build can report what it gave up on. A
    lemma's own citation form always wins over another lemma's generated
    form: "porta" is the noun, whatever `portare` would like.
    """
    citation = {normalize(e.id) for e in entries}
    claims: dict[str, set[str]] = {}
    for entry in entries:
        lemma = normalize(entry.id)
        for form in surface_forms(entry.id, entry.pos):
            if form in citation and form != lemma:
                continue
            claims.setdefault(form, set()).add(lemma)

    index, ambiguous = {}, set()
    for form, lemmas in claims.items():
        if len(lemmas) == 1:
            index[form] = next(iter(lemmas))
        else:
            ambiguous.add(form)
    return index, ambiguous


# A token is a run of letters, keeping an apostrophe that another letter
# follows: that is elision, and the fragment before it is a word in its
# own right ("l'acqua" -> "l'", "acqua"). An apostrophe with no letter
# after it is truncation or a quote mark, not elision, and stays out of
# the token ("un po'" -> "po").
_TOKEN_RE = re.compile(r"[a-zà-öø-ÿ]+'(?=[a-zà-öø-ÿ])|[a-zà-öø-ÿ]+", re.IGNORECASE)


_QUOTED_RE = re.compile(r"«([^»]*)»|“([^”]*)”")


def quoted_spans(text: str) -> list[str]:
    """The quoted fragments of a mixed-language string.

    Instruction prose is written in English, and a dozen spec lemmas
    ("come", "no", "male", "sale", "due") are English words too. The
    Italian in a prompt is always the part in quotes, so that is the only
    part worth scanning.
    """
    return [m.group(1) or m.group(2) or "" for m in _QUOTED_RE.finditer(text or "")]


def resolve(token: str, index: dict[str, str]) -> str | None:
    """The lemma `token` names, retrying it as an elision.

    The tokeniser only keeps an apostrophe that a letter follows, because
    that is what distinguishes elision ("l'acqua") from truncation ("un
    po'"). At a boundary the distinction disappears: an answer field
    holding just "l'" tokenises to "l". Retrying with the apostrophe
    restores it, and costs nothing when the word is genuinely truncated —
    "po'" is not a surface any lemma claims.
    """
    return index.get(token) or index.get(token + "'")


def find_lemmas(text: str, index: dict[str, str]) -> list[str]:
    """The spec lemmas appearing in `text`, in order of first appearance.

    Multi-word entries are matched before single tokens so "per favore"
    doesn't come back as two unrelated words.
    """
    if not text:
        return []
    norm = normalize(text)
    found: dict[str, None] = {}
    for form, lemma in index.items():
        if " " in form and re.search(rf"\b{re.escape(form)}\b", norm):
            found[lemma] = None
    for match in _TOKEN_RE.finditer(norm):
        lemma = resolve(match.group(), index)
        if lemma is not None:
            found[lemma] = None
    return list(found)
