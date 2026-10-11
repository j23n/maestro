"""`content freq <word…>` and `content suggest --unit uNN [--topic …]` (docs/04 § Commands): frequency ranks for the
item graph ("words by need, then frequency", docs/04 § How content gets made).

The frequency list is the pinned FrequencyWords `it_50k.txt` (`pipeline/data/frequency/`, `make data`; OpenSubtitles
2018, CC BY-SA 4.0, build time only: ranks are never shipped). Each line is `form count`, most frequent first; a form's
**rank** is its line number. Forms are grouped into **lemmas** through Morph-it! (`pipeline/data/morph-it/`): a lemma's
count is the sum of its forms' counts and its rank is the order of those sums, so *sono*, *è* and *sei* all count for
*essere*. A form Morph-it! doesn't know (names, English, typos) has no lemma and is never suggested.

`suggest` lists the most frequent lemmas that no item covers yet (an item covers its `it`, `plural` and `forms`, and a
lemma whose most frequent form is one of those: *latte* is `w:latte`, not *latta*), leaving out forms that are also
articles or articulated prepositions (grammar points), names, punctuation and allowlisted words. Options:
`--pos` keeps one part of speech; `--word` (repeatable) ranks only the words you list, the way "words by need, then
frequency" works within a topic (choose by need, order by frequency). The list carries no meaning, so `--topic` can't
filter candidates: it shows the items the topic already has, course-wide, to plan against. Candidates that written
drafts already use (glossed as new, `recognise`, or in accepted alternatives without an item) are marked.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itcontent import paths
from itcontent.course import Course, load_course
from itcontent.morphit import MorphIt, any_pos
from itcontent.morphit import load as load_morphit
from itcontent.tokenize import fold

FREQ_FILE = Path("pipeline/data/frequency/it_50k.txt")
MORPH_FILE = Path("pipeline/data/morph-it/morph-it.txt")

#: Morph-it! category prefixes → item POS (docs/03 § Items), checked in order; None: never an item of its own.
CATEGORY_POS: tuple[tuple[str, str | None], ...] = (
    ("ARTPRE", None),
    ("ART", None),
    ("NPR", None),
    ("PON", None),
    ("SYM", None),
    ("SENT", None),
    ("SMI", None),
    ("ABL", None),
    ("NOUN", "noun"),
    ("ADJ", "adj"),
    ("ADV", "adv"),
    ("PRE", "prep"),
    ("CON", "conj"),
    ("DET-NUM-CARD", "num"),
    ("PRO-NUM", "num"),
    ("DET", "det"),
    ("TALE", "det"),
    ("PRO", "pron"),
    ("SI", "pron"),
    ("CI", "pron"),
    ("NE", "pron"),
    ("CE", "pron"),
    ("WH-CHE", "conj"),
    ("WH", "adv"),
    ("INT", "interj"),
    ("VER", "verb"),
    ("AUX", "verb"),
    ("MOD", "verb"),
    ("CAU", "verb"),
    ("ASP", "verb"),
)
POS_NAMES = frozenset(p for _, p in CATEGORY_POS if p)


def category_pos(category: str) -> str | None:
    for prefix, pos in CATEGORY_POS:
        if any_pos(category, (prefix,)):
            return pos
    return None


@dataclass(frozen=True)
class Form:
    form: str
    rank: int
    count: int


@dataclass
class Lemma:
    lemma: str
    count: int = 0
    best: int = 0  # best (lowest) rank among its forms
    pos: set[str] = field(default_factory=set)
    forms: list[Form] = field(default_factory=list)
    rank: int = 0  # rank of `count` among all lemmas


class Frequency:
    def __init__(self, forms: Iterable[Form]) -> None:
        self.forms: list[Form] = []
        self.by_form: dict[str, Form] = {}
        for f in forms:
            if f.form not in self.by_form:
                self.by_form[f.form] = f
                self.forms.append(f)

    @classmethod
    def load(cls, path: Path) -> Frequency:
        forms = []
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            parts = raw.split()
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            forms.append(Form(fold(unicodedata.normalize("NFC", parts[0])), n, int(parts[1])))
        return cls(forms)

    def lemmas(self, morph: MorphIt) -> dict[str, Lemma]:
        """Every lemma Morph-it! gives the listed forms, with summed counts, ranked by those sums."""
        out: dict[str, Lemma] = {}
        for f in self.forms:
            seen: set[str] = set()
            analyses = morph.get(f.form)
            if any(any_pos(a.category, ("ART", "ARTPRE")) for a in analyses):
                continue  # mostly an article (la, una, l'): a grammar point, never an item
            for a in analyses:
                pos = category_pos(a.category)
                if pos is None:
                    continue
                lem = out.setdefault(fold(a.lemma), Lemma(fold(a.lemma), best=f.rank))
                lem.pos.add(pos)
                if lem.lemma not in seen:
                    seen.add(lem.lemma)
                    lem.count += f.count
                    lem.best = min(lem.best, f.rank)
                    lem.forms.append(f)
        for i, lem in enumerate(sorted(out.values(), key=lambda x: (-x.count, x.best, x.lemma)), start=1):
            lem.rank = i
        return out


# ---------------------------------------------------------------- what the course already has


@dataclass
class Covered:
    by_word: dict[str, str]  # folded it / plural / form → item id
    item_unit: dict[str, str]
    allowlisted: frozenset[str]
    drafts: set[str]  # lemmas and forms written content uses without an item

    def item_for(self, lemma: Lemma) -> str | None:
        """The item that covers a lemma: its own word, or its most frequent form (latte → w:latte, not latta)."""
        if lemma.lemma in self.by_word:
            return self.by_word[lemma.lemma]
        top = min(lemma.forms, key=lambda f: f.rank) if lemma.forms else None
        return self.by_word.get(top.form) if top else None


def covered(course: Course, root: Path) -> Covered:
    by_word: dict[str, str] = {}
    item_unit: dict[str, str] = {}
    for u, _, it in course.items():
        iid = it.get("id")
        if not isinstance(iid, str) or not iid.startswith("w:"):
            continue
        item_unit[iid] = u.id
        plural = it.get("plural") if it.get("plural") != "invariable" else None
        for w in [it.get("it"), plural, *(it.get("forms") or [])]:
            if isinstance(w, str):
                by_word.setdefault(fold(w), iid)
    allow = course.singles.get("allowlist")
    data = (allow.data if allow else None) or {}
    words = [*(data.get("names") or []), *(data.get("interjections") or [])]
    words += [t.get("form") for t in data.get("transparent") or [] if isinstance(t, dict)]
    return Covered(by_word, item_unit, frozenset(fold(str(w)) for w in words if w), draft_words(root))


def draft_words(root: Path) -> set[str]:
    """Lemmas (and surfaces) of tokens written content uses without an item: glossed as new, `recognise`, or in
    accepted alternatives (from the annotation lock files)."""
    out: set[str] = set()
    base = root / "content" / ".annotations"
    for p in sorted(base.rglob("*.json")) if base.is_dir() else []:
        try:
            lock = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for s in lock.get("strings") or []:
            for t in s.get("tokens") or []:
                if t.get("kind") != "word" or t.get("item") or t.get("chunk"):
                    continue
                if {"new", "recognise", "unresolved"} & set(t.get("flags") or ()):
                    out.add(fold(str(t.get("surface", ""))))
                    out.update(fold(str(a).rpartition(" ")[0]) for a in t.get("analyses") or ())
    return out


# ---------------------------------------------------------------- commands


def _paths(root: Path, freq_file: Path | None) -> tuple[Path, Path]:
    return (freq_file or root / FREQ_FILE), root / MORPH_FILE


def _missing(path: Path, root: Path, echo: Callable[[str], Any]) -> bool:
    if path.is_file():
        return False
    try:
        shown = path.relative_to(root)
    except ValueError:
        shown = path
    echo(f"error: {shown} is missing: run `make data`")
    return True


def run_freq(
    words: list[str],
    *,
    root: Path | None = None,
    freq_file: Path | None = None,
    morph: MorphIt | None = None,
    echo: Callable[[str], Any] = print,
) -> int:
    root = (root or paths.ROOT).resolve()
    fpath, mpath = _paths(root, freq_file)
    if _missing(fpath, root, echo) or (morph is None and _missing(mpath, root, echo)):
        return 2
    freq = Frequency.load(fpath)
    morph = morph or load_morphit(mpath.resolve())
    lemmas = freq.lemmas(morph)
    cov = covered(load_course(root), root)
    for raw in words:
        w = fold(unicodedata.normalize("NFC", raw))
        f = freq.by_form.get(w)
        parts = [f"form rank {f.rank} ({f.count:,})" if f else "form not in the list"]
        names = sorted(
            {fold(a.lemma) for a in morph.get(w) if category_pos(a.category)} | ({w} if w in lemmas else set())
        )
        if not names:
            parts.append("no Morph-it! lemma (a name, a foreign word or a typo?)")
        for name in names:
            lem = lemmas.get(name)
            if lem is None:
                parts.append(f"lemma {name}: not in the list")
                continue
            item = cov.item_for(lem)
            where = f", item {item} ({cov.item_unit.get(item, '?')})" if item else ""
            parts.append(f"lemma {name} ({'/'.join(sorted(lem.pos))}): rank {lem.rank} ({lem.count:,}){where}")
        echo(f"{raw}: " + "; ".join(parts))
    return 0


def suggest(
    lemmas: dict[str, Lemma],
    cov: Covered,
    *,
    pos: str | None = None,
    words: list[str] | None = None,
    limit: int = 40,
) -> list[Lemma]:
    """The most frequent lemmas no item covers (only `words`, if given), optionally of one POS."""
    wanted = {fold(w) for w in words} if words else None
    out = []
    for lem in sorted(lemmas.values(), key=lambda x: x.rank):
        if wanted is not None and lem.lemma not in wanted and not ({f.form for f in lem.forms} & wanted):
            continue
        top = min(lem.forms, key=lambda f: f.rank).form if lem.forms else lem.lemma
        if cov.item_for(lem) or {lem.lemma, top} & cov.allowlisted or (len(lem.lemma) < 2 and wanted is None):
            continue
        if pos and pos not in lem.pos:
            continue
        out.append(lem)
        if len(out) >= limit:
            break
    return out


def run_suggest(
    *,
    unit: str,
    topic: str | None = None,
    pos: str | None = None,
    words: list[str] | None = None,
    limit: int = 40,
    root: Path | None = None,
    freq_file: Path | None = None,
    morph: MorphIt | None = None,
    echo: Callable[[str], Any] = print,
) -> int:
    root = (root or paths.ROOT).resolve()
    course = load_course(root)
    u = course.unit(unit)
    if u is None:
        echo(f"error: unknown unit {unit}")
        return 2
    if pos and pos not in POS_NAMES:
        echo(f"error: unknown part of speech {pos} (one of {', '.join(sorted(POS_NAMES))})")
        return 2
    fpath, mpath = _paths(root, freq_file)
    if _missing(fpath, root, echo) or (morph is None and _missing(mpath, root, echo)):
        return 2
    morph = morph or load_morphit(mpath.resolve())
    lemmas = Frequency.load(fpath).lemmas(morph)
    cov = covered(course, root)
    spec_items = (u.spec.data.get("items") if u.spec and isinstance(u.spec.data, dict) else None) or {}
    have = sum(1 for _, _, it in course.items() if cov.item_unit.get(str(it.get("id"))) == unit)
    echo(f"# Item candidates for {unit}" + (f" · {topic}" if topic else ""))
    echo("")
    echo(f"{unit} has {have} word item(s); its spec asks for {spec_items.get('new_words', '?')} new words.")
    if topic:
        topical = sorted(
            (cov.item_unit.get(str(it["id"]), "?"), str(it["id"]))
            for _, _, it in course.items()
            if topic in (it.get("topics") or []) and isinstance(it.get("id"), str)
        )
        listed = ", ".join(f"{iid} ({uid})" for uid, iid in topical) or "none yet"
        echo(f"Items with {topic} so far: {listed}.")
        echo("The frequency list has no topics: choose the topic's words by need, then pass them with --word to rank")
        echo("them; without --word these are the most frequent lemmas no item covers yet.")
    echo("")
    rows = suggest(lemmas, cov, pos=pos, words=words, limit=limit)
    if not rows:
        echo("No candidates.")
        return 0
    echo("| Rank | Lemma | POS | Count | Top forms | In drafts |")
    echo("|---|---|---|---|---|---|")
    for lem in rows:
        top = ", ".join(f.form for f in sorted(lem.forms, key=lambda f: f.rank)[:4])
        drafts = "yes" if lem.lemma in cov.drafts or {f.form for f in lem.forms} & cov.drafts else ""
        echo(f"| {lem.rank} | {lem.lemma} | {'/'.join(sorted(lem.pos))} | {lem.count:,} | {top} | {drafts} |")
    if words:
        known = sorted({fold(w) for w in words} - {r.lemma for r in rows} - {f.form for r in rows for f in r.forms})
        if known:
            echo("")
            echo("Already items, allowlisted or not in the list: " + ", ".join(known))
    return 0
