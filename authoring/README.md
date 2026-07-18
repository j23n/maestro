# authoring — curriculum spec + content pipeline (Python)

The `maestro-pack` CLI (`python -m authoring.cli`): validate / build /
generate / review / release. See
`docs/plans/03-implementation-plan.md` §5 Phase 2 and §10.

- `spec_schemas.py` — Pydantic models for `spec/<lang>/` (Layer 1). IDs are
  forever; packs and learner events reference them.
- `validate_spec.py` — loads and validates a spec directory (unique IDs,
  refs resolve, prerequisite DAG acyclic). Run:
  `python -m authoring.validate_spec spec/it`
- `pack_schemas.py` — Pydantic models for `packs/<lang>/` item YAML
  (drills, readings, listenings) with the in-file review lifecycle
  (`status: draft|reviewed|flagged`).
- `build_pack.py` — compiles spec + reviewed items into
  `build/<lang>.pack.sqlite` (the bundle the core opens).
- `generate.py` — LLM drafting of drill candidates (API or `--from-file`).
- `review.py` — local web UI over the YAML working tree (queue, edit,
  accept/reject, coverage). Git is the database.
- `release.py` — build + sha256 + `release.json` for distribution.

Guarded by `tests/unit/test_spec.py`, `test_pack_build.py`,
`test_authoring_tools.py`.

`spec/it/` is canonical. It was originally converted from the legacy
app's `data/it/` by a one-shot converter — both the source data and the
converter were removed when the legacy app was retired (git history has
them); `spec/it/CONVERSION.md` records what the conversion did.
