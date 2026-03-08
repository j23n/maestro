# Eval test workflow

**Area:** `.github/workflows/eval.yml` (new)
**Roadmap:** [03-cicd](../roadmap/03-cicd.md)
**Depends on:** #32 (GitHub Actions CI)

## Goal

Run eval tests on a nightly schedule and on-demand, without blocking normal CI.

## Work

### Create `.github/workflows/eval.yml`

- Trigger on `workflow_dispatch` (manual) and `schedule` (nightly cron)
- Single job: `uv run pytest -m eval tests/eval/ -v`
- Requires `ANTHROPIC_API_KEY` from GitHub repository secrets

### Configure repository secret

- Add `ANTHROPIC_API_KEY` to GitHub repo settings > Secrets and variables > Actions

## Verification

- Trigger the workflow manually via Actions tab and confirm eval tests run
- Confirm the workflow does not appear on normal push/PR events
- Confirm tests auto-skip gracefully if the secret is missing or starts with `test-`

## Notes

- Eval tests hit the real Anthropic API — they are slow and cost money, so they stay opt-in.
- Nightly schedule catches regressions from API changes without blocking development.
