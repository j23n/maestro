"""What texts and exercises require, and what steps introduce (docs/04 § Requirements, docs/05 § Introductions).

Requirements come from the annotation tokens of the strings a learner sees or produces, per skill:

- a word or chunk token requires its item (a token inside a chunk requires only the chunk; a lexical article only
  its noun) for the skills of its context; an article or articulated preposition requires its grammar point, and every
  grammar detection requires its point, as `read` (shown or heard) or `recall` (in a model answer), never `listen` or
  `speak`;
- tokens flagged new in this step (glossed) or recognise-only require nothing, and neither does a detection that
  covers one of them; names, numbers, foreign words, punctuation and allowlisted words require nothing;
- contexts: `read` for texts, prompts (`prompt_it`, `context_it`), options, match left sides, tiles, writing labels,
  repeat and conversation `say`, and sources; `listen` (words) for what is heard without text: dictation `say`,
  sound-pair words and `audio_text`; texts of listening steps and audio texts require `read` and `listen`; `recall`
  for model answers: the first expansion of a recall answer, a cloze gap (the rest of the cloze sentence is `read`),
  the first sentence-building order, the first accepted expansion of each conversation intent, conversation `help`,
  and talk and writing models. Other expansions, near-misses and content-point patterns require nothing.
- an exercise also requires its primary targets.

A lesson's target grammar points (its notes' `grammar`) are excluded from the steps of that lesson that come before
the note (its story). The step that introduces an item does not require it: LearningCore subtracts `step_introduces`
when the step is entered, so the rows here stay complete for reviews.

`step_introduces` ports `IntroductionRules.stepIntroduces` (LearningCore) and must agree with it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from itcontent.pack.common import BuildError
from itcontent.pack.locks import LockString

Pair = tuple[str, str]  # (item id, skill)
SKILL_ORDER = {"read": 0, "listen": 1, "recall": 2, "speak": 3}


@dataclass(frozen=True)
class Context:
    """The skills a string's tokens require: `words` for word and chunk items, `grammar` for grammar points."""

    words: tuple[str, ...]
    grammar: str


READ = Context(("read",), "read")
LISTEN = Context(("listen",), "read")
HEARD_TEXT = Context(("read", "listen"), "read")  # audio-first texts: listening steps and audio texts
RECALL = Context(("recall",), "recall")


def sort_pairs(pairs: Iterable[Pair]) -> list[Pair]:
    return sorted(set(pairs), key=lambda p: (p[0], SKILL_ORDER.get(p[1], 9)))


def string_pairs(
    s: LockString,
    ctx: Context,
    *,
    exclude: frozenset[str] = frozenset(),
    keep: Callable[[int], bool] | None = None,
) -> set[Pair]:
    """The (item, skill) pairs a string requires in a context; `keep` limits it to some token indices."""
    out: set[Pair] = set()
    skipped: set[int] = set()
    for k, t in enumerate(s.tokens):
        flags = set(t.get("flags") or ())
        if "new" in flags or "recognise" in flags:
            skipped.add(k)
            continue
        if keep is not None and not keep(k):
            continue
        if t.get("kind") != "word":
            continue
        item = t.get("chunk") or t.get("item")
        if not item:
            continue
        if item.startswith("g:"):
            if item not in exclude:
                out.add((item, ctx.grammar))
        else:
            out.update((item, skill) for skill in ctx.words)
    for d in s.detections:
        span = range(d.first, d.last + 1)
        if d.point in exclude or any(k in skipped for k in span):
            continue
        if keep is not None and not any(keep(k) for k in span):
            continue
        out.add((d.point, ctx.grammar))
    return out


def cloze_pairs(s: LockString, *, exclude: frozenset[str] = frozenset()) -> set[Pair]:
    """A cloze's model string: the gap is a model answer (`recall`), the rest of the sentence is shown (`read`)."""
    if s.gap is None:
        raise BuildError(f"{s.where()}: the cloze annotation has no gap")
    first, last = s.gap

    def in_gap(k: int) -> bool:
        return first <= k <= last

    return string_pairs(s, RECALL, exclude=exclude, keep=in_gap) | string_pairs(
        s, READ, exclude=exclude, keep=lambda k: not in_gap(k)
    )


# What each role of an exercise string requires (docs/04 § Requirements); None: nothing.
ROLE_CONTEXT: dict[str, Context | None] = {
    "title": None,  # titles are exempt from every gate
    "prompt": READ,
    "context": READ,
    "option": READ,
    "pair": READ,
    "tile": READ,
    "label": READ,
    "help": RECALL,  # help phrases are model answers (check 2's production gate)
    "model": RECALL,
    "sound": LISTEN,
    "point": None,
    "field": None,
    "near": None,
}
SAY_CONTEXT = {"dictation": LISTEN, "repeat": READ, "conversation": READ}
MODEL_ROLES = frozenset({"answer", "accept"})  # recall answers, sentence-building orders, conversation intents


