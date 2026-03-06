# Phase 5: Grammar–Chunk Linkage

Link GrammarPoints to their authoritative ItalianChunk source, restructure explanations, and surface them properly in lessons.

## Context

- **ItalianChunk** (~96): authoritative grammar rules from the textbook, organized by chapter/section.
- **GrammarPoint** (231): CEFR-tagged learning objectives scraped from Profilo della Lingua Italiana. Source: `src/maestro/data/grammar_points.json`.
- **GrammarPointExplanation**: LLM-generated, per GP per CEFR level. Currently generated from scratch with chunks as loose "reference material". Prompt externalized to `prompts/grammar_explanations.yaml`.

Current link is indirect: semantic search at ingest sets `rag_refs` (top-3 similar chunks). This is fuzzy and often wrong.

## Goal

Make ItalianChunk the authoritative source for each GrammarPoint. Explanations become CEFR-adapted bilingual translations of the chunk, not free-form LLM output. Lessons are organized around chunks and surface explanations (not raw chunks) to the student.

---

## Tasks

### 5.1 — Create static GP→Chunk mapping file

**What**: Create `data/grammar_point_chunks.yaml` mapping each GP code to its primary ItalianChunk ref. Neither GPs nor chunks are expected to change, so this is a static data file.

**How**:
1. Write a one-off script that uses Claude to propose the best chunk ref for each of the 231 GPs, given the list of ~96 chunk refs + headings.
2. Output to `data/grammar_point_chunks.yaml` as `gp_code: chunk_ref`.
3. Manually review and correct the mapping.

**Format**:
```yaml
# data/grammar_point_chunks.yaml
la_distinzione_genere_e_numero_dei_nomi_regolari_a_suffisso_o_a_e_a_suffisso_e: book_4_il_nome_la_formazione_del_plurale_nomi_in_o
i_principali_nomi_invariabili_es_caffe_cinema_citta_universita: book_4_il_nome_la_formazione_del_plurale_nomi_invariabili
# ...
```

**Validation**: Every GP code appears exactly once. Every chunk ref exists in the ItalianChunk collection.

---

### 5.2 — Model changes

**GrammarPoint**: Add `chunk_ref: Optional[str]`, remove `rag_refs`.

```python
class GrammarPoint(Document):
    code: str
    label: str
    cefr_level: str
    category: str
    description: str
    chunk_ref: Optional[str] = None  # ItalianChunk.ref — set from mapping file at ingest
```

**GrammarPointExplanation**: Add `translation` field for English.

```python
class GrammarPointExplanation(Document):
    grammar_point: Link["GrammarPoint"]
    student_level: str           # "A1" | "A2" | "B1" | "B2"
    explanation: str             # CEFR-adapted Italian markdown
    translation: str             # English translation of the explanation
```

**Files touched**: `models.py`

---

### 5.3 — Update ingest to use static mapping

**What**: `learning/ingest.py` loads `data/grammar_point_chunks.yaml` and sets `chunk_ref` on each GP. Remove `link_grammar_points_to_rag()` and the `retrieve_for_grammar_point` call.

**Steps**:
1. Load the YAML mapping after inserting GrammarPoints.
2. For each GP, set `gp.chunk_ref = mapping[gp.code]` and save.
3. Warn on any GP code missing from the mapping.
4. Remove `rag_refs` usage everywhere in ingest.

**Files touched**: `learning/ingest.py`

---

### 5.4 — Rewrite `generate_explanations` to translate chunks

**What**: Instead of free-form generation, the script:
1. Loads the GP's linked ItalianChunk via `chunk_ref`.
2. Sends the chunk content + GP label/description to Claude.
3. Asks for a CEFR-adapted Italian explanation AND an English translation, per target level.

**Prompt changes** (in `prompts/grammar_explanations.yaml`):
- System prompt instructs: "You are adapting an authoritative Italian grammar rule for a student at level X. Produce two sections: one in Italian appropriate for this level, one in English."
- The chunk content is the primary input, not just "reference material".
- The GP label/description narrows the focus to the specific rule within the chunk.
- The per-level guidance keys (`level_guidance_a1` … `level_guidance_b2`) should be updated to request bilingual output.

**Code changes** (in `grammar/generate_explanations.py`):
- `_call_claude()`: update user message to pass chunk content as primary input (not via `rag_refs`).
- `_parse_response()`: extract both `explanation` and `translation` per level from the response.
- `_save_explanations()`: persist both fields on `GrammarPointExplanation`.

**Output**: Each `GrammarPointExplanation` now has both `explanation` (Italian) and `translation` (English).

