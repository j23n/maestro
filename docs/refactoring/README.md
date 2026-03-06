# Refactoring Plan — Phase 8+

Post-curriculum refactoring focused on reliability, maintainability, and testability.

## Phases

| Phase | Focus | Effort | Status |
|-------|-------|--------|--------|
| [A — Critical Fixes](phase-a-critical-fixes.md) | Sync-in-async bug, client lifecycle | 1-2 days | |
| [B — Structure](phase-b-structure.md) | Split planner, extract route logic, consolidate patterns | 3-5 days | |
| [C — Code Quality](phase-c-code-quality.md) | Enums, retry logic, query optimization, typed LLM responses | 3-5 days | |
| [D — Nice to Have](phase-d-nice-to-have.md) | Atomic updates, error UX, test infra | When time allows | |

## Execution

Phases are sequential — each builds on the prior one. Within a phase, tasks are generally independent unless noted.

## Validation

After every task:
```
uv run pytest -m unit tests/unit/ -v && uv run pytest -m integration tests/integration/ -v
```
