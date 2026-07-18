"""LLM drafting of pack items (`maestro-pack generate`).

Every item family can be drafted (drills, readings, listenings, vocab
cards, speaking prompts, writing prompts, grammar refs), scoped four
ways:

- ``--gp <id>``        one grammar point (the classic spec cell)
- ``--scenario <id>``  a scenario: its grammar + functions + setting
- ``--cando <id>``     a can-do descriptor and its decomposition
- ``--theme "..."``    a free theme (e.g. "Ferragosto"), with --level;
                       the prompt carries the allowed grammar/function/
                       vocab inventories for that level so thematic
                       content stays curriculum-grounded

Two modes:

- **API mode** (default): calls the Anthropic API (lazy import; needs
  ANTHROPIC_API_KEY). One call drafts a whole batch.
- **File mode** (``--from-file``): parses a prepared response — the same
  YAML the model would return. Used by tests, and for drafting sessions
  run outside this CLI (any chat session can act as the drafting model).

Drafts land in ``packs/<lang>/<family>/<slug>.draft.yaml`` with
``status: draft``; they are invisible to ``build`` until the review tool
(or a human edit) promotes them to ``reviewed``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from authoring.build_pack import load_pack_sources, validate_pack
from authoring.pack_schemas import (
    DrillItem,
    GrammarRefItem,
    ListeningItem,
    ReadingItem,
    SpeakingPromptItem,
    VocabCardItem,
    WritingPromptItem,
)
from authoring.spec_schemas import Spec

DEFAULT_MODEL = "claude-sonnet-5"

_LEVEL_ORDER = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]


def _levels_upto(level: str) -> set[str]:
    return set(_LEVEL_ORDER[: _LEVEL_ORDER.index(level) + 1])


def slugify(text: str) -> str:
    """A string safe for item ids and filenames (a-z0-9_ only)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


# --------------------------------------------------------------------------
# Scope: what part of the curriculum a batch is drafted for.


@dataclass
class Scope:
    kind: str  # gp | scenario | cando | theme
    slug: str
    level: str
    title: str
    context_lines: list[str] = field(default_factory=list)
    # Ids the model is allowed to tag evidence with.
    grammar_ids: list[str] = field(default_factory=list)
    function_ids: list[str] = field(default_factory=list)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def resolve_scope(
    spec: Spec,
    gp: str | None = None,
    scenario: str | None = None,
    cando: str | None = None,
    theme: str | None = None,
    level: str | None = None,
) -> Scope:
    given = [x for x in (gp, scenario, cando, theme) if x]
    if len(given) != 1:
        raise ValueError(
            "scope: give exactly one of --gp, --scenario, --cando, --theme"
        )

    if gp:
        g = next((x for x in spec.grammar_points if x.id == gp), None)
        if g is None:
            raise ValueError(f"unknown grammar point: {gp}")
        examples = [_strip_html(e) for e in g.examples[:6]]
        return Scope(
            kind="gp",
            slug=slugify(g.id),
            level=level or g.cefr_level,
            title=f"{g.label} ({g.id})",
            context_lines=[
                f"Grammar point: {g.id} ({g.cefr_level}) — {g.label}",
                f"Description: {g.description or g.source.descriptor_label or ''}",
                "Reference examples:",
                *[f"- {e}" for e in examples],
            ],
            grammar_ids=[g.id],
        )

    if scenario:
        s = next((x for x in spec.scenarios if x.id == scenario), None)
        if s is None:
            raise ValueError(f"unknown scenario: {scenario}")
        gp_labels = {g.id: g.label for g in spec.grammar_points}
        cf_labels = {c.id: c.label for c in spec.communicative_functions}
        return Scope(
            kind="scenario",
            slug=slugify(s.id),
            level=level or s.cefr_level,
            title=f"{s.label} ({s.id})",
            context_lines=[
                f"Scenario: {s.id} ({s.cefr_level}) — {s.label}",
                f"Setting: {s.scene_setting or s.description}",
                f"Story so far: {s.overview or s.depths[0]}",
                "Scenario grammar (tag evidence with these):",
                *[f"- {i}: {gp_labels.get(i, '?')}" for i in s.grammar_ids],
                "Scenario functions (tag evidence with these):",
                *[f"- {i}: {cf_labels.get(i, '?')}" for i in s.function_ids],
            ],
            grammar_ids=list(s.grammar_ids),
            function_ids=list(s.function_ids),
        )

    if cando:
        c = next((x for x in spec.can_dos if x.id == cando), None)
        if c is None:
            raise ValueError(f"unknown can-do: {cando}")
        gp_labels = {g.id: g.label for g in spec.grammar_points}
        cf_labels = {f.id: f.label for f in spec.communicative_functions}
        return Scope(
            kind="cando",
            slug=slugify(c.id),
            level=level or c.cefr_level,
            title=c.label,
            context_lines=[
                f"Can-do descriptor: {c.id} ({c.cefr_level}, {c.skill})",
                f"Descriptor: {c.label}",
                f"Theme: {c.theme}",
                "Required grammar (tag evidence with these):",
                *[f"- {i}: {gp_labels.get(i, '?')}" for i in c.grammar_ids],
                "Required functions (tag evidence with these):",
                *[f"- {i}: {cf_labels.get(i, '?')}" for i in c.function_ids],
                "An application item for the descriptor itself may also tag "
                f"evidence {{ axis: cando, id: {c.id} }}.",
            ],
            grammar_ids=list(c.grammar_ids),
            function_ids=list(c.function_ids),
        )

    # Theme mode: free topic, curriculum-grounded via allowed inventories.
    if not level:
        raise ValueError("--theme needs --level (the inventories to draw from)")
    levels = _levels_upto(level)
    gps = [g for g in spec.grammar_points if g.cefr_level in levels]
    cfs = [c for c in spec.communicative_functions if c.cefr_level in levels]
    return Scope(
        kind="theme",
        slug=slugify(theme),
        level=level,
        title=theme,
        context_lines=[
            f"Theme: {theme} (target level {level})",
            "Ground every item in this theme AND in the curriculum: tag "
            "evidence only with ids from the inventories below.",
            f"Allowed grammar ids ({len(gps)}):",
            ", ".join(g.id for g in gps),
            f"Allowed function ids ({len(cfs)}):",
            ", ".join(c.id for c in cfs),
        ],
        grammar_ids=[g.id for g in gps],
        function_ids=[c.id for c in cfs],
    )


