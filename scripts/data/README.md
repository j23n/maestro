# Data Pipeline

All offline scripts that build and maintain grammar points and communicative
functions — the single source of truth for learning-outcome data. Changes
propagate to MongoDB via ingest.

Run all scripts from the repo root with `uv run python scripts/data/<script>.py`.

---

## Pipeline (run in order)

### 1. Source parse

**Italian:** Scrape grammar points and communicative functions from Profilo della
Lingua Italiana website.
```
uv run python scripts/data/scrape_grammar_points.py
uv run python scripts/data/scrape_comm_functions.py
```

**German:** Extract grammar points from Goethe test PDFs.
```
uv run python scripts/data/extract_goethe_pdfs.py
```

### 2. Augment grammar points
```
uv run python scripts/data/augment_gp.py --lang it --level A1
uv run python scripts/data/augment_gp.py --lang de --level A1
```
Fills missing fields via LLM: `subcategory`, `description`, `examples`,
`explanations` (en + target language). Idempotent — only generates missing
fields. Use `--force` to regenerate all augmentable fields.

Use `--list` to see completion status, `--test` for one GP per level,
`--code` for a single GP, `--explanation-lang` for a single explanation language.

### 3. Augment communicative functions
```
uv run python scripts/data/augment_cf.py --lang it --level A1
uv run python scripts/data/augment_cf.py --lang de --level A1
```
Fills missing fields via LLM: `description`, `examples`, `explanations`
(en + target language). Same CLI options as augment_gp.

### 4. Generate prerequisite DAG
```
uv run python scripts/data/generate_prerequisites.py --lang it --level A1
uv run python scripts/data/generate_prerequisites.py --lang de --level A1
```
LLM generates direct prerequisite relationships between grammar points.
Cross-entity operation — sees all GPs at the target level + lower levels.

### 5. Map GPs to grammar book chunks *(Italian only)*
```
uv run python scripts/data/llm_remap_chunks.py
```
LLM maps each GP to the best chapter in the grammar book using
`chunk_enrichment.json`. Writes `chunk_ref` into `grammar_points.yaml`.

### 6. Ingest → MongoDB
```
uv run python -m maestro.sync.ingest
```
Upserts all GPs, CFs, vocab, and curriculum scenarios into MongoDB.

---

## Reference

### Data files

| File | Description |
|------|-------------|
| `data/{lang}/grammar_points.yaml` | Master GP list |
| `data/{lang}/comm_functions.json` | Master CF list |
| `data/{lang}/grammar_points.lock` | SHA256 + metadata for change detection |
| `data/{lang}/comm_functions.lock` | SHA256 + metadata for change detection |
| `data/it/chunk_enrichment.json` | Grammar book chunk descriptions (Italian) |

### GP YAML fields

| Field | Source |
|-------|--------|
| `code` | Source parse (short ≤10-char snake_case) |
| `label` | Source parse |
| `cefr_level` | Source parse (A0–B2) |
| `category` | Source parse |
| `subcategory` | augment_gp |
| `description` | augment_gp (short tooltip) |
| `examples` | augment_gp (4-6 target-language sentences) |
| `explanations` | augment_gp (en + target lang, keyed by language code) |
| `prerequisites` | generate_prerequisites (GP codes) |
| `chunk_ref` | llm_remap_chunks (Italian only) |
| `source_note` | Source parse (optional) |

### CF JSON fields

| Field | Source |
|-------|--------|
| `code` | Source parse |
| `label` | Source parse |
| `macro_category` | Source parse |
| `cefr_level` | Source parse (A0–B2) |
| `patterns` | Source parse |
| `description` | augment_cf (short tooltip) |
| `examples` | augment_cf (4-6 target-language utterances) |
| `explanations` | augment_cf (en + target lang, keyed by language code) |
