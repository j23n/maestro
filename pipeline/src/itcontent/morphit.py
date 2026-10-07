"""Morph-it! lookup (docs/04 § Reference data, § Annotation step 3; facts in pipeline/data/SOURCES.md).

Lines are `form<TAB>lemma<TAB>CATEGORY[:features]`. The file is Latin-1; it is decoded and normalised to UTF-8 NFC,
and the two malformed lines that use spaces instead of tabs are split on whitespace. The index (surface form →
analyses) is built once per process.

Categories carry gender, person and number with `-` (`NOUN-M`, `ART-F`, `PRO-PERS-CLI-3-F-S`), so a `pos` matcher is a
**prefix on `-` boundaries**: `ART` matches `ART-M` but not `ARTPRE-M`. A `morph` regex matches the features after the
colon (`ind+pres+3+s`), or the empty string when there are none.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from itcontent import paths

DEFAULT_PATH = paths.DATA / "morph-it" / "morph-it.txt"

#: Categories of verbs (lexical, auxiliary, modal, causative, aspectual).
VERB_CATEGORIES = ("VER", "AUX", "MOD", "CAU", "ASP")

#: Elided forms and the full forms whose analyses they take (docs/04 § Annotation step 3). The table wins over
#: Morph-it!'s own entry for these forms: Morph-it! lists `c'` as ADV with lemma `c'` (we want *ci*), `anch'` with lemma
#: `anch'` (we want *anche*) and lacks `quant'`. An optional category filter keeps only matching analyses
#: (`un'` is never the pronoun *una*).
ELISIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "l'": (("lo", "la"), ()),
    "un'": (("una",), ("ART",)),
    "dell'": (("dello", "della"), ()),
    "c'": (("ci",), ()),
    "dov'": (("dove",), ()),
    "com'": (("come",), ()),
    "cos'": (("cosa",), ()),
    "quant'": (("quanto",), ()),
    "anch'": (("anche",), ()),
    "d'": (("di",), ()),
    "m'": (("mi",), ()),
    "t'": (("ti",), ()),
    "s'": (("si",), ()),
    "v'": (("vi",), ()),
}

APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'"})


def pos_matches(category: str, prefix: str) -> bool:
    """`ART` matches `ART-M` and `ART`, not `ARTPRE-M`; `PRO-PERS` matches `PRO-PERS-CLI-3-F-S`."""
    return category == prefix or category.startswith(prefix + "-")


def any_pos(category: str, prefixes: Iterable[str]) -> bool:
    return any(pos_matches(category, p) for p in prefixes)


@dataclass(frozen=True, order=True)
class Analysis:
    """One Morph-it! reading of a form: lemma, category (`NOUN-M`) and features (`s`; empty when none)."""

    lemma: str
    category: str
    features: str = ""
    synthetic: bool = False  # made from an item when Morph-it! has no compatible reading (docs/04 step 4)

    @property
    def tag(self) -> str:
        return f"{self.category}:{self.features}" if self.features else self.category

    def __str__(self) -> str:
        return f"{self.lemma} {self.tag}"

    def is_verb(self) -> bool:
        return any_pos(self.category, VERB_CATEGORIES)

    def matches(
        self, *, lemma: Iterable[str] | None = None, pos: Iterable[str] | None = None, morph: str | None = None
    ) -> bool:
        if lemma is not None and self.lemma not in set(lemma):
            return False
        if pos is not None and not any_pos(self.category, pos):
            return False
        return not (morph is not None and not re.search(morph, self.features))


def parse_tag(tag: str) -> tuple[str, str]:
    cat, _, feats = tag.partition(":")
    return cat, feats


class MorphIt:
    """The surface-form index."""

    def __init__(self, entries: dict[str, tuple[Analysis, ...]], malformed: int = 0) -> None:
        self._index = entries
        self.malformed = malformed

    def __len__(self) -> int:
        return len(self._index)

    def __contains__(self, form: str) -> bool:
        return form in self._index

    def get(self, form: str) -> tuple[Analysis, ...]:
        """Analyses of exactly this surface form (NFC), or ()."""
        return self._index.get(form, ())

    def lookup(self, surface: str) -> tuple[Analysis, ...]:
        """docs/04 § Annotation step 3: elision table, then the surface form, then the lowercased form."""
        form = unicodedata.normalize("NFC", surface).translate(APOSTROPHES)
        low = form.lower()
        if low in ELISIONS:
            fulls, cats = ELISIONS[low]
            found = [a for full in fulls for a in self.get(full) if not cats or any_pos(a.category, cats)]
            return tuple(sorted(set(found)))
        hit = self.get(form)
        if not hit and low != form:
            hit = self.get(low)
        return hit


def parse_lines(lines: Iterable[str]) -> MorphIt:
    index: dict[str, list[Analysis]] = {}
    malformed = 0
    for raw in lines:
        line = unicodedata.normalize("NFC", raw.rstrip("\r\n"))
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            parts = line.split()
            malformed += 1
            if len(parts) != 3:
                continue
        form, lemma, tag = parts
        cat, feats = parse_tag(tag)
        index.setdefault(form, []).append(Analysis(lemma, cat, feats))
    return MorphIt({f: tuple(sorted(set(a))) for f, a in index.items()}, malformed)


@cache
def load(path: Path = DEFAULT_PATH) -> MorphIt:
    """Load and index Morph-it! once per process. Latin-1 is the file's encoding (SOURCES.md); UTF-8 is accepted."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_lines(text.splitlines())
