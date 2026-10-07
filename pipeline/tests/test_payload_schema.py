"""The pack payload contract (schemas/pack-payloads.schema.json) is a valid schema, and the hand-made examples in
fixtures/packs/payload-examples.json — one per exercise format, step kind, note, assessment and layout — conform."""

from __future__ import annotations

import json

import jsonschema
import pytest


@pytest.fixture(scope="module")
def schema(root):
    s = json.loads((root / "schemas" / "pack-payloads.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(s)
    return s


@pytest.fixture(scope="module")
def examples(root):
    return json.loads((root / "fixtures" / "packs" / "payload-examples.json").read_text(encoding="utf-8"))


def validator(schema, definition):
    return jsonschema.Draft202012Validator({"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]})


@pytest.mark.parametrize(
    ("key", "definition"),
    [
        ("exercises", "exercise"),
        ("steps", "stepPayload"),
        ("notes", "noteBody"),
        ("assessments", "assessment"),
        ("layouts", "layout"),
    ],
)
def test_examples_conform(schema, examples, key, definition):
    v = validator(schema, definition)
    for example in examples[key]:
        errors = sorted(v.iter_errors(example), key=lambda e: list(e.path))
        assert not errors, f"{example.get('id') or example.get('kind')}: {errors[0].message} at {list(errors[0].path)}"


def test_every_format_and_step_kind_has_an_example(examples):
    formats = {e["format"] for e in examples["exercises"]}
    assert formats >= {
        "cloze",
        "recall",
        "sentence-building",
        "dictation",
        "repeat",
        "choice",
        "match",
        "sound-pair",
        "conversation",
        "talk",
        "writing",
        "relay",
        "true-false",
    }
    kinds = {s["kind"] for s in examples["steps"]}
    assert kinds >= {
        "opener",
        "preview",
        "story",
        "listening",
        "reading",
        "note",
        "practice",
        "sounds",
        "use",
        "conversation",
        "talk",
        "relay",
        "check",
        "fluency",
    }


def test_tokenized_texts_rebuild_their_text(examples):
    def walk(node):
        if isinstance(node, dict):
            if {"text", "lead", "tokens"} <= node.keys():
                yield node
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    found = list(walk(examples))
    assert len(found) > 20
    for t in found:
        assert t["lead"] + "".join(k["surface"] + k["trailing"] for k in t["tokens"]) == t["text"]


def test_a_payload_missing_a_required_key_is_rejected(schema, examples):
    v = validator(schema, "exercise")
    broken = dict(examples["exercises"][0])
    del broken["gap"]
    assert list(v.iter_errors(broken))
