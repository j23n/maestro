# Maestro

This is a self-hostable Italian tutor, a very much working project I used to learn about tokenization, embeddings, LLM fine-tuning and RAG. No vibe-coding here, though I did use conversational AI to help me debug issues when I got stuck.

The main sources of info I used:

- [Hands-On Large Language Models]()

## Architecture

- FastAPI backend
- Simple htmx frontend
- Postgres database
- Claude API integration

## Worktrees

After `git worktree add <path> <branch>`, run `scripts/setup-worktree.sh` from
inside the new worktree. It copies `.env` / `.env.scripts` from the main repo
and symlinks `src/maestro/static/audio/` so TTS-generated WAVs are shared across
worktrees (no unnecessary Azure TTS regeneration on startup). Idempotent.

## LLM Critique / Eval Flow

Logged-in users can flag any LLM output for review using the ⚑ button. Clicking it opens an inline textarea — enter a description of the problem, then submit. The flag is saved as an `LLMCritique` document with the reconstructed input/output snapshot attached.

**CLI: `scripts/critique.py`**

```bash
# List all flagged critiques (shows call_type, eval test, issue)
uv run python scripts/critique.py list
uv run python scripts/critique.py list --call-type scorer_multi --unexported

# Inspect a single critique
uv run python scripts/critique.py review <id>

# Annotate with the correct expected output (JSON)
uv run python scripts/critique.py annotate <id> --expected '{"objective_correct": false}'

# Interactively export annotated critiques as eval fixture cases
uv run python scripts/critique.py export
uv run python scripts/critique.py export --call-type analyzer
```

**Workflow:**
1. Flag a bad output in the UI (add a description of the issue)
2. `critique.py list` — find the record, note the `eval_test` column showing which test file it targets
3. `critique.py review <id>` — inspect input/output snapshots
4. `critique.py annotate <id> --expected '...'` — set the ground-truth expected output
5. `critique.py export` — appends a fixture case to the relevant JSON file under `tests/eval/fixtures/` and marks the critique as exported
6. Run the linked eval test to verify: `uv run pytest -m llm_eval tests/eval/<eval_test>.py -s`