**Files touched**: `grammar/generate_explanations.py`, `prompts/grammar_explanations.yaml`

---

### 5.5 — Update planner to group GPs by chunk

**What**: When selecting grammar points for a lesson, prefer GPs that share the same `chunk_ref`. This makes lessons coherent around a textbook section.

**Logic**:
1. `pick_grammar_points` (in `lezione/selection.py`) selects candidates as before (by weakness within CEFR level).
2. New grouping step: among the top candidates, find the `chunk_ref` with the most selected GPs and prefer that group.
3. Soft constraint — if the student's weaknesses are spread across chunks, don't force a single chunk at the expense of addressing real gaps.

**Grammar overview**: The lesson overview no longer shows raw ItalianChunk content. Instead, it collects the `GrammarPointExplanation` for each GP in the lesson and displays those.

**Files touched**: `lezione/selection.py`, `lezione/planner.py`

---

### 5.6 — Update lesson templates to surface explanations with chunk links

**What**: In lesson activities and feedback, show the GrammarPointExplanation (bilingual), with a link to the full ItalianChunk for students who want the authoritative source.

**Changes**:

1. **Grammar activity** (`lezione-activity-grammar.html`): Show `explanation` (Italian) + `translation` (English). Add a "Vedi la regola completa" link pointing to the chunk detail.

2. **Drill/activity feedback**: When a student gets a GP wrong, the feedback includes:
   - The relevant `GrammarPointExplanation` excerpt (Italian + English)
   - A link to the chunk detail page

3. **Lesson completion summary** (`lezione-complete.html`): For GPs the student struggled with, show the explanation with chunk link.

4. **Chunk detail route**: Add `GET /grammar/chunk/{ref}` that renders the raw ItalianChunk content (or reuse existing grammar detail route).

**Files touched**: `templates/lezione-activity-grammar.html`, `templates/lezione-complete.html`, `routes/grammar.py`, `routes/lezione.py`

---

### 5.7 — Remove `rag_refs` and old retrieval code

**What**: Clean up all references to `rag_refs` now that `chunk_ref` is the canonical link.

- Remove `GrammarPoint.rag_refs` field
- Remove `link_grammar_points_to_rag()` from `learning/ingest.py`
- Remove `retrieve_for_grammar_point()` from `rag/retrieve.py`
- Update `GeneratedDrill.rag_refs` — drills should reference `chunk_ref` from their GP instead
- Update planner drill generation: use `chunk_ref` to fetch the chunk, not `rag_refs`
- Update `drills/scoring.py` — uses `drill.rag_refs` to fetch chunk context for scoring feedback
- Keep `rag/retrieve.py` `retrieve()` and `get_chunks_for_refs()` — still useful for general RAG

**Files touched**: `models.py`, `learning/ingest.py`, `rag/retrieve.py`, `lezione/planner.py`, `drills/generator.py`, `drills/scoring.py`

---

### 5.8 — Update tests

- **Unit tests**: Update any tests that reference `rag_refs` on GrammarPoint.
- **Integration tests**: Update `tests/integration/test_scoring.py` (sets `drill.rag_refs = []`) and any fixtures that create GrammarPoint documents — add `chunk_ref`, remove `rag_refs`.
- **New test**: Validate that `data/grammar_point_chunks.yaml` contains all GP codes from `src/maestro/data/grammar_points.json` (static data integrity check).

**Files touched**: `tests/unit/`, `tests/integration/test_scoring.py`, `tests/integration/conftest.py`, new `tests/unit/test_grammar_chunk_mapping.py`

---

## Execution order

```
5.1  Create mapping file (prerequisite for everything)
 |
5.2  Model changes
 |
5.3  Update ingest ──────────┐
 |                            |
5.4  Rewrite generate_expl.  |
 |                            |
5.5  Update planner ──────── 5.7  Remove rag_refs
 |
5.6  Update templates
 |
5.8  Update tests (after all above)
```

5.3 and 5.4 can run in parallel. 5.7 should come after 5.3 and 5.5 are done (so nothing still reads `rag_refs`). 5.8 is last.

---

## Data flow after refactoring

```
grammar_point_chunks.yaml ─── static mapping ──→ GrammarPoint.chunk_ref
                                                        │
ItalianChunk.content ──── chunk text ──────────→ generate_explanations
                                                        │
                                              GrammarPointExplanation
                                              ├── explanation (Italian, CEFR-adapted)
                                              └── translation (English)
                                                        │
                              ┌──────────────────────────┤
                              ▼                          ▼
                    Lesson grammar overview    Drill/activity feedback
                    (shows explanations)       (shows explanation + link to chunk)
```