# --------------------------------------------------------------------------
# Item-kind registry: model class, source dir, id prefix, response shape.


@dataclass(frozen=True)
class Kind:
    name: str
    model: type
    subdir: str
    id_prefix: str
    shape: str  # the per-entry YAML shape shown to the model
    guidance: str = ""


_SHAPE_DRILL = """\
- item_type: drill_cloze        # or drill_multiple_choice / drill_transform
  cefr_level: {level}
  prompt: "..."
  answers:
    - {{ text: "...", canonical: true }}
  distractor_feedback:
    "wrong answer": "why it's wrong"
  explanation: "..."
  evidence:
    - {{ axis: grammar, id: ..., weight: 1.0 }}"""

_SHAPE_READING = """\
- cefr_level: {level}
  title: "..."
  text: "3-6 short sentences of connected Italian prose"
  glossary:
    "above-level word": "English gloss"
  questions:
    - prompt: "comprehension question in Italian"
      answers: [{{ text: "...", canonical: true }}]
      explanation: "..."
  evidence:
    - {{ axis: grammar, id: ..., weight: 1.0 }}"""

_SHAPE_LISTENING = """\
- cefr_level: {level}
  title: "..."
  turns:
    - {{ speaker: "Name", text: "..." }}
    - {{ speaker: "Other", text: "..." }}
  questions:
    - prompt: "comprehension question in Italian"
      answers: [{{ text: "...", canonical: true }}]
      explanation: "..."
  evidence:
    - {{ axis: function, id: ..., weight: 1.0 }}"""

_SHAPE_VOCAB = """\
- cefr_level: {level}
  lemma: "spec vocab id, exactly as listed"
  front: "Italian side (with article for nouns)"
  back: "English side"
  example: "short Italian sentence using it"
  example_gloss: "its English translation"
  answers: [{{ text: "the Italian production", canonical: true }}]
  evidence:
    - {{ axis: vocab, id: same-as-lemma, weight: 1.0 }}"""

