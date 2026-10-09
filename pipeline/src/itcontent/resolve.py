"""Item resolution for one Italian string (docs/04 § Annotation steps 2–5).

`Lexicon.from_course` gathers what resolution needs (items, chunks, the allowlist, `disambiguation.yaml`, grammar
point units, Morph-it!, detection rules); `Lexicon.annotate` turns one string plus its line fields into annotated
tokens and issues. The order for each word token outside a chunk:

1. **Candidates.** Items whose `it`, `plural` or `forms` equal the surface (case-insensitive) come first and skip
   the lemma lookup; each keeps only the Morph-it! analyses compatible with its POS, or one analysis synthesised
   from the item when none is (`spremuta` is only a participle in Morph-it!). Otherwise each analysis' lemma maps to
   word items whose `it` equals it with a compatible POS. Articles (ART) map to `g:indefinite-article` /
   `g:definite-article` and articulated prepositions (ARTPRE) to `g:articulated-prepositions` / `-lo-gli`, never
   to word items.
2. **Choice.** The `lemmas:` override (of the line, or of the exercise or layout the string belongs to), then the
   `disambiguation.yaml` context rule for the form (applied whenever the form has one, since a rule may also rule out
   an article reading, as for clitic *la*), then its default: an item ID (among several candidates), or `{pos: […]}`,
   which, like a rule's choice, keeps only those Morph-it! readings even with one candidate (*ci* is the clitic,
   not the letter `w:ci~letter`); one candidate left is taken, several are an error naming the line and the
   candidates. A rule's conditions look at the neighbours' *context*: the readings of the items each neighbour can
   still resolve to after `lemmas:` and its default (all its candidates' when it has a rule of its own; its Morph-it!
   readings when it has no candidate or is in a chunk), so a letter noun *o* never makes *uno* an article. An
   allowlisted name is always a proper noun (`NPR`, synthesised when Morph-it! lacks it), so *la Federica* is the
   article.
3. **The lexical-article rule** (ADR-20): an article directly before a noun item (or an allowlisted noun such as
   *bar*), or before an adjective and a noun item, is part of that noun until the article's own unit
   (`points.yaml`): it takes the noun's item, the `lexical_article` flag and no detection.
4. **No candidate:** allowlisted words pass; glossed and `recognise` tokens pass (new in this step); in an accepted
   pattern's other expansions the token keeps its Morph-it! lemma with no item (a warning if it has no analysis
   either); anything else is an error ("untaught lemma").
5. **Detection** (`itcontent.detection`) over the chosen analyses.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from itcontent.chunks import ChunkMatcher, find_sequences
from itcontent.course import Course
from itcontent.detection import Detection, Detector
from itcontent.morphit import VERB_CATEGORIES, Analysis, MorphIt, any_pos
from itcontent.tokenize import FOREIGN, NAME, PUNCT, WORD, Token, fold, tokenize

#: Morph-it! categories compatible with each item POS (docs/03 § Items).
POS_CATEGORIES: dict[str, tuple[str, ...]] = {
    "noun": ("NOUN",),
    "verb": VERB_CATEGORIES,
    "adj": ("ADJ",),
    "adv": ("ADV", "WH"),
    "prep": ("PRE",),
    "conj": ("CON", "WH", "WH-CHE"),
    "pron": ("PRO", "SI", "CI", "NE", "CE", "WH", "WH-CHE"),
    "det": ("DET",),
    "num": ("DET-NUM-CARD", "PRO-NUM"),
    "interj": ("INT",),
}
SYNTH_CATEGORY = {
    "verb": "VER",
    "adj": "ADJ",
    "adv": "ADV",
    "prep": "PRE",
    "conj": "CON",
    "pron": "PRO",
    "det": "DET",
    "num": "DET-NUM-CARD",
    "interj": "INT",
}

INDEFINITE = "g:indefinite-article"
DEFINITE = "g:definite-article"
ARTPRE = "g:articulated-prepositions"
ARTPRE_LO_GLI = "g:articulated-prepositions-lo-gli"
INDEFINITE_FORMS = frozenset({"un", "uno", "una", "un'"})
ARTPRE_LO_GLI_FORMS = frozenset(
    {"allo", "agli", "nello", "negli", "dallo", "dagli", "dello", "degli", "sullo", "sugli"}
)
LEXICAL_POINTS = (INDEFINITE, DEFINITE)

#: Flags written to the lock files (docs/03 § Annotation lock files). `foreign`, `name` and `number` are token kinds.
NEW = "new"  # glossed in this line and not introduced before this step
RECOGNISE = "recognise"  # listed in the line's `recognise` (flag 2)
LEXICAL_ARTICLE = "lexical_article"
ALLOWLISTED = "allowlisted"
SYNTHETIC = "synthetic"  # the analysis was made from the item; Morph-it! has no compatible one
SOUND = "sound"  # a sound-pair word: listening material with its own glosses
UNRESOLVED = "unresolved"  # no item: allowed only in non-model expansions, sound words and pending titles
PENDING = "pending"  # a unit-title token whose unit has no items file yet

Position = tuple[int, int, int]  # (unit index, lesson K or a container rank, step index)


@dataclass
class TokAnn:
    tok: Token
    raw: tuple[Analysis, ...] = ()  # every Morph-it! analysis of the surface
    context: tuple[Analysis, ...] = ()  # the readings neighbours' context rules see (`Lexicon.context_readings`)
    analyses: tuple[Analysis, ...] = ()  # left after disambiguation
    item: str | None = None
    chunk: str | None = None
    flags: set[str] = field(default_factory=set)
    gloss: str | None = None
    head: int | None = None  # lexical article: index of its noun
    detections: list[str] = field(default_factory=list)
    candidates: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return self.tok.kind

    @property
    def surface(self) -> str:
        return self.tok.surface

    @property
    def norm(self) -> str:
        return self.tok.norm

    @property
    def detectable(self) -> bool:
        return self.tok.kind == WORD and self.chunk is None and LEXICAL_ARTICLE not in self.flags

    @property
    def lemma(self) -> str | None:
        lemmas = sorted({a.lemma for a in self.analyses})
        return lemmas[0] if len(lemmas) == 1 else None


@dataclass(frozen=True)
class Issue:
    level: str  # error | warning | pending
    token: int | None
    message: str


@dataclass
class Annotated:
    text: str
    lead: str
    tokens: list[TokAnn]
    detections: list[Detection]
    issues: list[Issue]
    used_lemmas: frozenset[str] = frozenset()  # the (folded) `lemmas` keys this string contains


@dataclass
class Ctx:
    """Everything about one string that changes how it is annotated."""

    unit: int  # course order of the string's unit
    pos: Position = (0, 0, 0)
    foreign: Sequence[str] = ()
    gloss: Mapping[str, str] = field(default_factory=dict)
    lemmas: Mapping[str, Any] = field(default_factory=dict)
    # True when `lemmas` is an exercise's or a layout's: it covers several strings, so a key this string doesn't
    # contain is fine here (the annotator reports a key none of them contains)
    shared_lemmas: bool = False
    recognise: Sequence[str] = ()
    strict: bool = True  # False for an accepted pattern's other expansions
    pending: bool = False  # unit spec title of a unit without an items file
    sound: bool = False  # a sound-pair word
    sound_glosses: Mapping[str, str] = field(default_factory=dict)
    markup: str = ""
    protected: Sequence[tuple[int, int, str]] = ()


def _neighbour(anns: Sequence[TokAnn], k: int, step: int) -> TokAnn | None:
    j = k + step
    while 0 <= j < len(anns):
        if anns[j].kind != PUNCT:
            return anns[j]
        j += step
    return None


def _any_match(tok: TokAnn | None, spec: Mapping[str, Any]) -> bool:
    """disambiguation.yaml: a neighbour matches if ANY of its analyses matches (form on the lowercase surface)."""
    if tok is None:
        return False
    if "form" in spec and not re.search(str(spec["form"]), tok.norm):
        return False
    keys = {k: spec[k] for k in ("lemma", "pos", "morph") if k in spec}
    if not keys:
        return True
    lemma = [str(x) for x in spec["lemma"]] if "lemma" in spec else None
    pos = [str(x) for x in spec["pos"]] if "pos" in spec else None
    morph = str(spec["morph"]) if "morph" in spec else None
    return any(a.matches(lemma=lemma, pos=pos, morph=morph) for a in tok.context)


class Lexicon:
    def __init__(
        self,
        *,
        items: Mapping[str, Mapping[str, Any]],
        item_unit: Mapping[str, str],
        unit_index: Mapping[str, int],
        point_unit: Mapping[str, str],
        allowlist: Mapping[str, Any],
        disambiguation: Mapping[str, Any],
        morph: MorphIt,
        detector: Detector,
        intro: Mapping[str, Position] | None = None,
        slot_heads: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self.items = dict(items)
        self.item_unit = dict(item_unit)
        self.unit_index = dict(unit_index)
        self.point_unit = dict(point_unit)
        self.morph = morph
        self.detector = detector
        self.intro = dict(intro or {})
        self.slot_heads = dict(slot_heads or {})
        self.by_form: dict[str, list[str]] = {}
        self.by_lemma: dict[str, list[str]] = {}
        for iid, it in sorted(self.items.items()):
            if not iid.startswith("w:"):
                continue
            base = fold(str(it.get("it", "")))
            self.by_lemma.setdefault(base, []).append(iid)
            plural = str(it.get("plural") or "")
            extra = [plural] if plural and plural != "invariable" else []
            for f in sorted({base, *(fold(str(x)) for x in [*extra, *(it.get("forms") or [])])}):
                self.by_form.setdefault(f, []).append(iid)
        self.chunks = ChunkMatcher(it for iid, it in sorted(self.items.items()) if iid.startswith("c:"))
        self.names = frozenset(str(n) for n in allowlist.get("names") or [])
        self.interjections = frozenset(fold(str(x)) for x in allowlist.get("interjections") or [])
        self.transparent = {
            fold(str(t["form"])): str(t.get("gloss", "")) for t in allowlist.get("transparent") or [] if "form" in t
        }
        self.rules: dict[str, Mapping[str, Any]] = {}
        for r in disambiguation.get("context_rules") or []:
            forms = r.get("forms") or ([r["form"]] if "form" in r else [])
            for f in forms:
                self.rules[fold(str(f))] = r
        # an item ID, or {pos: [...]} (the Morph-it! readings to keep, as a context rule's choice)
        self.defaults: dict[str, str | Mapping[str, Any]] = {
            fold(str(k)): (v if isinstance(v, Mapping) else str(v))
            for k, v in (disambiguation.get("defaults") or {}).items()
        }

    # ------------------------------------------------------------ construction from the course

    @classmethod
    def from_course(cls, course: Course, morph: MorphIt) -> Lexicon:
        items: dict[str, dict[str, Any]] = {}
        item_unit: dict[str, str] = {}
        for u, _, it in course.items():
            if it.get("id"):
                items[str(it["id"])] = it
                item_unit[str(it["id"])] = u.id
        unit_index = course.unit_order()
        point_unit = {str(p["id"]): str(p.get("unit", "")) for p in course.grammar_points() if p.get("id")}
        allow = course.singles.get("allowlist")
        dis = course.singles.get("disambiguation")
        return cls(
            items=items,
            item_unit=item_unit,
            unit_index=unit_index,
            point_unit=point_unit,
            allowlist=(allow.data if allow else None) or {},
            disambiguation=(dis.data if dis else None) or {},
            morph=morph,
            detector=Detector(course.detection_rules()),
            intro=introductions(course, items, item_unit),
            slot_heads=slot_heads(course),
        )

    # ------------------------------------------------------------ helpers

    def compatible(self, a: Analysis, item: Mapping[str, Any]) -> bool:
        cats = POS_CATEGORIES.get(str(item.get("pos", "")), ())
        return any_pos(a.category, cats)

    def synthesise(self, item: Mapping[str, Any], form: str) -> tuple[Analysis, ...]:
        pos = str(item.get("pos", ""))
        lemma = str(item.get("it", form))
        if pos == "noun":
            g = str(item.get("gender", "m"))
            # mf nouns for people: the base form is masculine, the other forms feminine (amico / amica)
            gender = "F" if g == "f" or (g == "mf" and form != fold(lemma)) else "M"
            plural = str(item.get("plural", ""))
            numbers = ["p", "s"] if plural == "invariable" else (["p"] if form == fold(plural) else ["s"])
            return tuple(Analysis(lemma, f"NOUN-{gender}", n, synthetic=True) for n in numbers)
        return (Analysis(lemma, SYNTH_CATEGORY.get(pos, "X"), "", synthetic=True),)

    def function_point(self, analyses: Sequence[Analysis], norm: str) -> tuple[str, tuple[Analysis, ...]] | None:
        """Articles and articulated prepositions map to grammar points, not items."""
        artpre = tuple(a for a in analyses if any_pos(a.category, ("ARTPRE",)))
        if artpre:
            return (ARTPRE_LO_GLI if norm in ARTPRE_LO_GLI_FORMS else ARTPRE), artpre
        art = tuple(a for a in analyses if any_pos(a.category, ("ART",)))
        if art:
            return (INDEFINITE if norm in INDEFINITE_FORMS else DEFINITE), art
        return None

    def candidates(
        self, analyses: Sequence[Analysis], norm: str, *, synthesise: bool = True
    ) -> dict[str, tuple[Analysis, ...]]:
        cands: dict[str, tuple[Analysis, ...]] = {}
        for iid in self.by_form.get(norm, []):
            item = self.items[iid]
            compat = tuple(a for a in analyses if self.compatible(a, item))
            if compat:
                cands[iid] = compat
            elif synthesise:
                cands[iid] = self.synthesise(item, norm)
        if not cands:
            for a in analyses:
                if any_pos(a.category, ("ART", "ARTPRE")):
                    continue
                for iid in self.by_lemma.get(fold(a.lemma), []):
                    if self.compatible(a, self.items[iid]):
                        cands[iid] = (*cands.get(iid, ()), a)
        fp = self.function_point(analyses, norm)
        if fp:
            cands[fp[0]] = fp[1]
        return cands

    def name_readings(self, surface: str) -> tuple[Analysis, ...]:
        """An allowlisted name's readings: Morph-it!'s for its exact form, plus a synthetic proper-noun reading when
        none is one (*Federica*, *Mimì*), so to the *la / l'* rule every name is a proper noun (CL7)."""
        raw = self.morph.get(surface)
        if any(any_pos(x.category, ("NPR",)) for x in raw):
            return raw
        return (*raw, Analysis(surface, "NPR", synthetic=True))

    def pos_readings(self, raw: Sequence[Analysis], choice: Mapping[str, Any]) -> tuple[Analysis, ...]:
        """The Morph-it! readings a `{pos: [...]}` choice keeps."""
        cats = [str(x) for x in choice.get("pos") or []]
        return tuple(x for x in raw if any_pos(x.category, cats))

    def context_readings(self, a: TokAnn, lemmas: Mapping[str, Any]) -> tuple[Analysis, ...]:
        """What a neighbour's context rule sees of this token (docs/04 § Annotation step 4): the readings of the items
        it can still resolve to after `lemmas:` and its default, never those of a homograph it can't be (a letter
        noun *o* next to *uno*). A chunk's tokens and tokens without candidates keep their Morph-it! readings; a form
        with a context rule of its own keeps every candidate's, since that rule hasn't chosen yet."""
        norm = a.norm
        if a.chunk is not None:
            return a.raw
        if norm in lemmas:
            choice = lemmas[norm]
            if isinstance(choice, Mapping):
                return self.pos_readings(a.raw, choice)
            item = self.items.get(str(choice))
            if item is None:
                return a.raw  # reported when the token is resolved
            return tuple(x for x in a.raw if self.compatible(x, item)) or self.synthesise(item, norm)
        if norm in self.rules:
            return a.raw + tuple(
                x
                for iid in self.by_form.get(norm, [])
                if not any(self.compatible(r, self.items[iid]) for r in a.raw)
                for x in self.synthesise(self.items[iid], norm)
            )
        default = self.defaults.get(norm)
        if isinstance(default, Mapping):
            return self.pos_readings(a.raw, default)
        cands = self.candidates(a.raw, norm)
        if len(cands) > 1 and default in cands:
            return cands[str(default)]
        if not cands:
            return a.raw
        return tuple(dict.fromkeys(x for an in cands.values() for x in an))

    def introduced_before(self, item_id: str, pos: Position) -> bool:
        at = self.intro.get(item_id)
        return at is not None and at < pos

    def is_noun(self, t: TokAnn) -> bool:
        if t.kind != WORD or t.chunk is not None:
            return False
        if t.item and t.item.startswith("w:") and LEXICAL_ARTICLE not in t.flags:
            return str(self.items[t.item].get("pos")) == "noun"
        # an allowlisted transparent noun (il bar, un euro) counts as a noun item here
        return t.item is None and t.norm in self.transparent and any(any_pos(a.category, ("NOUN",)) for a in t.raw)

    def is_adjective(self, t: TokAnn) -> bool:
        """An adjective item, or a word whose Morph-it! readings are all adjectives (buon, bel)."""
        if t.kind != WORD or t.chunk is not None:
            return False
        if t.item and t.item.startswith("w:"):
            return str(self.items[t.item].get("pos")) == "adj"
        return bool(t.raw) and all(any_pos(a.category, ("ADJ",)) for a in t.raw)

    # ------------------------------------------------------------ annotate one string

    def annotate(self, text: str, ctx: Ctx) -> Annotated:
        issues: list[Issue] = []
        lemmas = {fold(str(k)): v for k, v in (ctx.lemmas or {}).items()}
        lead, toks = tokenize(
            text,
            foreign=ctx.foreign,
            names=self.names,
            not_names=lemmas.keys(),
            markup=ctx.markup,
            protected=ctx.protected,
        )
        anns = [TokAnn(t) for t in toks]
        for a in anns:
            if a.kind == WORD:
                a.raw = self.morph.lookup(a.surface)
            elif a.kind == NAME:
                a.raw = a.context = self.name_readings(a.surface)

        # chunks first
        for s, e, cid in self.chunks.match(toks, self.slot_heads):
            for a in anns[s:e]:
                a.chunk = cid
                a.analyses = a.raw
        for a in anns:
            if a.kind == WORD:
                a.context = self.context_readings(a, lemmas)

        # line fields: gloss, recognise, lemmas
        glossable = frozenset({WORD, FOREIGN, NAME})
        for key, en in (ctx.gloss or {}).items():
            hits = find_sequences(toks, str(key), glossable)
            if not hits:
                issues.append(Issue("error", None, f"gloss key '{key}' is not in the line"))
            for s, e in hits:
                for a in anns[s:e]:
                    a.gloss = str(en)
        for key in ctx.recognise or ():
            hits = find_sequences(toks, str(key), glossable)
            if not hits:
                issues.append(Issue("error", None, f"recognise form '{key}' is not in the line"))
            for s, e in hits:
                for k in range(s, e):
                    anns[k].flags.add(RECOGNISE)
                    if anns[k].gloss is None:
                        issues.append(Issue("error", k, f"recognise form '{key}' needs a gloss on the line"))
        used_lemmas: set[str] = set()

        # resolve word tokens outside chunks
        for k, a in enumerate(anns):
            if a.kind != WORD or a.chunk is not None:
                continue
            self._resolve(anns, k, lemmas, used_lemmas, ctx, issues)
        if not ctx.shared_lemmas:
            for key in sorted(set(lemmas) - used_lemmas):
                issues.append(Issue("error", None, f"lemmas key '{key}' is not in the line"))

        # the lexical-article rule
        for k, a in enumerate(anns):
            if a.item not in LEXICAL_POINTS:
                continue
            point_unit = self.unit_index.get(self.point_unit.get(str(a.item), ""), -1)
            if ctx.unit >= point_unit:
                continue
            head = None
            if k + 1 < len(anns) and self.is_noun(anns[k + 1]):
                head = k + 1
            elif k + 2 < len(anns) and self.is_adjective(anns[k + 1]) and self.is_noun(anns[k + 2]):
                head = k + 2
            if head is not None:
                a.item = anns[head].item if anns[head].item else None
                a.head = head
                a.flags.add(LEXICAL_ARTICLE)

        # unknown tokens, glosses, sound words
        for k, a in enumerate(anns):
            if a.kind != WORD or a.chunk is not None or a.item is not None or LEXICAL_ARTICLE in a.flags:
                continue
            if a.candidates:  # ambiguous: already reported
                continue
            if a.norm in self.interjections or a.norm in self.transparent:
                a.flags.add(ALLOWLISTED)
                a.analyses = a.analyses or a.raw
                if a.norm in self.transparent and a.gloss is None:
                    a.gloss = self.transparent[a.norm] or None
                continue
            a.analyses = a.analyses or a.raw
            if a.gloss is not None or RECOGNISE in a.flags:
                continue
            a.flags.add(UNRESOLVED)
            if ctx.sound and (ctx.sound_glosses.get(a.surface) or ctx.sound_glosses.get(a.norm)):
                continue
            lemmas_here = sorted({x.lemma for x in a.raw})
            if ctx.pending:
                a.flags.add(PENDING)
                issues.append(Issue("pending", k, f"'{a.surface}' has no item yet (its unit's items file is missing)"))
            elif not ctx.strict:
                if not a.raw:
                    issues.append(
                        Issue("warning", k, f"'{a.surface}' has neither a Morph-it! analysis nor an item (a typo?)")
                    )
            else:
                what = ", ".join(lemmas_here) if lemmas_here else a.surface
                hint = "" if lemmas_here else " (no Morph-it! analysis either: a typo?)"
                issues.append(
                    Issue(
                        "error",
                        k,
                        f"untaught lemma '{what}' (token '{a.surface}'){hint}: add an item, gloss it as new in this "
                        "step, or rephrase",
                    )
                )

        # sound-pair words: listening material glossed in place (`glosses`), never "new" in a text
        if ctx.sound:
            for a in anns:
                if a.kind == WORD:
                    a.flags.add(SOUND)
                    a.gloss = a.gloss or ctx.sound_glosses.get(a.surface) or ctx.sound_glosses.get(a.norm)
        else:
            # new: glossed on the line and not introduced before this step
            for a in anns:
                if a.gloss is None or a.kind != WORD or ALLOWLISTED in a.flags:
                    continue
                ref = a.chunk or (a.item if a.item and a.item.startswith(("w:", "c:")) else None)
                if ref is None or not self.introduced_before(ref, ctx.pos):
                    a.flags.add(NEW)

        detections = self.detector.detect(anns)
        for d in detections:
            for a in anns[d.start : d.end + 1]:
                if d.point not in a.detections:
                    a.detections.append(d.point)
        return Annotated(text, lead, anns, detections, issues, frozenset(used_lemmas))

    def _resolve(
        self,
        anns: list[TokAnn],
        k: int,
        lemmas: Mapping[str, Any],
        used: set[str],
        ctx: Ctx,
        issues: list[Issue],
    ) -> None:
        a = anns[k]
        norm = a.norm
        if norm in lemmas:
            used.add(norm)
            choice = lemmas[norm]
            if isinstance(choice, str):
                if choice not in self.items:
                    issues.append(Issue("error", k, f"lemmas maps '{a.surface}' to unknown item {choice}"))
                    return
                item = self.items[choice]
                compat = tuple(x for x in a.raw if self.compatible(x, item))
                a.item, a.analyses = choice, compat or self.synthesise(item, norm)
                if not compat:
                    a.flags.add(SYNTHETIC)
                return
            cands = self._pos_filter(a, choice)
        else:
            cands = self.candidates(a.raw, norm)
            rule = self.rules.get(norm)
            if rule is not None:
                fired = any(
                    all(
                        _any_match(_neighbour(anns, k, -1 if side == "prev" else 1), spec)
                        for side, spec in (cond or {}).items()
                    )
                    for cond in rule.get("when_any") or []
                )
                choice = rule.get("choose") if fired else rule.get("otherwise")
                if isinstance(choice, str):
                    if choice not in cands:
                        issues.append(
                            Issue(
                                "error",
                                k,
                                f"disambiguation.yaml chooses {choice} for '{a.surface}', which is not a candidate "
                                f"(candidates: {', '.join(sorted(cands)) or 'none'})",
                            )
                        )
                        a.candidates = tuple(sorted(cands))
                        return
                    cands = {choice: cands[choice]}
                elif isinstance(choice, Mapping):
                    cands = self._pos_filter(a, choice)
            default = self.defaults.get(norm)
            if rule is None and isinstance(default, Mapping):
                cands = self._pos_filter(a, default)  # even with one candidate: it rules a reading out
            elif len(cands) > 1 and isinstance(default, str) and default in cands:
                cands = {default: cands[default]}
        if len(cands) == 1:
            (iid, an), *_ = cands.items()
            a.item, a.analyses = iid, an
            if any(x.synthetic for x in an):
                a.flags.add(SYNTHETIC)
            return
        if len(cands) > 1:
            a.candidates = tuple(sorted(cands))
            a.analyses = tuple(sorted({x for an in cands.values() for x in an}))
            msg = (
                f"ambiguous '{a.surface}': candidates {', '.join(a.candidates)}; add `lemmas: {{{norm}: <item>}}` to "
                "the line or a rule to content/disambiguation.yaml"
            )
            issues.append(Issue("error" if ctx.strict else "warning", k, msg))

    def _pos_filter(self, a: TokAnn, choice: Mapping[str, Any]) -> dict[str, tuple[Analysis, ...]]:
        kept = self.pos_readings(a.raw, choice)
        a.analyses = kept  # what the rule chose, even if no item matches it (then the token is unknown)
        return self.candidates(kept, a.norm, synthesise=False)


