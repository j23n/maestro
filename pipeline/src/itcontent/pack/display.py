"""Display forms of items and the generated recall answers (docs/03 § Display forms, docs/05 § Review session builder,
docs/06 § 1).

- Nouns show with the **definite article** (`il cornetto`, `la spremuta`, `lo zaino`); where the article hides the
  gender, the display adds it (`l'acqua (f)`); nouns for people show both genders (`l'amico / l'amica`). The indefinite
  form (`un cornetto`, `un'amica`) is stored too. `articles: {indef, def}` overrides the computed articles.
- The generated recall answer mirrors LearningCore's `GeneratedCards.recall` (preview retrievals use it): an item's
  `recall_answer` if set; nouns accept the definite or indefinite article with the noun as focus (`{il|un} [cornetto]`),
  a bare noun is `correctWithNote` and a singular article of the other gender `almost`; chunks are their text without
  trailing `… ? !`; other words are the lemma as focus.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

VOWELS = frozenset("aeiouàèéìíòóùú")
CONSONANTS = frozenset("bcdfghjklmnpqrstvwxyz")
PATTERN_SPECIAL = frozenset("\\{}[]()|")
GENDER_MARKS = (" (m)", " (f)", " (mf)", " (m/f)")


def escape(text: str) -> str:
    """Escape the answer-pattern language's special characters in literal text (docs/03)."""
    return "".join("\\" + ch if ch in PATTERN_SPECIAL else ch for ch in text)


def starts_with_vowel(word: str) -> bool:
    w = word.lower()
    if not w:
        return False
    if w[0] == "h" and len(w) > 1 and w[1] in VOWELS:
        return True  # l'hotel, un hotel: a silent h
    return w[0] in VOWELS


def takes_lo(word: str) -> bool:
    """Masculine nouns that take lo/uno: s + consonant, z, gn, ps, pn, x, y, and i + vowel (lo iogurt)."""
    w = word.lower()
    if not w:
        return False
    if w[0] == "s" and len(w) > 1 and w[1] in CONSONANTS:
        return True
    if w[0] in "zxy":
        return True
    if w[:2] in ("gn", "ps", "pn"):
        return True
    return w[0] == "i" and len(w) > 1 and w[1] in VOWELS


def definite(noun: str, gender: str) -> str:
    if starts_with_vowel(noun):
        return "l'"
    if gender == "f":
        return "la"
    return "lo" if takes_lo(noun) else "il"


def indefinite(noun: str, gender: str) -> str:
    if gender == "f":
        return "un'" if starts_with_vowel(noun) else "una"
    return "uno" if takes_lo(noun) else "un"


def join(article: str, noun: str) -> str:
    return article + noun if article.endswith("'") else f"{article} {noun}"


def feminine_form(item: Mapping[str, Any]) -> str | None:
    """The feminine singular of a noun for people (`amica` for `amico`), taken from the item's `forms`."""
    it = str(item.get("it", ""))
    forms = [str(f) for f in item.get("forms") or ()]
    candidates = []
    if it.endswith("tore"):
        candidates.append(it[:-4] + "trice")
    if it.endswith("o"):
        candidates.append(it[:-1] + "a")
    if it.endswith("e"):
        candidates += [it[:-1] + "a", it[:-1] + "essa"]
    return next((c for c in candidates if c in forms), None)


