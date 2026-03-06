# Maestro Refactoring Plan

Comprehensive refactoring plan for the Maestro Italian tutoring app, organized into four sequential phases.

## Phases

| Phase | Focus | Effort | Tasks |
|-------|-------|--------|-------|
| [Phase 1](phase-1-critical-fixes.md) | Critical fixes | ~1 session | Async LLM call, regex injection, datetime.utcnow |
| [Phase 2](phase-2-foundation.md) | Foundation | 1-2 sessions | Client factory, profile helper, model registry, settings |
| [Phase 3](phase-3-structure.md) | Structure | 2-3 sessions | Taxonomy cache, background tasks, file splits, lazy load |
| [Phase 4](phase-4-test-coverage.md) | Test coverage | 2-3 sessions | ~31 new tests across 7 test files |
| [Phase 5](phase-5-grammar-chunk-linkage.md) | Grammar–Chunk linkage | 2-3 sessions | GP→Chunk mapping, bilingual explanations, planner grouping, template updates |

## Execution order

Phases are sequential — each builds on the prior one. Within a phase, tasks are generally independent and can be done in any order.

## Validation

After every task: `uv run pytest -m unit tests/unit/ -v && uv run pytest -m integration tests/integration/ -v`

## Task index

| ID | Task | Priority | File(s) touched |
|----|------|----------|----------------|
| 1.1 | Fix sync LLM in async route | Critical | `routes/lezione.py` |
| 1.2 | Sanitize regex in vocab search | Critical | `routes/vocab.py` |
| 1.3 | Replace datetime.utcnow() | Critical | `models.py`, `routes/lezione.py`, `learning/profile.py`, `lezione/planner.py`, `utils.py` |
| 2.1 | Extract Anthropic client factory | High | New `llm.py`, 7 consumer files |
| 2.2 | Extract get_profile() helper | High | New `profile.py`, 16 call sites |
| 2.3 | Single ALL_DOCUMENT_MODELS list | High | `models.py`, `db.py`, 2 test files |
| 2.4 | Unify settings access | High | `generate_definitions.py`, `generate_explanations.py`, `rag/ingest.py`, `rag/retrieve.py` |
| 3.1 | Replace global caches with taxonomy module | Medium | New `taxonomy.py`, `analyzer.py`, `lesson_analyzer.py`, `scoring.py`, tests |
| 3.2 | Handle background task errors | Medium | `utils.py`, `routes/lezione.py`, `lezione/planner.py` |
| 3.3 | Split large files | Medium | `planner.py` → +`selection.py`, `routes/lezione.py` → +`service.py`, `analyzer.py` → +`scorer.py` |
| 3.4 | Lazy-load SentenceTransformer | Medium | `rag/ingest.py` |
| 4.1 | Vocab discover/annotate tests | Low | New `tests/unit/test_discover.py`, `tests/integration/test_discover.py` |
| 4.2 | Planner tests | Low | New `tests/integration/test_planner.py` |
| 4.3 | Route form submission tests | Low | New `tests/integration/test_lezione_routes.py` |
| 4.4 | Lesson completion flow tests | Low | New `tests/integration/test_lesson_complete.py` |
| 4.5 | Vocab lookup tests | Low | New `tests/unit/test_vocab_lookup.py` |
| 4.6 | Profile description tests | Low | New `tests/integration/test_profile_description.py` |
| 5.1 | Create static GP→Chunk mapping | High | New `data/grammar_point_chunks.yaml` |
| 5.2 | Model changes (chunk_ref, translation) | High | `models.py` |
| 5.3 | Update ingest to use mapping | High | `learning/ingest.py` |
| 5.4 | Rewrite generate_explanations (bilingual) | High | `grammar/generate_explanations.py`, prompts |
| 5.5 | Update planner to group by chunk | Medium | `lezione/planner.py` |
| 5.6 | Update templates (explanations + chunk links) | Medium | `lezione-activity-grammar.html`, `lezione-complete.html`, `routes/grammar.py`, `routes/lezione.py` |
| 5.7 | Remove rag_refs | Medium | `models.py`, `learning/ingest.py`, `rag/retrieve.py`, `lezione/planner.py` |
| 5.8 | Update tests | Medium | `tests/unit/`, `tests/integration/conftest.py`, new mapping validation test |
