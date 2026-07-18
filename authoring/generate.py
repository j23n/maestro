"""LLM drafting of drill banks for a spec cell (`maestro-pack generate`).

Two modes:

- **API mode** (default): calls the Anthropic API (lazy import; needs
  ANTHROPIC_API_KEY). One call drafts a whole batch.
- **File mode** (`--from-file`): parses a prepared response — the same
  YAML the model would return. Used by tests, and for drafting sessions
  run outside this CLI.

Drafts land in ``packs/<lang>/drills/<gp>.draft.yaml`` with
``status: draft``; they are invisible to ``build`` until the review tool
(or a human edit) promotes them to ``reviewed``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from authoring.build_pack import load_pack_sources, validate_pack
from authoring.pack_schemas import DrillItem
from authoring.spec_schemas import Spec

DEFAULT_MODEL = "claude-sonnet-5"

PROMPT_TEMPLATE = """\
You are drafting Italian drill items for a CEFR-graded language course.

Grammar point: {gp_id} ({level})
Label: {label}
Description: {description}
Reference examples:
{examples}

Draft {count} drill items exercising this grammar point. Mix types:
mostly cloze, a couple of multiple_choice, at most one transform.

Rules:
- Vocabulary at or below {level}; gloss anything above inline as
  "parola (gloss)".
- Every item: 1 canonical answer, plus non-canonical acceptable variants
  where natural (e.g. with/without subject pronoun).
- Every plausible wrong answer you can anticipate gets distractor
  feedback explaining the specific confusion, in English, naming Italian
  forms in «guillemets».
- An `explanation` field states the rule in one or two sentences.
- Do NOT reuse these existing prompts:
{existing}

Output ONLY a YAML list, each entry exactly this shape (id will be
assigned later; omit it):

- item_type: drill_cloze
  cefr_level: {level}
  prompt: "..."
  answers:
    - {{ text: "...", canonical: true }}
  distractor_feedback:
    "wrong answer": "why it's wrong"
  explanation: "..."
  evidence:
    - {{ axis: grammar, id: {gp_id}, weight: 1.0 }}
"""


def build_prompt(
    spec: Spec, gp_id: str, count: int, existing_prompts: list[str]
) -> str:
    gp = next((g for g in spec.grammar_points if g.id == gp_id), None)
    if gp is None:
        raise ValueError(f"unknown grammar point: {gp_id}")
    plain_examples = [re.sub(r"<[^>]+>", "", e) for e in gp.examples[:6]]
    return PROMPT_TEMPLATE.format(
        gp_id=gp_id,
        level=gp.cefr_level,
        label=gp.label,
        description=gp.description or gp.source.descriptor_label or "",
        examples="\n".join(f"- {e}" for e in plain_examples) or "- (none)",
        count=count,
        existing="\n".join(f"- {p}" for p in existing_prompts[:40]) or "- (none)",
    )


def parse_response(
    text: str, spec: Spec, gp_id: str, existing_ids: set[str]
) -> list[DrillItem]:
    """Parse a model response into draft items with fresh sequential ids."""
    # Tolerate a fenced code block around the YAML.
    m = re.search(r"```(?:yaml)?\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    raw = yaml.safe_load(text)
    if not isinstance(raw, list):
        raise ValueError("response is not a YAML list")

    used = {
        int(m.group(1))
        for i in existing_ids
        if (m := re.fullmatch(rf"drill\.{re.escape(gp_id)}\.(\d+)", i))
    }
    next_n = max(used, default=0) + 1

    items: list[DrillItem] = []
    for entry in raw:
        entry.pop("id", None)
        item = DrillItem(id=f"drill.{gp_id}.{next_n:03d}", status="draft", **entry)
        next_n += 1
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


def generate_drills(
    pack_dir: Path,
    spec: Spec,
    gp_id: str,
    count: int,
    from_file: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> Path:
    _manifest, drills, _r, _l = load_pack_sources(pack_dir)
    existing_ids = {d.id for d in drills}
    existing_prompts = [
        d.prompt for d in drills if any(e.id == gp_id for e in d.evidence)
    ]
    if from_file is not None:
        response = from_file.read_text()
    else:
        response = call_api(build_prompt(spec, gp_id, count, existing_prompts), model)

    items = parse_response(response, spec, gp_id, existing_ids)
    out = pack_dir / "drills" / f"{gp_id}.draft.yaml"
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
    print(f"drafted {len(items)} items -> {out}")
    return out
