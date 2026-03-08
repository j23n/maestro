# Branch protection for main

**Area:** GitHub repo settings
**Roadmap:** [03-cicd](../roadmap/03-cicd.md)
**Depends on:** #32 (GitHub Actions CI)

## Goal

Prevent merging to main when CI is failing.

## Work

### Configure branch protection rule on `main`

- Require status checks to pass before merging:
  - `test` job from CI workflow
  - `lint` job from CI workflow
- Require branches to be up to date before merging
- Require a pull request before merging (no direct pushes to main)

## Verification

- Open a PR with a failing test — merge button is blocked
- Open a PR with a linting error — merge button is blocked
- Open a PR with all checks passing — merge button is enabled
- Confirm direct pushes to main are rejected

## Notes

- This is a manual configuration step in GitHub repo settings > Branches > Branch protection rules.
- The eval workflow is intentionally excluded — it should not block merges.
- Railway auto-deploy (ticket #31) triggers on push to main, so this rule ensures only passing code gets deployed.