_SHAPE_SPEAKING = """\
- cefr_level: {level}
  prompt: "instruction in Italian (what to say / do)"
  target_text: "the utterance a good answer sounds like"
  variants: ["acceptable alternative utterance"]
  explanation: "one sentence on the key form"
  evidence:
    - {{ axis: grammar, id: ..., weight: 1.0 }}
    - {{ axis: function, id: ..., weight: 1.0 }}"""

_SHAPE_WRITING = """\
- cefr_level: {level}
  prompt: "writing task (Italian, with an English hint in parentheses)"
  min_words: 20
  required_grammar: [grammar ids the submission should attempt]
  required_vocab: [spec vocab ids it should use]
  model_answer: "a model submission meeting the rubric"
  evidence:
    - {{ axis: grammar, id: ..., weight: 1.0 }}"""

_SHAPE_GRAMMAR_REF = """\
- cefr_level: {level}
  grammar_id: "the grammar point id"
  title: "learner-facing page title (English)"
  body_md: |
    Markdown body: explain the form in plain English, with a table of
    forms where helpful, Italian always inline like «così».
  examples: ["Italian example 1", "Italian example 2"]
  evidence:
    - {{ axis: grammar, id: same-as-grammar_id, weight: 0.5 }}"""

KINDS: dict[str, Kind] = {
    k.name: k
    for k in [
        Kind(
            "drill",
            DrillItem,
            "drills",
            "drill",
            _SHAPE_DRILL,
            "Mix types: mostly cloze, a couple of multiple_choice, at most "
            "one transform. Every plausible wrong answer gets distractor "
            "feedback naming the specific confusion, in English, with "
            "Italian forms in «guillemets».",
        ),
        Kind(
            "reading",
            ReadingItem,
            "readings",
            "reading",
            _SHAPE_READING,
            "Connected prose a learner at this level can mostly read; gloss "
            "every above-level word in the glossary map. 2-3 questions each, "
            "answerable from the text alone.",
        ),
        Kind(
            "listening",
            ListeningItem,
            "listenings",
            "listening",
            _SHAPE_LISTENING,
            "A natural short dialogue (4-8 turns, two speakers with names). "
            "Spoken register. 2-3 questions each, answerable from the "
            "dialogue alone. Audio is rendered later — do not mention it.",
        ),
        Kind(
            "vocab",
            VocabCardItem,
            "vocab",
            "vocab",
            _SHAPE_VOCAB,
            "One card per lemma, lemma must be copied exactly from the "
            "allowed vocabulary list. Nouns get their article on the front.",
        ),
        Kind(
            "speaking",
            SpeakingPromptItem,
            "speaking_prompts",
            "speaking",
            _SHAPE_SPEAKING,
            "Closed tasks: the instruction must pin down what a good answer "
            "says, because the learner's transcript is aligned against "
            "target_text word by word. Keep targets one sentence.",
        ),
        Kind(
            "writing",
            WritingPromptItem,
            "writing_prompts",
            "writing",
            _SHAPE_WRITING,
            "Tasks a learner can do in 3-6 sentences. required_grammar / "
            "required_vocab become the deterministic rubric the app checks "
            "offline, so keep them modest and central to the task.",
        ),
        Kind(
            "grammar_ref",
            GrammarRefItem,
            "grammar_refs",
            "grammar_ref",
            _SHAPE_GRAMMAR_REF,
            "One reference page per grammar point, written for the learner "
            "(not the linguist): lead with what it's for, then the forms.",
        ),
    ]
}

PROMPT_TEMPLATE = """\
You are drafting Italian learning content for a CEFR-graded course.

{context}

Task: draft {count} {kind} item(s) for this scope.
{guidance}

Rules:
- Vocabulary at or below {level}. The allowed vocabulary list (spec
  lemmas through {level}) is:
  {vocab_list}
  Gloss anything outside it inline as "parola (gloss)" or in the
  glossary field where the shape has one.
- Tag evidence ONLY with ids that appear in the scope context above
  (or the grammar point / lemma the item is for).
- Do NOT reuse these existing prompts:
{existing}

Output ONLY a YAML list, each entry exactly this shape (id will be
assigned later; omit it):

{shape}
"""


