"""Grammar detection and morphology unlocks from `content/grammar/detection.yaml` (docs/03, docs/04 step 5).

`detect` rules are token sequences. A matcher has optional `form` (regex searched in the lowercase surface with plain
apostrophes), `lemma` (list), `pos` (Morph-it! category prefixes on `-` boundaries), `morph` (regex searched in the
features after the colon), `optional: true` and `any: true`. A matcher matches a token only if **every** analysis left
after disambiguation satisfies its lemma/pos/morph constraints (so an invariable noun, singular and plural, never counts
as a plural); with `any: true` one analysis is enough, for verb forms Morph-it! also lists under another mood or as an
adjective (`parliamo` ind/impr/sub, `finito` participle/adjective). A token without analyses matches only matchers
without such constraints. Tokens that get no detections
(inside chunks, lexical articles, names, numbers, foreign words, punctuation, slots) also break a sequence.

`unlock` entries name the verb morphology a point makes legal: `{lemmas: [essere] | "*", morph: regex}`.
`Detector.unlocks` answers, for a verb token's analyses, which points would make each analysis legal; the level gate
passes a token when any analysis is unlocked by an introduced point (docs/04 § Check 2).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from itcontent.morphit import Analysis


class DetectionRuleError(ValueError):
    pass


class Detectable(Protocol):
    @property
    def norm(self) -> str: ...

    @property
    def analyses(self) -> Sequence[Analysis]: ...

    @property
    def detectable(self) -> bool: ...


@dataclass(frozen=True)
class Matcher:
    form: re.Pattern[str] | None = None
    lemma: frozenset[str] | None = None
    pos: tuple[str, ...] | None = None
    morph: str | None = None
    optional: bool = False
    any: bool = False  # one analysis is enough (default: every analysis must match)

    @property
    def needs_analyses(self) -> bool:
        return self.lemma is not None or self.pos is not None or self.morph is not None

    def matches(self, tok: Detectable) -> bool:
        if not tok.detectable:
            return False
        if self.form is not None and not self.form.search(tok.norm):
            return False
        if not self.needs_analyses:
            return True
        quantifier = any if self.any else all
        return bool(tok.analyses) and quantifier(
            a.matches(lemma=self.lemma, pos=self.pos, morph=self.morph) for a in tok.analyses
        )


@dataclass(frozen=True)
class Unlock:
    lemmas: frozenset[str] | None  # None = every verb ("*")
    morph: str

    def allows(self, a: Analysis) -> bool:
        lemma_ok = self.lemmas is None or a.lemma in self.lemmas
        return a.is_verb() and lemma_ok and bool(re.search(self.morph, a.features))


@dataclass(frozen=True)
class Rule:
    id: str
    seqs: tuple[tuple[Matcher, ...], ...]
    unlock: tuple[Unlock, ...]

    @property
    def detects(self) -> bool:
        return bool(self.seqs)


@dataclass(frozen=True, order=True)
class Detection:
    start: int  # token index
    end: int  # last token index (inclusive)
    point: str


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return list(v) if isinstance(v, list | tuple) else [v]


def _matcher(spec: dict[str, Any], where: str) -> Matcher:
    unknown = set(spec) - {"form", "lemma", "pos", "morph", "optional", "any"}
    if unknown:
        raise DetectionRuleError(f"{where}: unknown matcher keys {sorted(unknown)}")
    try:
        form = re.compile(str(spec["form"])) if "form" in spec else None
        morph = str(spec["morph"]) if "morph" in spec else None
        if morph is not None:
            re.compile(morph)
    except re.error as exc:
        raise DetectionRuleError(f"{where}: bad regex ({exc})") from exc
    return Matcher(
        form=form,
        lemma=frozenset(str(x) for x in _as_list(spec["lemma"])) if "lemma" in spec else None,
        pos=tuple(str(x) for x in _as_list(spec["pos"])) if "pos" in spec else None,
        morph=morph,
        optional=bool(spec.get("optional")),
        any=bool(spec.get("any")),
    )


def parse_rules(rules: Iterable[dict[str, Any]]) -> list[Rule]:
    out: list[Rule] = []
    for r in rules:
        rid = str(r.get("id"))
        seqs: list[tuple[Matcher, ...]] = []
        detect = r.get("detect", "none")
        if detect != "none":
            for k, entry in enumerate(_as_list(detect)):
                seq = entry.get("seq") if isinstance(entry, dict) else None
                if not seq:
                    raise DetectionRuleError(f"{rid}: detect[{k}] needs a non-empty seq")
                ms = tuple(_matcher(m, f"{rid}: detect[{k}].seq[{j}]") for j, m in enumerate(seq))
                if all(m.optional for m in ms):
                    raise DetectionRuleError(f"{rid}: detect[{k}] has only optional matchers")
                seqs.append(ms)
        unlocks: list[Unlock] = []
        for k, u in enumerate(_as_list(r.get("unlock"))):
            lemmas = u.get("lemmas")
            if "morph" not in u:
                raise DetectionRuleError(f"{rid}: unlock[{k}] needs morph")
            unlocks.append(
                Unlock(None if lemmas == "*" else frozenset(str(x) for x in _as_list(lemmas)), str(u["morph"]))
            )
        out.append(Rule(rid, tuple(seqs), tuple(unlocks)))
    return out


def _match(seq: Sequence[Matcher], j: int, toks: Sequence[Detectable], i: int) -> int | None:
    """End index (exclusive) of a match of seq[j:] at toks[i:], optional matchers present before absent."""
    if j == len(seq):
        return i
    m = seq[j]
    if i < len(toks) and m.matches(toks[i]):
        end = _match(seq, j + 1, toks, i + 1)
        if end is not None:
            return end
    if m.optional:
        return _match(seq, j + 1, toks, i)
    return None


class Detector:
    def __init__(self, rules: Iterable[dict[str, Any]]) -> None:
        self.rules = parse_rules(rules)
        self.by_id = {r.id: r for r in self.rules}

    def detect(self, toks: Sequence[Detectable]) -> list[Detection]:
        found: set[Detection] = set()
        for rule in self.rules:
            for seq in rule.seqs:
                for i in range(len(toks)):
                    if not toks[i].detectable:
                        continue
                    end = _match(seq, 0, toks, i)
                    if end is not None and end > i:
                        found.add(Detection(i, end - 1, rule.id))
        return sorted(found)

    def unlocks(self, analyses: Iterable[Analysis]) -> list[tuple[Analysis, frozenset[str]]]:
        """For each verb analysis, the grammar points whose `unlock` makes it legal (empty: nothing does)."""
        out = []
        for a in analyses:
            if a.is_verb():
                out.append((a, frozenset(r.id for r in self.rules for u in r.unlock if u.allows(a))))
        return out

    def unlocking_points(self, analyses: Iterable[Analysis]) -> frozenset[str]:
        """Every point that would make at least one analysis of this verb token legal."""
        return frozenset(p for _, pts in self.unlocks(analyses) for p in pts)

    def is_legal(self, analyses: Iterable[Analysis], introduced: Iterable[str]) -> bool:
        """A verb token is legal if any of its verb analyses is unlocked by an introduced point (non-verbs: True)."""
        intro = set(introduced)
        verbs = self.unlocks(analyses)
        return not verbs or any(pts & intro for _, pts in verbs)
