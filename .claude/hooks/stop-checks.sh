#!/usr/bin/env bash
# Stop: run the fast checks for what this branch changed before Claude ends its turn (docs/10).
# Exit 2 sends the failures back to Claude to fix. stop_hook_active=true means Claude is already continuing
# because of this hook, so we let it stop to avoid a loop.
# Worktree-aware: checks run in the git top level of the session's cwd, not in CLAUDE_PROJECT_DIR.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
input="$(cat)"
[ "$(json_field "$input" stop_hook_active)" = "true" ] && exit 0

cwd="$(json_field "$input" cwd)"
root="$(repo_root "${cwd:-${CLAUDE_PROJECT_DIR:-.}}")"
[ -n "$root" ] || exit 0
cd "$root" || exit 0
[ -f Makefile ] || exit 0          # before M0.1 there is nothing to run

# Everything this branch changed: committed since it left main, plus uncommitted and untracked files.
base="$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main 2>/dev/null || echo HEAD)"
changed="$( { git diff --name-only "$base" 2>/dev/null; git ls-files --others --exclude-standard; } | sort -u )"
[ -z "$changed" ] && exit 0

fail=0
report=""
run() {
  local name="$1"; shift
  local out
  if ! out="$("$@" 2>&1)"; then
    fail=1
    report+=$'\n\n'"✗ ${name} failed (last 40 lines):"$'\n'"$(printf '%s' "$out" | tail -n 40)"
  fi
}
has() { grep -Eq "$1" <<<"$changed"; }

if has '^(Packages/LearningCore/|fixtures/(fsrs|grading|packs)/)'; then
  run "LearningCore tests (make test-core)" make test-core
  run "LearningCore import guard" bash scripts/check-core-imports.sh
fi
if has '^(Packages/Storage/|fixtures/packs/)' && [ "$(uname)" = "Darwin" ]; then
  run "Storage tests (make test-storage)" make test-storage
fi
has '^(pipeline/|schemas/|fixtures/grading/)' && run "pipeline tests (make test-pipeline)" make test-pipeline
if has '^(content|schemas|reviews)/'; then
  if [ -d pipeline/data/morph-it ]; then
    run "content checks (make check-content)" make check-content
  else
    echo "Skipped content checks: pipeline/data is missing here (run 'make data')." >&2
  fi
fi
has '^(scripts/|Makefile$|design/tokens\.json$)' && run "guards (make lint-guards)" make lint-guards

if [ "$fail" -ne 0 ]; then
  printf 'Checks failed. Fix them before finishing, or explain exactly why you cannot:%s\n' "$report" >&2
  exit 2
fi
exit 0