def build_prompt(
    spec: Spec, scope: Scope, kind: Kind, count: int, existing: list[str]
) -> str:
    levels = _levels_upto(scope.level)
    vocab = [v.id for v in spec.vocab if v.cefr_level in levels]
    return PROMPT_TEMPLATE.format(
        context="\n".join(scope.context_lines),
        count=count,
        kind=kind.name,
        guidance=kind.guidance,
        level=scope.level,
        vocab_list=", ".join(vocab) or "(none listed yet)",
        existing="\n".join(f"- {p}" for p in existing[:40]) or "- (none)",
        shape=kind.shape.format(level=scope.level),
    )


def _existing_prompts(items: list, scope: Scope) -> list[str]:
    """Prompt-ish strings of existing items overlapping the scope."""
    out = []
    ids = set(scope.grammar_ids) | set(scope.function_ids)
    for it in items:
        if not any(e.id in ids for e in it.evidence):
            continue
        out.append(
            getattr(it, "prompt", None)
            or getattr(it, "title", None)
            or getattr(it, "front", "")
        )
    return [p for p in out if p]


def _allocate_id(
    kind: Kind, scope: Scope, entry: dict, existing_ids: set[str], seq: int
) -> str:
    if kind.name == "vocab":
        return f"vocab.{slugify(entry.get('lemma', ''))}"
    if kind.name == "grammar_ref":
        return f"grammar_ref.{entry.get('grammar_id', scope.slug)}"
    return f"{kind.id_prefix}.{scope.slug}.{seq:03d}"


def parse_response(
    text: str, spec: Spec, kind: Kind, scope: Scope, existing_ids: set[str]
) -> list:
    """Parse a model response into draft items with fresh ids."""
    # Tolerate a fenced code block around the YAML.
    m = re.search(r"```(?:yaml)?\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    raw = yaml.safe_load(text)
    if not isinstance(raw, list):
        raise ValueError("response is not a YAML list")

    used = {
        int(g.group(1))
        for i in existing_ids
        if (g := re.fullmatch(rf"{kind.id_prefix}\.{re.escape(scope.slug)}\.(\d+)", i))
    }
    seq = max(used, default=0) + 1

    items = []
    for entry in raw:
        entry.pop("id", None)
        item_id = _allocate_id(kind, scope, entry, existing_ids, seq)
        if item_id in existing_ids:
            raise ValueError(f"{item_id}: already exists (duplicate draft?)")
        item = kind.model(id=item_id, status="draft", **entry)
        existing_ids.add(item_id)
        seq += 1
        items.append(item)
    errors = validate_pack(items, spec)
    if errors:
        raise ValueError("; ".join(errors))
    return items


def call_api(prompt: str, model: str = DEFAULT_MODEL) -> str:
    import anthropic  # lazy: only API mode needs it

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in message.content if b.type == "text")


def generate_items(
    pack_dir: Path,
    spec: Spec,
    kind_name: str,
    scope: Scope,
    count: int,
    from_file: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> Path:
    kind = KINDS[kind_name]
    sources = load_pack_sources(pack_dir)
    all_items = sources.all_items()
    existing_ids = {i.id for i in all_items}

    if from_file is not None:
        response = from_file.read_text()
    else:
        prompt = build_prompt(
            spec, scope, kind, count, _existing_prompts(all_items, scope)
        )
        response = call_api(prompt, model)

    items = parse_response(response, spec, kind, scope, existing_ids)

    out_dir = pack_dir / kind.subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{scope.slug}.draft.yaml"
    existing_drafts = yaml.safe_load(out.read_text()) or [] if out.exists() else []
    dumped = existing_drafts + [
        {
            k: v
            for k, v in yaml.safe_load(i.model_dump_json()).items()
            if v not in (None, [], {})
        }
        for i in items
    ]
    out.write_text(
        yaml.dump(dumped, allow_unicode=True, sort_keys=False, width=88),
        encoding="utf-8",
    )
    print(f"drafted {len(items)} {kind.name} item(s) -> {out}")
    return out


def generate_drills(
    pack_dir: Path,
    spec: Spec,
    gp_id: str,
    count: int,
    from_file: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> Path:
    """Back-compat wrapper: drill batch for one grammar point."""
    scope = resolve_scope(spec, gp=gp_id)
    return generate_items(pack_dir, spec, "drill", scope, count, from_file, model)
