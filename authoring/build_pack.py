"""Compile pack sources (``packs/<lang>/``) into a runtime SQLite bundle.

The bundle schema is the contract documented in ``core/src/pack.rs``; the
Rust core is its consumer. Acceptable answers are stored as authored —
the core normalizes both sides at scoring time.

Validation before build:
- item schema (see ``pack_schemas``), unique item ids
- every evidence ref resolves against the curriculum spec
- referenced media files exist under the pack directory
- tombstoned ids are actually absent from the sources

Usage: ``python -m authoring.build_pack packs/it build/it.pack.sqlite``
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from authoring.pack_schemas import (
    Answer,
    DrillItem,
    GrammarRefItem,
    ListeningItem,
    PackManifest,
    ReadingItem,
    SpeakingPromptItem,
    Tombstone,
    VocabCardItem,
    TaskItem,
    WritingPromptItem,
)
from authoring.spec_schemas import Spec
from authoring.validate_spec import load_spec
from authoring import vocab_link

_SCHEMA = """
CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE items (
    id TEXT PRIMARY KEY, item_type TEXT NOT NULL,
    cefr_level TEXT NOT NULL, modality TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE acceptable_answers (
    item_id TEXT NOT NULL REFERENCES items(id),
    answer TEXT NOT NULL,
    is_canonical INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE distractor_feedback (
    item_id TEXT NOT NULL REFERENCES items(id),
    response_norm TEXT NOT NULL,
    feedback TEXT NOT NULL
);
CREATE TABLE explanations (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    feedback TEXT NOT NULL
);
CREATE TABLE media (
    path TEXT PRIMARY KEY,          -- as referenced by item payloads
    kind TEXT NOT NULL,             -- audio | image
    sha256 TEXT NOT NULL,
    bytes BLOB NOT NULL
);
CREATE TABLE tombstones (
    item_id TEXT PRIMARY KEY,
    removed_in TEXT NOT NULL,
    reason TEXT
);
CREATE TABLE spec_grammar (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE spec_functions (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE spec_scenarios (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    phase INTEGER NOT NULL, sequence INTEGER,
    depth_count INTEGER NOT NULL,
    grammar_ids TEXT NOT NULL DEFAULT '[]',
    function_ids TEXT NOT NULL DEFAULT '[]',
    -- Authored framing: what the lesson is about and why it's worth
    -- doing. Shown before the lesson starts and again in its recap.
    label TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    overview TEXT NOT NULL DEFAULT '',
    scene_setting TEXT NOT NULL DEFAULT '',
    outro TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT ''
);
CREATE TABLE spec_can_dos (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL, skill TEXT NOT NULL,
    grammar_ids TEXT NOT NULL DEFAULT '[]',
    function_ids TEXT NOT NULL DEFAULT '[]',
    label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE spec_vocab (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    pos TEXT NOT NULL, gloss TEXT NOT NULL
);
"""

_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# Directory -> (model, kind key used in coverage reports).
_ITEM_DIRS = {
    "drills": DrillItem,
    "readings": ReadingItem,
    "listenings": ListeningItem,
    "vocab": VocabCardItem,
    "speaking_prompts": SpeakingPromptItem,
    "writing_prompts": WritingPromptItem,
    "grammar_refs": GrammarRefItem,
    "tasks": TaskItem,
}


def _normalize(s: str) -> str:
    """Mirror of core/src/normalize.rs, applied to distractor keys at
    build time (the core looks distractors up by normalized response).
    Pinned by conformance/normalize_vectors.json on both sides."""
    s = s.replace("’", "'").replace("ʼ", "'")
    s = "".join(c for c in s if c not in '.,;:!?"«»')
    return " ".join(s.lower().split())


@dataclass
class PackSources:
    """Everything under ``packs/<lang>/``, parsed and typed."""

    manifest: PackManifest
    drills: list[DrillItem] = field(default_factory=list)
    readings: list[ReadingItem] = field(default_factory=list)
    listenings: list[ListeningItem] = field(default_factory=list)
    vocab_cards: list[VocabCardItem] = field(default_factory=list)
    speaking_prompts: list[SpeakingPromptItem] = field(default_factory=list)
    writing_prompts: list[WritingPromptItem] = field(default_factory=list)
    grammar_refs: list[GrammarRefItem] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    tombstones: list[Tombstone] = field(default_factory=list)

    def all_items(self) -> list:
        return [
            *self.drills,
            *self.readings,
            *self.listenings,
            *self.vocab_cards,
            *self.speaking_prompts,
            *self.writing_prompts,
            *self.grammar_refs,
            *self.tasks,
        ]


def load_pack_sources(pack_dir: Path) -> PackSources:
    manifest = PackManifest(**yaml.safe_load((pack_dir / "pack.yaml").read_text()))

    def load(subdir: str, model):
        out = []
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            out.extend(model(**e) for e in yaml.safe_load(f.read_text()) or [])
        return out

    tombstones = []
    ts_file = pack_dir / "tombstones.yaml"
    if ts_file.exists():
        tombstones = [Tombstone(**e) for e in yaml.safe_load(ts_file.read_text()) or []]

    return PackSources(
        manifest=manifest,
        drills=load("drills", DrillItem),
        readings=load("readings", ReadingItem),
        listenings=load("listenings", ListeningItem),
        vocab_cards=load("vocab", VocabCardItem),
        speaking_prompts=load("speaking_prompts", SpeakingPromptItem),
        writing_prompts=load("writing_prompts", WritingPromptItem),
        grammar_refs=load("grammar_refs", GrammarRefItem),
        tasks=load("tasks", TaskItem),
        tombstones=tombstones,
    )


def _media_refs(item) -> list[str]:
    """All media paths an item references (audio and image fields)."""
    refs = [getattr(item, "audio", None), getattr(item, "image", None)]
    for turn in getattr(item, "turns", []) or []:
        refs.append(turn.audio)
    return [r for r in refs if r]


def validate_pack(items: list, spec: Spec) -> list[str]:
    """Cross-item and cross-spec checks over any mix of item models."""
    errors: list[str] = []
    seen: set[str] = set()
    gp_ids = {g.id for g in spec.grammar_points}
    cf_ids = {c.id for c in spec.communicative_functions}
    vocab_ids = {v.id for v in spec.vocab}
    cando_ids = {c.id for c in spec.can_dos}
    scenario_ids = {s.id for s in spec.scenarios}
    for item in items:
        if item.id in seen:
            errors.append(f"duplicate item id: {item.id}")
        seen.add(item.id)
        for ev in item.evidence:
            known = {
                "grammar": gp_ids,
                "function": cf_ids,
                "vocab": vocab_ids,
                "cando": cando_ids,
            }.get(ev.axis)
            if known is not None and ev.id not in known:
                errors.append(f"{item.id}: unknown {ev.axis} id {ev.id}")
        if isinstance(item, VocabCardItem) and item.lemma not in vocab_ids:
            errors.append(f"{item.id}: unknown lemma {item.lemma}")
        if isinstance(item, GrammarRefItem) and item.grammar_id not in gp_ids:
            errors.append(f"{item.id}: unknown grammar id {item.grammar_id}")
        for gp in getattr(item, "required_grammar", []):
            if gp not in gp_ids:
                errors.append(f"{item.id}: unknown required_grammar {gp}")
        for lemma in getattr(item, "required_vocab", []):
            if lemma not in vocab_ids:
                errors.append(f"{item.id}: unknown required_vocab {lemma}")
        for sc in item.scenario_ids:
            if sc not in scenario_ids:
                errors.append(f"{item.id}: unknown scenario id {sc}")
    return errors


def validate_media(items: list, pack_dir: Path) -> list[str]:
    """Every referenced media file must exist and have a known kind."""
    errors = []
    for item in items:
        for ref in _media_refs(item):
            p = pack_dir / ref
            if not p.is_file():
                errors.append(f"{item.id}: missing media file {ref}")
            elif p.suffix.lower() not in _AUDIO_EXT | _IMAGE_EXT:
                errors.append(f"{item.id}: unsupported media type {ref}")
    return errors


def validate_tombstones(sources: PackSources) -> list[str]:
    live = {i.id for i in sources.all_items()}
    return [
        f"tombstoned id still present in sources: {t.item_id}"
        for t in sources.tombstones
        if t.item_id in live
    ]


def coverage_report(
    items: list, spec: Spec, statuses: frozenset[str] = frozenset({"reviewed"})
) -> dict:
    """Item counts per grammar point and per (level, kind).

    The authoring backlog view: thin cells are what `generate` should be
    pointed at next. Written beside the bundle at build time and reused
    by the review tool's coverage matrix.

    Counts `reviewed` items by default — the backlog question is "what is
    ready to ship". `build` passes the status set it actually compiled, so
    the report beside a `--include-draft` dev bundle describes that bundle
    rather than a stricter one.
    """
    kinds = {
        DrillItem: "drill",
        ReadingItem: "reading",
        ListeningItem: "listening",
        VocabCardItem: "vocab_card",
        SpeakingPromptItem: "speaking_prompt",
        WritingPromptItem: "writing_prompt",
        GrammarRefItem: "grammar_ref",
        TaskItem: "task",
    }
    by_gp: dict[str, dict] = {
        g.id: {"cefr_level": g.cefr_level, "counts": {}} for g in spec.grammar_points
    }
    by_level_kind: dict[str, dict[str, int]] = {}
    for item in items:
        if item.status not in statuses:
            continue
        kind = kinds[type(item)]
        lk = by_level_kind.setdefault(item.cefr_level, {})
        lk[kind] = lk.get(kind, 0) + 1
        for ev in item.evidence:
            if ev.axis == "grammar" and ev.id in by_gp:
                counts = by_gp[ev.id]["counts"]
                counts[kind] = counts.get(kind, 0) + 1
    covered = {g for g, d in by_gp.items() if d["counts"]}
    return {
        "grammar_points": by_gp,
        "levels": by_level_kind,
        "totals": {
            "grammar_points": len(by_gp),
            "grammar_points_covered": len(covered),
        },
    }


def _unwrap(text: str | None) -> str:
    """Join hard-wrapped prose back into paragraphs.

    The scenario copy is written as wrapped YAML block scalars, so a
    sentence arrives split across several lines. Rendered as-is that breaks
    mid-sentence on every device. Blank lines survive as paragraph breaks;
    single newlines were only ever the author's text editor.
    """
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "\n\n".join(" ".join(p.split()) for p in paragraphs)


def _embed_spec(conn: sqlite3.Connection, spec) -> None:
    """Embed the curriculum spec so the core's composer works offline.

    The bundle is self-contained: the app never needs spec/ itself.
    """
    conn.executemany(
        "INSERT INTO spec_grammar VALUES (?, ?, ?, ?)",
        [
            (g.id, g.cefr_level, json.dumps(g.prerequisites), g.label)
            for g in spec.grammar_points
        ],
    )
    conn.executemany(
        "INSERT INTO spec_functions VALUES (?, ?, ?)",
        [(f.id, f.cefr_level, f.label) for f in spec.communicative_functions],
    )
    conn.executemany(
        "INSERT INTO spec_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                s.id,
                s.cefr_level,
                s.phase,
                s.sequence,
                len(s.depths),
                json.dumps(s.grammar_ids),
                json.dumps(s.function_ids),
                s.label,
                _unwrap(s.description),
                _unwrap(s.overview),
                _unwrap(s.scene_setting),
                _unwrap(s.outro),
                s.image or "",
            )
            for s in spec.scenarios
        ],
    )
    conn.executemany(
        "INSERT INTO spec_can_dos VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                c.id,
                c.cefr_level,
                c.skill,
                json.dumps(c.grammar_ids),
                json.dumps(c.function_ids),
                c.label,
            )
            for c in spec.can_dos
        ],
    )
    conn.executemany(
        "INSERT INTO spec_vocab VALUES (?, ?, ?, ?)",
        [(v.id, v.cefr_level, v.pos, v.gloss) for v in spec.vocab],
    )


def _embed_media(
    conn: sqlite3.Connection, items: list, pack_dir: Path, spec: Spec | None = None
) -> int:
    embedded: set[str] = set()

    def embed(ref: str) -> None:
        if ref in embedded:
            return
        data = (pack_dir / ref).read_bytes()
        kind = "audio" if Path(ref).suffix.lower() in _AUDIO_EXT else "image"
        conn.execute(
            "INSERT INTO media VALUES (?, ?, ?, ?)",
            (ref, kind, hashlib.sha256(data).hexdigest(), data),
        )
        embedded.add(ref)

    for item in items:
        for ref in _media_refs(item):
            embed(ref)
    # Scenario art lives at a conventional path (no spec field): the app
    # asks the media table for images/scenarios/<id>.png and renders it
    # if present.
    if spec is not None:
        for s in spec.scenarios:
            for ext in sorted(_IMAGE_EXT):
                p = pack_dir / "images" / "scenarios" / f"{s.id}{ext}"
                if p.is_file():
                    embed(f"images/scenarios/{s.id}{ext}")
                    break
    return len(embedded)


def _italian_text(payload: dict, answers) -> str:
    """The parts of an item that are unambiguously Italian.

    Instruction prose is deliberately left out. It is written in English,
    and a dozen spec lemmas ("come", "no", "male", "sale", "due") are also
    English words — scanning it would hand the learner vocabulary they
    never met. The Italian inside a prompt is always quoted, so that is the
    only part of a mixed string that comes through.
    """
    parts: list[str] = [a.text for a in answers]
    for key in ("target_text", "model_answer", "text", "front", "example"):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    parts += payload.get("variants") or []
    parts += payload.get("examples") or []
    parts += [t.get("text", "") for t in payload.get("turns") or []]
    for key in ("prompt", "body_md"):
        value = payload.get(key)
        if isinstance(value, str):
            parts += vocab_link.quoted_spans(value)
    return "\n".join(p for p in parts if p)


# Vocab-axis weight for a word the item merely contains, well below the
# 1.0 an authored flashcard carries: meeting a word is evidence that it
# belongs in the learner's vocabulary, not that they know it.
ENCOUNTER_WEIGHT = 0.1


def _link_vocab(payload: dict, answers, index: dict[str, str]) -> int:
    """Add vocab-axis evidence for the spec words this item contains.

    Returns how many were added. Words the author already tagged keep
    their own weight — an explicit annotation always outranks a match.
    """
    evidence = payload.setdefault("evidence", [])
    tagged = {e["id"] for e in evidence if e.get("axis") == "vocab"}
    added = 0
    for lemma in vocab_link.find_lemmas(_italian_text(payload, answers), index):
        if lemma not in tagged:
            evidence.append({"axis": "vocab", "id": lemma, "weight": ENCOUNTER_WEIGHT})
            added += 1
    return added


def _insert_item(
    conn,
    item_id,
    item_type,
    level,
    modality,
    payload,
    answers=(),
    distractors=None,
    explanation=None,
    vocab_index=None,
) -> int:
    added = _link_vocab(payload, answers, vocab_index) if vocab_index else 0
    conn.execute(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?)",
        (item_id, item_type, level, modality, json.dumps(payload, ensure_ascii=False)),
    )
    conn.executemany(
        "INSERT INTO acceptable_answers VALUES (?, ?, ?)",
        [(item_id, a.text, int(a.canonical)) for a in answers],
    )
    for resp, fb in (distractors or {}).items():
        conn.execute(
            "INSERT INTO distractor_feedback VALUES (?, ?, ?)",
            (item_id, _normalize(resp), fb),
        )
    if explanation:
        conn.execute("INSERT INTO explanations VALUES (?, ?)", (item_id, explanation))
    return added


def build(
    pack_dir: Path, spec_dir: Path, out_path: Path, *, include_draft: bool = False
) -> int:
    sources = load_pack_sources(pack_dir)
    spec = load_spec(spec_dir)
    all_items = sources.all_items()
    errors = (
        validate_pack(all_items, spec)
        + validate_media(all_items, pack_dir)
        + validate_tombstones(sources)
    )
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1
    # Only `reviewed` content ships. `--include-draft` relaxes that for local
    # dev packs so freshly drafted content can be exercised on device before
    # review; `release` never passes it, so a release bundle stays clean.
    shippable = {"reviewed", "draft"} if include_draft else {"reviewed"}
    skipped = [i.id for i in all_items if i.status not in shippable]
    drafted = [i.id for i in all_items if i.status == "draft"] if include_draft else []
    reviewed = [i for i in all_items if i.status in shippable]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)
    conn = sqlite3.connect(out_path)
    conn.executescript(_SCHEMA)
    _embed_spec(conn, spec)
    manifest = sources.manifest
    conn.executemany(
        "INSERT INTO manifest VALUES (?, ?)",
        [
            ("schema_version", manifest.schema_version),
            ("pack_version", manifest.pack_version),
            ("language", manifest.language),
        ],
    )
    conn.executemany(
        "INSERT INTO tombstones VALUES (?, ?, ?)",
        [(t.item_id, t.removed_in, t.reason) for t in sources.tombstones],
    )
    media_count = _embed_media(conn, reviewed, pack_dir, spec)

    # Every item is linked to the leveled vocabulary as it is written, so
    # the app can add a word to the learner's vocabulary the moment a
    # lesson puts it in front of them.
    vocab_index, ambiguous = vocab_link.build_index(spec.vocab)
    linked_words = 0
    linked_items = 0

    def insert(*args, **kwargs) -> None:
        nonlocal linked_words, linked_items
        added = _insert_item(*args, vocab_index=vocab_index, **kwargs)
        linked_words += added
        linked_items += 1 if added else 0

    built = 0
    for item in reviewed:
        if isinstance(item, DrillItem):
            payload: dict = {
                "prompt": item.prompt,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
            }
            if item.choices:
                payload["choices"] = item.choices
            insert(
                conn,
                item.id,
                item.item_type,
                item.cefr_level,
                item.modality,
                payload,
                item.answers,
                item.distractor_feedback,
                item.explanation,
            )
            built += 1
        elif isinstance(item, VocabCardItem):
            payload = {
                "lemma": item.lemma,
                "front": item.front,
                "back": item.back,
                "example": item.example,
                "example_gloss": item.example_gloss,
                "audio": item.audio,
                "image": item.image,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
            }
            insert(
                conn,
                item.id,
                item.item_type,
                item.cefr_level,
                "vocab",
                payload,
                item.answers,
            )
            built += 1
        elif isinstance(item, SpeakingPromptItem):
            payload = {
                "prompt": item.prompt,
                "target_text": item.target_text,
                "variants": item.variants,
                "audio": item.audio,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
            }
            answers = [Answer(text=item.target_text, canonical=True)] + [
                Answer(text=v) for v in item.variants
            ]
            insert(
                conn,
                item.id,
                item.item_type,
                item.cefr_level,
                "speaking",
                payload,
                answers,
                None,
                item.explanation,
            )
            built += 1
        elif isinstance(item, WritingPromptItem):
            payload = {
                "prompt": item.prompt,
                "min_words": item.min_words,
                "required_grammar": item.required_grammar,
                "required_vocab": item.required_vocab,
                "model_answer": item.model_answer,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
            }
            insert(conn, item.id, item.item_type, item.cefr_level, "writing", payload)
            built += 1
        elif isinstance(item, GrammarRefItem):
            payload = {
                "grammar_id": item.grammar_id,
                "title": item.title,
                "body_md": item.body_md,
                "examples": item.examples,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                # No demand: a reference page is presentation, not an
                # attempt. It emits `introduced`, never evidence.
            }
            insert(conn, item.id, item.item_type, item.cefr_level, "reading", payload)
            built += 1
        elif isinstance(item, TaskItem):
            payload = {
                "prompt": item.prompt,
                "mode": item.mode,
                # Withheld from the payload at `perform`: the whole point
                # of the closing capstone is that there is nothing to copy.
                # Scoring still has it via acceptable_answers.
                "target_text": item.target_text if item.demand == "use" else None,
                "rubric": item.rubric,
                "min_words": item.min_words,
                "evidence": [e.model_dump() for e in item.evidence],
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
            }
            answers = (
                [Answer(text=item.target_text, canonical=True)]
                + [Answer(text=v) for v in item.variants]
                if item.target_text
                else []
            )
            insert(
                conn,
                item.id,
                item.item_type,
                item.cefr_level,
                item.mode,
                payload,
                answers,
                None,
                item.explanation,
            )
            built += 1
        elif isinstance(item, (ReadingItem, ListeningItem)):
            # Passages/dialogues become a parent item (the composer's
            # receptive slot) plus one scorable child item per question,
            # so the core's one-item-one-answer scoring model holds.
            kind = item.id.split(".", 1)[0]  # reading | listening
            modality = "reading" if kind == "reading" else "listening"
            evidence = [e.model_dump() for e in item.evidence]
            question_ids = [f"{item.id}.q{n + 1}" for n in range(len(item.questions))]
            payload = {
                "title": item.title,
                "evidence": evidence,
                "scenario_ids": item.scenario_ids,
                "demand": item.demand,
                "question_ids": question_ids,
            }
            if isinstance(item, ReadingItem):
                payload["text"] = item.text
                payload["glossary"] = item.glossary
                payload["image"] = item.image
            else:
                payload["turns"] = [t.model_dump() for t in item.turns]
                payload["audio"] = item.audio
            insert(conn, item.id, kind, item.cefr_level, modality, payload)
            built += 1
            for qid, q in zip(question_ids, item.questions):
                q_evidence = [
                    {**e, "weight": e.get("weight", 1.0) * 0.5} for e in evidence
                ]
                insert(
                    conn,
                    qid,
                    f"{kind}_question",
                    item.cefr_level,
                    modality,
                    {
                        "prompt": q.prompt,
                        "parent_id": item.id,
                        "evidence": q_evidence,
                        "scenario_ids": item.scenario_ids,
                        # The question's own rung, not the passage's: a
                        # comprehension question is recognition even when
                        # the answer box makes it look like a drill.
                        "demand": q.demand,
                    },
                    q.answers,
                    None,
                    q.explanation,
                )
                built += 1
        else:  # pragma: no cover - all models handled above
            raise TypeError(f"unhandled item model: {type(item)}")

    conn.commit()
    conn.close()

    report = coverage_report(all_items, spec, frozenset(shippable))
    coverage_path = out_path.with_suffix(".coverage.json")
    coverage_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    note = f", {len(skipped)} unreviewed skipped" if skipped else ""
    if drafted:
        note += f", {len(drafted)} DRAFT included (not for release)"
    media_note = f", {media_count} media files" if media_count else ""
    gp = report["totals"]
    print(
        f"built {out_path}: {built} items{media_note}, pack "
        f"{manifest.pack_version}{note}; grammar coverage "
        f"{gp['grammar_points_covered']}/{gp['grammar_points']} "
        f"(details: {coverage_path})"
    )
    # Ambiguous surfaces are dropped, not guessed at, so say how many
    # rather than letting the link rate look like full coverage.
    ambiguous_note = f", {len(ambiguous)} ambiguous forms skipped" if ambiguous else ""
    print(
        f"vocabulary: {linked_words} word links across {linked_items} items"
        f"{ambiguous_note}"
    )
    return 0


def main() -> int:
    pack_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "packs/it")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "build/it.pack.sqlite")
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    return build(pack_dir, Path("spec") / lang, out)


if __name__ == "__main__":
    raise SystemExit(main())
