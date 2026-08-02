# Maestro

This is a self-hostable Italian tutor, a very much working project I used to learn about tokenization, embeddings, LLM fine-tuning and RAG. No vibe-coding here, though I did use conversational AI to help me debug issues when I got stuck.

The main sources of info I used:

- [Hands-On Large Language Models]()

The original FastAPI + MongoDB web app has been retired (it lives in
git history — last present at commit `4ba88ad`, see
`docs/plans/decisions.md` #32). What's here now is its greenfield
successor: a local-first, offline-capable, CEFR-grounded system
targeting native iOS, per `docs/plans/02-greenfield-architecture.md`
(concepts) and `docs/plans/03-implementation-plan.md` (plan). Decisions
made along the way: `docs/plans/decisions.md`.

## The architecture at a glance

```
spec/it/          curriculum spec: grammar DAG, functions, scenarios,
                  can-do inventory, leveled vocab  (IDs are forever)
packs/it/         authored content (YAML, review lifecycle in-file)
authoring/        maestro-pack CLI: validate · build · generate ·
                  review (local web UI) · release          [Python]
core/             portable runtime: pack reader, event-sourced learner
                  model, mastery/SRS folds, session composer,
                  deterministic + alignment scoring   [Rust + UniFFI]
conformance/      golden vectors any core implementation must pass
prompts/runtime/  versioned LLM prompts shared by app AND evals
evals/            LLM eval loop: seeded golden sets, per-backend
                  runners, judge scoring, promotion gates  [Python]
ios/              SwiftUI shell (runs on simulator; speech + device run
                  outstanding)
```

The load-bearing rule: **content flows down, nothing flows back.** The
LLM does its heavy lifting at authoring time; the runtime is
deterministic and fully offline, with LLM feedback as an optional,
eval-gated enhancement.

## Working on it

```bash
uv sync --group dev                         # Python 3.13+

# Curriculum + content
uv run python -m authoring.cli validate     # spec + pack sources
uv run python -m authoring.cli build        # -> build/it.pack.sqlite
uv run python -m authoring.cli review       # review queue on :8321
uv run python -m authoring.cli generate --gp ind_pres --count 10
uv run python -m authoring.cli release

# Core (any platform)
cd core && cargo test                       # incl. conformance vectors
MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test pack_compat

# Eval loop
uv run python -m evals.harness.run --task writing_feedback --runner anthropic --judge anthropic
uv run python -m evals.harness.run --resolve-gates  # -> build/gates_resolved.json

# Tests + lint
uv run pytest tests/unit/
uv run ruff check authoring/ evals/ tests/
```

Only `generate` (API mode) and the anthropic eval runner/judge need
`ANTHROPIC_API_KEY` (see `.env.example`); everything else runs offline.

iOS build steps (Mac required): `ios/README.md`.
