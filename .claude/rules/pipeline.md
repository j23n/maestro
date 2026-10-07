---
paths:
  - "pipeline/**"
  - "schemas/**"
---

# Pipeline conventions

- Python 3.12, managed with `uv`; type hints everywhere; `ruff format` and `ruff check` clean; tests with pytest.
- Outputs must be deterministic: sorted keys and rows, no timestamps in content, `VACUUM INTO` for the pack. `content pack-hash` must not change between two runs on the same input.
- No network in tests. Azure responses are recorded fixtures; Morph-it! and frequency data come from `make data`.
- `schemas/content-pack.sql` is normative. Change it only with a `meta.schema_version` bump and matching Swift `PackReader` changes in the same PR.
- Only permissively licensed data (`docs/13` § Licences). Keep each data source's licence file next to it.
