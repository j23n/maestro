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
    "dire": ("dico", "dici", "dice", "diciamo", "dite", "dicono", "detto"),
    "volere": ("voglio", "vuoi", "vuole", "vogliamo", "volete", "vogliono", "vorrei"),
    "potere": ("posso", "puoi", "può", "possiamo", "potete", "possono"),
    "dovere": ("devo", "devi", "deve", "dobbiamo", "dovete", "devono"),
    "sapere": ("so", "sai", "sa", "sappiamo", "sapete", "sanno", "saputo"),
    "venire": ("vengo", "vieni", "viene", "veniamo", "venite", "vengono", "venuto"),
    "uscire": ("esco", "esci", "esce", "usciamo", "uscite", "escono", "uscito"),
    "bere": ("bevo", "bevi", "beve", "beviamo", "bevete", "bevono", "bevuto"),
    "piacere": ("piace", "piacciono", "piaciuto"),
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
}

_INVARIABLE_POS = {"inter", "adv", "conj", "prep", "num", "pron", "phrase"}


def normalize(text: str) -> str:
    """Lowercase and unify the apostrophes Italian elision uses.

    Deliberately *not* the pack's `normalize()`: that strips punctuation
    entirely, which would fuse "l'acqua" into one token and lose the word.
    """
    text = unicodedata.normalize("NFC", text)
    return text.lower().replace("’", "'").replace("ʼ", "'")


def _noun_forms(lemma: str) -> set[str]:
    forms = {lemma}
    if lemma.endswith("io"):
        forms.add(lemma[:-2] + "i")
    elif lemma.endswith("co"):
        forms |= {lemma[:-2] + "chi", lemma[:-2] + "ci"}
    elif lemma.endswith("go"):
        forms |= {lemma[:-2] + "ghi", lemma[:-2] + "gi"}
    elif lemma.endswith("ca"):
        forms.add(lemma[:-2] + "che")
    elif lemma.endswith("ga"):
        forms.add(lemma[:-2] + "ghe")
    elif lemma.endswith("o"):
        forms.add(lemma[:-1] + "i")
    elif lemma.endswith("a"):
        forms.add(lemma[:-1] + "e")
    elif lemma.endswith("e"):
        forms.add(lemma[:-1] + "i")
    return forms


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
        return {lemma}
    if pos == "verb":
        return _verb_forms(lemma)
    if pos == "adj":
        return _adjective_forms(lemma)
    return _noun_forms(lemma)


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


# A token is a run of letters, with the apostrophe of an elided article
# ending the previous one ("l'acqua" -> "l", "acqua").
_TOKEN_RE = re.compile(r"[a-zà-öø-ÿ]+", re.IGNORECASE)


_QUOTED_RE = re.compile(r"«([^»]*)»|“([^”]*)”")


def quoted_spans(text: str) -> list[str]:
    """The quoted fragments of a mixed-language string.

    Instruction prose is written in English, and a dozen spec lemmas
    ("come", "no", "male", "sale", "due") are English words too. The
    Italian in a prompt is always the part in quotes, so that is the only
    part worth scanning.
    """
    return [m.group(1) or m.group(2) or "" for m in _QUOTED_RE.finditer(text or "")]


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
        lemma = index.get(match.group())
        if lemma is not None:
            found[lemma] = None
    return list(found)
