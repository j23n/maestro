# GitHub Actions CI workflow

**Area:** `.github/workflows/ci.yml` (new)
**Roadmap:** [03-cicd](../roadmap/03-cicd.md)
**Depends on:** none

## Goal

Run tests and linting automatically on every push and pull request so broken code never reaches main.

## Work

### Create `.github/workflows/ci.yml`

Two jobs, both triggered on `push` and `pull_request`:

**test**
- Use `ubuntu-latest`
- Set up Python 3.13
- Install `uv`
- Install dependencies: `uv sync`
- Run unit tests: `uv run pytest -m unit tests/unit/ -v`
- Run integration tests: `uv run pytest -m integration tests/integration/ -v`

**lint**
- Use `ubuntu-latest`
- Set up Python 3.13
- Install `uv`
- Install dependencies: `uv sync`
- Run linter: `uv run ruff check`

### Caching

- Cache the uv cache directory between runs to speed up installs

## Verification

- Push a branch and confirm both jobs appear in the Actions tab
- Push a failing test and confirm the workflow fails
- Push a ruff violation and confirm the lint job fails

## Notes

- No secrets are needed — unit tests use mongomock and mocked Anthropic client.
- `ANALYSIS_ENABLED` does not need to be set; tests don't depend on mlx-lm.
