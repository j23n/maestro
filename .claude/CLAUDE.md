# Maestro

Local-first, offline-capable, CEFR-grounded Italian tutor (A0–A2).
Curriculum spec + authored content packs (Python tooling) → portable
Rust core (event-sourced learner model, session composer) → native iOS
shell. Optional LLM feedback is eval-gated. Architecture:
`docs/plans/02-greenfield-architecture.md`; plan:
`docs/plans/03-implementation-plan.md`; decision log:
`docs/plans/decisions.md`.

## Commands

```bash
uv sync --group dev                          # Python deps (3.13+)
uv run pytest tests/unit/                    # authoring + eval tests
uv run ruff check authoring/ evals/ tests/   # lint
uv run ruff format authoring/ evals/ tests/  # format

uv run python -m authoring.cli validate --quality   # + vocab/solvability checks
uv run python -m authoring.cli build         # -> build/it.pack.sqlite + coverage
uv run python -m authoring.cli review        # review web UI on :8321 (all types)
uv run python -m authoring.cli generate --type drill --gp <id> --count 10
uv run python -m authoring.cli generate --type reading --theme "Ferragosto" --level A1
uv run python -m authoring.cli generate-audio --provider mock   # azure/openai w/ keys
uv run python -m authoring.cli generate-images --provider mock  # openai w/ key
uv run python -m authoring.cli flags <file.jsonl>   # learner problem reports
uv run python -m authoring.cli release       # signed if keys/ exists (release keygen)

cd core && cargo test                        # incl. conformance vectors
MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test pack_compat
cargo clippy --all-targets -- -D warnings

uv run python -m evals.harness.run --task writing_feedback --runner mock
uv run python -m evals.harness.run --resolve-gates   # -> build/gates_resolved.json
```

Eval runs with `--runner anthropic` / `--judge anthropic` hit the real
API — skip in normal dev; `--runner mock` is offline.

## Layout

```
spec/it/          curriculum spec: grammar DAG, functions, scenarios,
                  can-do inventory, leveled vocab — IDs are forever
packs/it/         authored content YAML (status: draft|reviewed|flagged)
authoring/        maestro-pack CLI: validate (+--quality/--adversarial),
                  build, generate (all item families; gp/scenario/cando/
                  theme scopes), generate-audio, generate-images,
                  review, release (ed25519-signed, tombstone-guarded)
core/             Rust portable core + UniFFI (pack reader, events,
                  mastery/SM-2 folds, session composer, alignment scorer)
conformance/      golden vectors any core implementation must pass
prompts/runtime/  versioned LLM prompts shared by the app AND evals
evals/            eval harness (writing/speaking feedback, mistake
                  explanation, content generation), pinned judge
                  prompts, seeded cases + seed_cases.py, promotion gates
ios/              SwiftUI shell — UNTESTED scaffold, see ios/README.md
```

## Key rules

- **Content flows down, nothing flows back**: LLM heavy lifting happens
  at authoring time; the runtime is deterministic and offline.
- The pack build compiles only items with `status: reviewed`.
- All core APIs take `now` explicitly; no wall-clock reads inside the
  core (determinism + conformance vectors depend on it).
- Cross-language contract: Python `build_pack._normalize` must mirror
  `core/src/normalize.rs`; schema changes need both plus a conformance
  vector.
- `ios/Maestro/` was written off-Mac and never compiled — keep the
  ⚠️ UNTESTED banners until it runs on a device.

## Worktree Discipline

When working inside a git worktree, stay in that worktree for every tool
call, agent spawn, and file read/write. Never `cd` to the main repo or
another worktree.