def slot_heads(course: Course) -> dict[str, frozenset[str]]:
    """First words of what `{ME.home}` stands for (countries.yaml `home_phrase`, `alt_home_phrases`)."""
    doc = course.singles.get("countries")
    heads: set[str] = set()
    for c in ((doc.data if doc else None) or {}).get("countries") or []:
        for phrase in [c.get("home_phrase"), *(c.get("alt_home_phrases") or [])]:
            if isinstance(phrase, str) and phrase.split():
                heads.add(fold(phrase.split()[0]))
    return {"ME.home": frozenset(heads)} if heads else {}


# ---------------------------------------------------------------- introductions (for the `new` flag)

BIG = 10**6


def lesson_k(lesson_id: str) -> int:
    try:
        return int(lesson_id.rsplit(".l", 1)[1])
    except (IndexError, ValueError):
        return 0


def introductions(
    course: Course, items: Mapping[str, Mapping[str, Any]], item_unit: Mapping[str, str]
) -> dict[str, Position]:
    """Where each item is introduced, as far as annotation can tell (docs/05 § Introductions, docs/04 § Partial
    content): its lesson's preview step; else its lesson (introduced by the text that glosses it); else the start of
    its unit when the lesson file doesn't exist yet."""
    order = course.unit_order()
    previews: dict[str, tuple[int, int, int]] = {}
    lessons: set[str] = set()
    for u in course.units:
        for doc in u.lessons:
            lid = str((doc.data or {}).get("id", ""))
            lessons.add(lid)
            for s, step in enumerate((doc.data or {}).get("steps") or []):
                if isinstance(step, dict) and step.get("kind") == "preview":
                    for batch in step.get("batches") or []:
                        for iid in batch or []:
                            previews.setdefault(str(iid), (order[u.id], lesson_k(lid), s))
    out: dict[str, Position] = {}
    for iid, it in items.items():
        lesson = str(it.get("lesson") or "")
        unit = order.get(lesson.split(".")[0], order.get(item_unit.get(iid, ""), BIG))
        if iid in previews:
            out[iid] = previews[iid]
        elif lesson in lessons:
            out[iid] = (unit, lesson_k(lesson), BIG)
        else:
            out[iid] = (unit, -1, -1)
    return out
