"""Check 2 · Level gate (docs/04): every text and exercise at its course position *p*.

What is gated, and how strictly (`scope`):

- **text** level: text lines and real-world layouts, prompts and context lines, conversation and dictation `say`,
  Italian choice options, match left sides, sentence-building tiles, writing field labels, note fragments, cells and
  examples (a note's own points are introduced by that note, so it can show them), and the sentence around a cloze
  gap. Words must be introduced (for reading) at or before *p*; verb forms must be unlocked by a P or R point
  introduced at or before *p*; every grammar detection must belong to such a point. The current lesson's target
  points count from its first text step on (the story comes before the note).
- **production** level (the production gate): the model answer — the first expansion of a recall `answer`, of a
  cloze gap and of the first `accept` pattern of each conversation intent, the first sentence-building order, every
  `help` phrase and talk/writing `model`s. Items must be introduced for `recall`; detections and verb forms need a
  point with status P introduced at or before *p*. Chunk tokens are exempt from the grammar part only.
- **not gated:** titles (unit, lesson, story and conversation titles), other expansions and later patterns, near
  misses, talk and writing points, items' `recall_answer`, and sound-pair words (listening material glossed in place).

Exempt tokens: chunk tokens (morphology and construction; the chunk itself must be introduced), `recognise` tokens
(every gate; listed in the report), glossed tokens new in this step (the lemma gate), allowlisted words, lexical
articles (their noun is gated), names, numbers and foreign words. Lines with `allow: {reason}` skip the morphology
gate and are listed in the report. A detection of a point with status `chunk` outside a chunk always fails: such
points are taught only as chunks (`vorrei` yes, `vorrebbe` no).

**New-token budget:** (tokens new in this step + `recognise` tokens) / word tokens per text, at most
`story_new_token_max` (stories, listening and every other non-real-world text) or `real_world_new_token_max`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from itcontent.checks.context import (
    ALLOWLISTED,
    LEXICAL_ARTICLE,
    NEW,
    PENDING,
    RECOGNISE,
    SOUND,
    CheckContext,
    Intro,
    Pos,
    Str,
    Tok,
)
from itcontent.course import Loc

UNGATED_ROLES = frozenset({"title", "near", "point", "field", "recall_answer"})
PRODUCTION_ROLES = frozenset({"help", "model"})


@dataclass
class Budget:
    text: str
    file: str
    path: tuple
    kind: str
    words: int = 0
    new: int = 0
    recognise: int = 0
    limit: float = 0.0

    @property
    def share(self) -> float:
        return (self.new + self.recognise) / self.words if self.words else 0.0


@dataclass
class Exemption:
    """A line the morphology gate skips (`allow`) or a `recognise` form: listed in the report."""

    kind: str  # allow | recognise
    ref: str
    file: str
    path: tuple
    text: str
    detail: str


@dataclass
class LevelResult:
    budgets: list[Budget] = field(default_factory=list)
    exemptions: list[Exemption] = field(default_factory=list)


def scope(s: Str) -> str | None:
    """'text', 'production', 'cloze' (text with a production-gated gap) or None (not gated)."""
    if s.pos is None or s.container in ("unit", "items") or s.role in UNGATED_ROLES:
        return None
    if s.role in ("answer", "accept"):
        return "production" if s.model else None
    if s.role == "cloze":
        return "cloze" if s.model else None
    if s.role in PRODUCTION_ROLES:
        return "production"
    return "text"


def _production(s: Str, sc: str, first: int, last: int) -> bool:
    if sc == "production":
        return True
    return sc == "cloze" and s.gap is not None and first <= s.gap[1] and last >= s.gap[0]


def _quote(s: Str) -> str:
    return s.text if len(s.text) <= 80 else s.text[:77] + "…"


class LevelGate:
    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx
        self.result = LevelResult()
        self._legal: dict[tuple[Pos, bool, frozenset[str]], dict[str, Intro | None]] = {}

    # ------------------------------------------------------------ helpers

    def where(self, intro: Intro | None) -> str:
        return intro.step if intro else "?"

    def legal_points(self, s: Str, production: bool) -> dict[str, Intro | None]:
        """Points whose forms are legal in `s`: introduced at or before p (P or R in texts, P in answers), plus the
        lesson's own targets in its story (value None: no introduction needed)."""
        assert s.pos is not None
        targets = frozenset() if production else self.ctx.targets_at(s)
        key = (s.pos, production, targets)
        if key not in self._legal:
            skill = "recall" if production else "read"
            ok = ("P",) if production else ("P", "R")
            out: dict[str, Intro | None] = {}
            for pid in self.ctx.points:
                if self.ctx.point_status(pid) not in ok:
                    continue
                hit = self.ctx.intros.find(pid, s.pos, skill)
                if hit:
                    out[pid] = hit
            for pid in targets:
                if self.ctx.point_status(pid) in ok:
                    out.setdefault(pid, None)
            self._legal[key] = out
        return self._legal[key]

    def error(self, s: Str, rule: str, message: str) -> None:
        self.ctx.add("error", 2, rule, s.loc, f'{message} (in "{_quote(s)}")')

    def at(self, s: Str) -> str:
        return s.step or self.ctx.describe(s.pos)

    # ------------------------------------------------------------ lemma gate

    def lemma(self, s: Str, t: Tok, ref: str, production: bool) -> None:
        assert s.pos is not None
        skill = "recall" if production else "read"
        hit = self.ctx.intros.find(ref, s.pos, skill)
        if hit:
            self.ctx.note_fallback(ref, hit, s)
            return
        what = f"'{t.surface}' ({ref})"
        if production:
            status = self.ctx.item_status(ref).get("recall")
            first = self.ctx.intros.first(ref, "recall")
            if status and status != "P":
                why = f"{ref} has status {status} for recall (recognition only), so it can't be in a model answer"
            elif first:
                why = f"{ref} is introduced for recall only at {first.step}"
            else:
                why = f"{ref} is never introduced for recall"
            self.error(s, "production", f"{what} in a model answer at {self.at(s)}: {why}")
            return
        first = self.ctx.intros.first(ref)
        when = f"it is introduced at {first.step}" if first else "it is never introduced"
        self.error(
            s,
            "lemma",
            f"{what} is untaught at {self.at(s)}: {when}. Preview it earlier, gloss it as new on this line, or rephrase",
        )

    # ------------------------------------------------------------ morphology gate

    def morphology(self, s: Str, t: Tok, production: bool) -> None:
        verbs = self.ctx.detector.unlocks(t.analyses)
        if not verbs:
            return
        if all(a.synthetic and not a.features for a, _ in verbs):
            self.ctx.add(
                "warning",
                2,
                "morphology",
                s.loc,
                f"'{t.surface}': Morph-it! has no verb reading for it, so its morphology isn't checked",
            )
            return
        legal = self.legal_points(s, production)
        for _, pts in verbs:
            hits = [legal[p] for p in sorted(pts) if p in legal]
            if hits:
                if all(h is not None and h.fallback for h in hits):
                    pid = next(p for p in sorted(pts) if p in legal)
                    intro = legal[pid]
                    if intro is not None:
                        self.ctx.note_fallback(pid, intro, s)
                return
        readings = ", ".join(sorted({f"{a.lemma} {a.tag}" for a, _ in verbs}))
        unlockers = sorted({p for _, pts in verbs for p in pts})
        if unlockers:
            named = ", ".join(f"{p} ({self.ctx.point_unit(p)}, {self.ctx.point_status(p)})" for p in unlockers)
            why = f"only {named} unlock{'s' if len(unlockers) == 1 else ''} it"
            if production and all(self.ctx.point_status(p) != "P" for p in unlockers):
                why += "; a model answer needs a P point"
        else:
            why = "no grammar point unlocks this form (conditional, future, imperfetto…): rephrase or use a chunk"
        rule = "production" if production else "morphology"
        where = "in a model answer " if production else ""
        self.error(s, rule, f"verb form '{t.surface}' ({readings}) is not unlocked {where}at {self.at(s)}: {why}")

    # ------------------------------------------------------------ construction gate

    def construction(self, s: Str, sc: str) -> None:
        assert s.pos is not None
        for d in s.detections:
            span = s.tokens[d.start : d.end + 1]
            if not span or any(RECOGNISE in t.flags for t in span):
                continue
            production = _production(s, sc, d.start, d.end)
            words = " ".join(t.surface for t in span)
            status = self.ctx.point_status(d.point)
            if not status:
                continue  # not a course point: lint reports the rule
            rule = "production" if production else "construction"
            if status == "chunk":
                self.error(
                    s,
                    rule,
                    f"'{words}' is {d.point}, which is taught only as chunks (status chunk): use the chunk or rephrase",
                )
                continue
            legal = self.legal_points(s, production)
            if d.point in legal:
                intro = legal[d.point]
                if intro is not None:
                    self.ctx.note_fallback(d.point, intro, s)
                continue
            unit = self.ctx.point_unit(d.point)
            first = self.ctx.intros.first(d.point, "recall" if production else "read")
            if production and status != "P":
                why = f"it has status {status} (recognition only); a model answer needs P points"
            elif first:
                why = f"it is introduced at {first.step}"
            else:
                why = f"it is a {unit} point that is never introduced"
            where = "in a model answer " if production else ""
            self.error(s, rule, f"'{words}' is {d.point} ({unit}), not taught {where}at {self.at(s)}: {why}")

    # ------------------------------------------------------------ one string

    def gate(self, s: Str) -> None:
        sc = scope(s)
        if sc is None:
            return
        allow = isinstance((s.line or {}).get("allow"), dict)
        prev_chunk: str | None = None
        for t in s.tokens:
            chunk_start = t.chunk is not None and t.chunk != prev_chunk
            prev_chunk = t.chunk
            if not t.is_word or SOUND in t.flags or PENDING in t.flags or RECOGNISE in t.flags:
                continue
            production = _production(s, sc, t.i, t.i)
            if t.chunk:
                if chunk_start and not (NEW in t.flags and not production):
                    self.lemma(s, t, t.chunk, production)
                continue
            if (
                LEXICAL_ARTICLE not in t.flags
                and ALLOWLISTED not in t.flags
                and t.item
                and t.item.startswith(("w:", "c:"))
                and not (NEW in t.flags and not production)
            ):
                self.lemma(s, t, t.item, production)
            if not allow:
                self.morphology(s, t, production)
        self.construction(s, sc)

    # ------------------------------------------------------------ budgets and exemptions

    def budgets(self) -> None:
        gate = self.ctx.checker.get("level_gate") or {}
        story_max = float(gate.get("story_new_token_max", 0.05))
        real_max = float(gate.get("real_world_new_token_max", 0.10))
        by_text: dict[tuple[str, tuple], Budget] = {}
        for s in self.ctx.strings:
            if s.text_ref is None or s.role not in ("line", "layout") or s.pos is None:
                continue
            tr = s.text_ref
            key = (tr.loc.file, tr.loc.path)
            kind = str(tr.data.get("kind", ""))
            b = by_text.get(key)
            if b is None:
                limit = real_max if kind == "real_world" else story_max
                b = by_text[key] = Budget(tr.id, tr.loc.file, tr.loc.path, kind, limit=limit)
            for t in s.tokens:
                if not t.is_word:
                    continue
                b.words += 1
                if RECOGNISE in t.flags:
                    b.recognise += 1
                elif NEW in t.flags:
                    b.new += 1
        for b in sorted(by_text.values(), key=lambda b: (b.file, b.path)):
            self.result.budgets.append(b)
            if b.words and b.share > b.limit + 1e-9:
                which = "real-world texts" if b.kind == "real_world" else "stories and listening"
                self.ctx.add(
                    "error",
                    2,
                    "budget",
                    _loc(b.file, b.path),
                    f"new-token budget: {b.new} new + {b.recognise} recognise of {b.words} word tokens in {b.text} "
                    f"= {b.share:.1%}, above {b.limit:.0%} for {which}: preview some items or replace them with "
                    "known words",
                )

    def exemptions(self) -> None:
        seen: set[tuple[str, tuple]] = set()
        for s in self.ctx.strings:
            if s.role != "line" or s.line is None:
                continue
            key = (s.file, s.path)
            if key in seen:
                continue
            seen.add(key)
            allow = s.line.get("allow")
            if isinstance(allow, dict):
                reason = str(allow.get("reason", ""))
                self.result.exemptions.append(Exemption("allow", s.ref or "", s.file, s.path, s.text, reason))
                if not reason.strip() and (self.ctx.checker.get("level_gate") or {}).get("allow_requires_reason", True):
                    self.ctx.add("error", 2, "morphology", s.loc, "allow: needs a reason (it is listed in the report)")
            forms = [t.surface for t in s.tokens if RECOGNISE in t.flags]
            if forms:
                self.result.exemptions.append(
                    Exemption("recognise", s.ref or "", s.file, s.path, s.text, ", ".join(forms))
                )

    def run(self) -> LevelResult:
        for s in self.ctx.strings:
            self.gate(s)
        self.budgets()
        self.exemptions()
        self.ctx.report_fallbacks()
        return self.result


def _loc(file: str, path: tuple) -> Loc:
    return Loc(file, path)


def check_level(ctx: CheckContext) -> LevelResult:
    return LevelGate(ctx).run()
