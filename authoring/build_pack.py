"""Compile pack sources (``packs/<lang>/``) into a runtime SQLite bundle.

The bundle schema is the contract documented in ``core/src/pack.rs``; the
Rust core is its consumer. Acceptable answers are stored as authored —
the core normalizes both sides at scoring time.

Validation before build:
- item schema (see ``pack_schemas``), unique item ids
- every evidence ref resolves against the curriculum spec
  (axis ``grammar``/``function``; ``vocab`` is unchecked until the
  leveled vocab list lands)

Usage: ``python -m authoring.build_pack packs/it build/it.pack.sqlite``
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import yaml

from authoring.pack_schemas import (
    DrillItem,
    ListeningItem,
    PackManifest,
    ReadingItem,
)
from authoring.spec_schemas import Spec
from authoring.validate_spec import load_spec

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
CREATE TABLE spec_grammar (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    prerequisites TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE spec_functions (id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL);
CREATE TABLE spec_scenarios (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
    phase INTEGER NOT NULL, sequence INTEGER,
    depth_count INTEGER NOT NULL,
    grammar_ids TEXT NOT NULL DEFAULT '[]',
    function_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE spec_can_dos (
    id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL, skill TEXT NOT NULL,
    grammar_ids TEXT NOT NULL DEFAULT '[]',
    function_ids TEXT NOT NULL DEFAULT '[]'
);
"""


def _normalize(s: str) -> str:
    """Mirror of core/src/normalize.rs, applied to distractor keys at
    build time (the core looks distractors up by normalized response)."""
    s = s.replace("’", "'").replace("ʼ", "'")
    s = "".join(c for c in s if c not in '.,;:!?"«»')
    return " ".join(s.lower().split())


def load_pack_sources(
    pack_dir: Path,
) -> tuple[PackManifest, list[DrillItem], list[ReadingItem], list[ListeningItem]]:
    manifest = PackManifest(**yaml.safe_load((pack_dir / "pack.yaml").read_text()))

    def load(subdir: str, model):
        out = []
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            out.extend(model(**e) for e in yaml.safe_load(f.read_text()) or [])
        return out

    return (
        manifest,
        load("drills", DrillItem),
        load("readings", ReadingItem),
        load("listenings", ListeningItem),
    )


def validate_pack(items: list, spec: Spec) -> list[str]:
    """Cross-item and cross-spec checks over any mix of item models."""
    errors: list[str] = []
    seen: set[str] = set()
    gp_ids = {g.id for g in spec.grammar_points}
    cf_ids = {c.id for c in spec.communicative_functions}
    vocab_ids = {v.id for v in spec.vocab}
    cando_ids = {c.id for c in spec.can_dos}
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
    return errors


def _embed_spec(conn: sqlite3.Connection, spec) -> None:
    """Embed the curriculum spec so the core's composer works offline.

    The bundle is self-contained: the app never needs spec/ itself.
    """
    conn.executemany(
        "INSERT INTO spec_grammar VALUES (?, ?, ?)",
        [
            (g.id, g.cefr_level, json.dumps(g.prerequisites))
            for g in spec.grammar_points
        ],
    )
    conn.executemany(
        "INSERT INTO spec_functions VALUES (?, ?)",
        [(f.id, f.cefr_level) for f in spec.communicative_functions],
    )
    conn.executemany(
        "INSERT INTO spec_scenarios VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                s.id,
                s.cefr_level,
                s.phase,
                s.sequence,
                len(s.depths),
                json.dumps(s.grammar_ids),
                json.dumps(s.function_ids),
            )
            for s in spec.scenarios
        ],
    )
    conn.executemany(
        "INSERT INTO spec_can_dos VALUES (?, ?, ?, ?, ?)",
        [
            (
                c.id,
                c.cefr_level,
                c.skill,
                json.dumps(c.grammar_ids),
                json.dumps(c.function_ids),
            )
            for c in spec.can_dos
        ],
    )


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
) -> None:
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


def build(pack_dir: Path, spec_dir: Path, out_path: Path) -> int:
    manifest, drills, readings, listenings = load_pack_sources(pack_dir)
    spec = load_spec(spec_dir)
    all_items = [*drills, *readings, *listenings]
    errors = validate_pack(all_items, spec)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1
    skipped = [i.id for i in all_items if i.status != "reviewed"]
    drills = [i for i in drills if i.status == "reviewed"]
    readings = [i for i in readings if i.status == "reviewed"]
    listenings = [i for i in listenings if i.status == "reviewed"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)
    conn = sqlite3.connect(out_path)
    conn.executescript(_SCHEMA)
    _embed_spec(conn, spec)
    conn.executemany(
        "INSERT INTO manifest VALUES (?, ?)",
        [
            ("schema_version", manifest.schema_version),
            ("pack_version", manifest.pack_version),
            ("language", manifest.language),
        ],
    )

    built = 0
    for item in drills:
        payload: dict = {
            "prompt": item.prompt,
            "evidence": [e.model_dump() for e in item.evidence],
        }
        if item.choices:
            payload["choices"] = item.choices
        _insert_item(
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

    # Passages/dialogues become a parent item (the composer's receptive
    # slot) plus one scorable child item per question, so the core's
    # one-item-one-answer scoring model holds.
    for item in readings + listenings:
        kind = item.id.split(".", 1)[0]  # reading | listening
        modality = "reading" if kind == "reading" else "listening"
        evidence = [e.model_dump() for e in item.evidence]
        question_ids = [f"{item.id}.q{n + 1}" for n in range(len(item.questions))]
        payload = {
            "title": item.title,
            "evidence": evidence,
            "question_ids": question_ids,
        }
        if kind == "reading":
            payload["text"] = item.text
            payload["glossary"] = item.glossary
        else:
            payload["turns"] = [t.model_dump() for t in item.turns]
            payload["audio"] = item.audio
        _insert_item(conn, item.id, kind, item.cefr_level, modality, payload)
        built += 1
        for qid, q in zip(question_ids, item.questions):
            q_evidence = [{**e, "weight": e.get("weight", 1.0) * 0.5} for e in evidence]
            _insert_item(
                conn,
                qid,
                f"{kind}_question",
                item.cefr_level,
                modality,
                {"prompt": q.prompt, "parent_id": item.id, "evidence": q_evidence},
                q.answers,
                None,
                q.explanation,
            )
            built += 1

    conn.commit()
    conn.close()
    note = f", {len(skipped)} unreviewed skipped" if skipped else ""
    print(f"built {out_path}: {built} items, pack {manifest.pack_version}{note}")
    return 0


def main() -> int:
    pack_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "packs/it")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "build/it.pack.sqlite")
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    return build(pack_dir, Path("spec") / lang, out)


if __name__ == "__main__":
    raise SystemExit(main())
