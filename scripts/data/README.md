# Grammar Data Pipeline

All offline scripts that build and maintain `data/it/grammar_points.yaml` —
the single source of truth for grammar point data. Changes propagate to MongoDB via ingest.

Run all scripts from the repo root with `uv run python scripts/data/<script>.py`.

---

## Pipeline (run in order)

### 1. Split omnibus GPs  *(one-time — already done)*
```
uv run python scripts/data/split_gp.py
```
Splits umbrella entries for verbi and preposizioni into individual GPs using
delimiter rules. Grew the taxonomy from 246 → 344 entries.

### 2. Generate Italian labels
```
uv run python scripts/data/generate_labels.py
```
LLM-generated Italian noun-phrase labels (5–12 words) for every GP.
These are the primary display name used in LLM prompts.
Idempotent — skips GPs that already have a `label`. Use `--force` or `--code` to redo.

### 3. Generate short codes
```
uv run python scripts/data/generate_short_codes.py
```
LLM-generates a ≤10-char snake_case English code (e.g. `pres_ind`, `def_art`)
for every GP. The old verbose code is preserved as `unistr_code`.
After running, re-run ingest and migration `0003_short_codes` remaps all collections.

### 4. Map GPs to grammar book chunks
```
uv run python scripts/data/llm_remap_chunks.py
```
LLM maps each GP to the best chapter in the grammar book using
`chunk_enrichment.json` (40–80-word descriptions of all 124 chunks) as context.
Outputs `null` for A0 formulaic items with no corresponding chapter.
Writes `chunk_ref` directly into `grammar_points.yaml`.

### 5. Export existing DB explanations to JSON  *(one-time — run before clearing DB)*
```
uv run python scripts/data/export_explanations_to_json.py
```
Reads the old `grammar_point_explanations` MongoDB collection and writes
explanations into `grammar_points.yaml`. Only needed when migrating from the
separate-collection model to the inline model.

### 6. Ingest YAML → MongoDB
```
uv run python -m maestro.sync.ingest
```
Upserts all GPs (labels, codes, chunk_refs, explanations) into MongoDB.
Also ingests vocab, communicative functions, and curriculum scenarios.

### 7. (Automatic) Migration on app startup
Migration `0003_short_codes` runs automatically on the next `uvicorn` start and
remaps `grammar_point_code` references across `generated_drills`, `lessons`,
`learning_events`, `learning_profile`, and `curriculum_scenarios`.

### 8. Generate grammar reference explanations
```
uv run python scripts/data/generate_explanations.py
```
For each GP (A1–B2), generates one complete reference entry at the GP's own CEFR level,
using the GP's linked grammar chunk as the authoritative source.
Writes to both MongoDB and `grammar_points.yaml`. A0 GPs are intentionally skipped.
Use `--clear` to wipe and regenerate from scratch. Use `--level` or `--code` to target.

---

## Reference

### Data files

| File | Description |
|------|-------------|
| `data/it/grammar_points.yaml` | Master GP list — 344 entries |
| `data/it/chunk_enrichment.json` | 124 grammar book chunk descriptions |
| `data/it/grammar_point_chunks.yaml` | Legacy YAML chunk mapping (superseded) |

### GP YAML fields

| Field | Description |
|-------|-------------|
| `code` | Short ≤10-char snake_case English identifier (`pres_ind`) |
| `unistr_code` | Original verbose code preserved for migration lookup |
| `label` | Italian noun-phrase display name (`Indicativo presente dei verbi regolari`) |
| `unistr_label` | Original verbose label |
| `cefr_level` | A0–B2 |
| `category` | Grammar category (verbi, preposizioni, …) |
| `description` | One-sentence description of the grammar concept |
| `chunk_ref` | Grammar book chapter ref, or `null` for A0 formulaic items |
| `explanations` | Dict keyed by CEFR level: `{"A1": {"title": …, "explanation": …}}` |