def display_forms(item: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(display_def, display_indef) of a noun item; (None, None) for anything else."""
    if str(item.get("pos")) != "noun":
        return None, None
    noun = str(item.get("it", ""))
    gender = str(item.get("gender") or "m")
    over = item.get("articles") if isinstance(item.get("articles"), dict) else {}
    if gender == "mf":
        fem = feminine_form(item)
        m_def = str(over.get("def") or definite(noun, "m"))
        m_indef = str(over.get("indef") or indefinite(noun, "m"))
        if fem is not None:
            return (
                f"{join(m_def, noun)} / {join(definite(fem, 'f'), fem)}",
                f"{join(m_indef, noun)} / {join(indefinite(fem, 'f'), fem)}",
            )
        f_def = definite(noun, "f")
        if m_def == f_def:  # l'artista: the article shows neither gender
            return f"{join(m_def, noun)} (m/f)", f"{join(m_indef, noun)} / {join(indefinite(noun, 'f'), noun)}"
        return (
            f"{join(m_def, noun)} / {join(f_def, noun)}",
            f"{join(m_indef, noun)} / {join(indefinite(noun, 'f'), noun)}",
        )
    art = str(over.get("def") or definite(noun, gender))
    disp = join(art, noun)
    if art.endswith("'"):
        disp += f" ({gender})"
    return disp, join(str(over.get("indef") or indefinite(noun, gender)), noun)


# ---------------------------------------------------------------- generated recall answers


@dataclass(frozen=True)
class NounForm:
    article: str
    noun: str
    elided: bool

    @property
    def text(self) -> str:
        return self.article + self.noun if self.elided else f"{self.article} {self.noun}"

    @property
    def pattern(self) -> str:
        if self.elided:
            return f"[{escape(self.article + self.noun)}]"
        return f"{escape(self.article)} [{escape(self.noun)}]"


@dataclass(frozen=True)
class NearAnswer:
    answer: str  # a pattern
    outcome: str  # wrong | almost | correctWithNote
    hint: str


DEFINITE_ARTICLES = frozenset({"il", "lo", "la", "i", "gli", "le"})
INDEFINITE_ARTICLES = frozenset({"un", "uno", "una"})


def strip_gender_mark(text: str) -> str:
    t = text.strip()
    for mark in GENDER_MARKS:
        if t.endswith(mark):
            return t[: -len(mark)].strip()
    return t


def parse_noun_form(raw: str) -> NounForm | None:
    text = raw.replace("’", "'").strip()
    lower = text.lower()
    for elided in ("un'", "l'"):
        if lower.startswith(elided) and len(text) > len(elided):
            return NounForm(elided, text[len(elided) :].strip(), True)
    if " " not in text:
        return None
    article, noun = text.split(" ", 1)
    if article.lower() not in DEFINITE_ARTICLES | INDEFINITE_ARTICLES or not noun.strip():
        return None
    return NounForm(article.lower(), noun.strip(), False)


def noun_forms(display: str | None) -> list[NounForm]:
    if not display:
        return []
    return [f for part in strip_gender_mark(display).split("/") if (f := parse_noun_form(part)) is not None]


def chunk_answer(it: str) -> str | None:
    """A chunk's text without trailing `… ? !` and spaces; None when it contains `/` (recall_answer is required)."""
    text = it.strip()
    while text and (text[-1] in "…?!" or text[-1] == " "):
        text = text[:-1]
    if not text or "/" in text:
        return None
    return text


def noun_recall(gender: str | None, display_def: str | None, display_indef: str | None):
    forms: list[NounForm] = []
    for f in noun_forms(display_def) + noun_forms(display_indef):
        if f not in forms:
            forms.append(f)
    if not forms:
        return None
    model = forms[0]
    nouns: list[str] = []
    for f in forms:
        if f.noun not in nouns:
            nouns.append(f.noun)
    if len(nouns) == 1 and not any(f.elided for f in forms):
        articles = [escape(f.article) for f in forms]
        answer = model.pattern if len(articles) == 1 else "{" + "|".join(articles) + "} [" + escape(model.noun) + "]"
    else:
        answer = model.pattern if len(forms) == 1 else "{" + "|".join(f.pattern for f in forms) + "}"
    bare = escape(nouns[0]) if len(nouns) == 1 else "{" + "|".join(escape(n) for n in nouns) + "}"
    near = [NearAnswer(bare, "correctWithNote", f"Say it with its article: {model.text}")]
    if len(nouns) == 1 and gender in ("m", "f"):
        noun = nouns[0]
        if gender == "m":
            wrong_articles = [("la", False), ("una", False)] + ([("un'", True)] if starts_with_vowel(noun) else [])
        else:
            wrong_articles = [("il", False), ("lo", False), ("un", False), ("uno", False)]
        correct = {f.text for f in forms}
        wrong = [NounForm(a, noun, e).text for a, e in wrong_articles]
        wrong = [w for w in wrong if w not in correct]
        if wrong:
            pattern = escape(wrong[0]) if len(wrong) == 1 else "{" + "|".join(escape(w) for w in wrong) + "}"
            gendered = "masculine" if gender == "m" else "feminine"
            near.append(NearAnswer(pattern, "almost", f"{noun} is {gendered}: {model.text}"))
    return answer, near


def recall_answer(item: Mapping[str, Any], kind: str) -> tuple[str, list[NearAnswer]] | None:
    """The generated recall answer pattern and near-misses of a word or chunk item; None for grammar and sounds,
    and for a chunk whose text contains `/` without a `recall_answer` (lint requires one)."""
    if kind not in ("word", "chunk"):
        return None
    if isinstance(item.get("recall_answer"), str) and item["recall_answer"]:
        return str(item["recall_answer"]), []
    it = str(item.get("it", ""))
    if kind == "chunk":
        text = chunk_answer(it)
        return (escape(text), []) if text is not None else None
    if str(item.get("pos")) == "noun":
        d, i = display_forms(item)
        found = noun_recall(str(item.get("gender") or "m"), d, i)
        if found is not None:
            return found
    return f"[{escape(it)}]", []


def primary_gloss(gloss: str) -> str:
    """The gloss up to the first `;` (prompts of recall, options of choice, match right sides)."""
    return gloss.split(";", 1)[0].strip()
