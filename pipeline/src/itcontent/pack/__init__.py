"""The content pack builder: `content build` and `content pack-hash` (docs/04 § Pack build, docs/03 § The compiled
content pack, docs/06 § Payloads).

The pack is compiled from the YAML in `content/` and the annotation lock files in `content/.annotations/` (every
Italian string's tokens come from them; the build never tokenises authored text itself) into the tables of the
normative `schemas/content-pack.sql`.

- `locks`: the lock files as the builder reads them, and `TokenizedText` payloads from their tokens.
- `display`: display forms of nouns and the generated recall answers (docs/03 § Display forms, docs/05).
- `requirements`: `text_requires`, `exercise_requires` and `step_introduces` (docs/04 § Requirements, docs/05).
- `payloads`: step, exercise, note, assessment and layout JSON (`schemas/pack-payloads.schema.json`).
- `compile`: the walk over the course that produces every table's rows.
- `db`: writing the SQLite file and the canonical pack hash.
- `build`: modes (dev, `--release`, `--mini`), scope, checks and outputs; the CLI calls `run_build`.
"""