def exercise_string_pairs(fmt: str, s: LockString, *, exclude: frozenset[str] = frozenset()) -> set[Pair]:
    """What one string of an exercise (outside its texts) requires."""
    if s.role == "cloze":
        return cloze_pairs(s, exclude=exclude) if s.model else set()
    if s.role in MODEL_ROLES:
        return string_pairs(s, RECALL, exclude=exclude) if s.model else set()
    if s.role == "say":
        ctx = SAY_CONTEXT.get(fmt)
        if ctx is None:
            raise BuildError(f"{s.where()}: no requirement rule for `say` in a {fmt} exercise")
        return string_pairs(s, ctx, exclude=exclude)
    if s.role not in ROLE_CONTEXT:
        raise BuildError(f"{s.where()}: no requirement rule for strings with role {s.role!r}")
    ctx = ROLE_CONTEXT[s.role]
    return string_pairs(s, ctx, exclude=exclude) if ctx is not None else set()


# ---------------------------------------------------------------- introductions (docs/05 § Introductions)


@dataclass
class ItemInfo:
    id: str
    kind: str  # word | chunk | grammar | sound
    unit: str
    skills: dict[str, str] = field(default_factory=dict)  # skill → status (P, R, chunk)
    grammar_status: str | None = None
    exemplifies: tuple[str, ...] = ()


@dataclass
class StepInfo:
    """What a step contributes to introductions, in course order."""

    id: str
    unit: str
    kind: str
    preview_items: list[str] = field(default_factory=list)
    new_text_items: list[str] = field(default_factory=list)
    note_grammar: list[str] = field(default_factory=list)
    sound_items: list[str] = field(default_factory=list)
    detected_grammar: list[str] = field(default_factory=list)


def standard_skills(item: ItemInfo) -> list[str]:
    """Skills a whole item is introduced for: words and chunks read and listen, plus recall and speak where P;
    grammar points read, plus recall if P; sounds listen."""
    if item.kind in ("word", "chunk"):
        return ["read", "listen"] + [s for s in ("recall", "speak") if item.skills.get(s) == "P"]
    if item.kind == "grammar":
        return ["read"] + (["recall"] if item.skills.get("recall") == "P" else [])
    return ["listen"]


def step_introduces(steps: Sequence[StepInfo], items: Mapping[str, ItemInfo]) -> dict[str, list[Pair]]:
    """`step_introduces` for steps given in course order (LearningCore's `IntroductionRules.stepIntroduces`)."""
    result: dict[str, set[Pair]] = {}
    first_note: dict[str, int] = {}  # R and chunk points: their earliest note

    for index, step in enumerate(steps):
        rows = result.setdefault(step.id, set())
        if step.kind == "preview":
            for iid in step.preview_items:
                item = items.get(iid)
                if item is None or item.kind == "grammar":
                    continue
                rows.update((iid, s) for s in standard_skills(item))
        elif step.kind in ("story", "listening", "reading"):
            for iid in step.new_text_items:
                item = items.get(iid)
                if item is None or item.kind == "grammar":
                    continue
                rows.update({(iid, "read"), (iid, "listen")})
        elif step.kind == "note":
            for iid in step.note_grammar:
                item = items.get(iid)
                if item is None:
                    continue
                if item.grammar_status == "P":
                    rows.update({(iid, "read"), (iid, "recall")})
                else:
                    first_note.setdefault(iid, index)
        elif step.kind == "sounds":
            rows.update((iid, "listen") for iid in step.sound_items)

    # R and chunk points: the earliest of their note, the first preview in their own unit with a chunk that
    # exemplifies them, or else the first story or listening step of their unit where they are detected.
    for point in sorted(items.values(), key=lambda i: i.id):
        if point.kind != "grammar" or point.grammar_status not in ("R", "chunk"):
            continue
        preview = next(
            (
                i
                for i, s in enumerate(steps)
                if s.kind == "preview"
                and s.unit == point.unit
                and any(point.id in items[x].exemplifies for x in s.preview_items if x in items)
            ),
            None,
        )
        story = None
        if preview is None:
            story = next(
                (
                    i
                    for i, s in enumerate(steps)
                    if s.kind in ("story", "listening") and s.unit == point.unit and point.id in s.detected_grammar
                ),
                None,
            )
        candidates = [c for c in (first_note.get(point.id), preview, story) if c is not None]
        if candidates:
            result.setdefault(steps[min(candidates)].id, set()).add((point.id, "read"))
    return {sid: sort_pairs(rows) for sid, rows in result.items() if rows}


# ---------------------------------------------------------------- scheduled skills (docs/05 § Skills)


def scheduled_skill(item: ItemInfo) -> str | None:
    """The one skill of an item that gets scheduled review cards (docs/05 table)."""
    if item.kind in ("word", "chunk"):
        if item.skills.get("recall") == "P":
            return "recall"
        return "read" if "read" in item.skills else None
    if item.kind == "grammar":
        if item.grammar_status == "P":
            return "recall"
        return "read"
    if item.kind == "sound":
        return "listen" if item.skills.get("listen") == "P" else None
    return None
