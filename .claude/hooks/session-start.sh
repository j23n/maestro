#!/usr/bin/env bash
# SessionStart: stdout is added to Claude's context. Keep it short. Worktree-aware (uses the session's cwd).
source "$(dirname "$0")/lib.sh"
input="$(cat)"
cwd="$(json_field "$input" cwd)"
root="$(repo_root "${cwd:-${CLAUDE_PROJECT_DIR:-.}}")"
cd "${root:-${CLAUDE_PROJECT_DIR:-.}}" 2>/dev/null || exit 0
branch="$(git branch --show-current 2>/dev/null || echo '?')"
echo "Branch: ${branch}"
case "$PWD" in */.claude/worktrees/*) echo "Worktree: $PWD";; esac
[ -d pipeline/data/morph-it ] || echo "Note: pipeline/data is missing here; run 'make data' before content checks."
if [ -f PROGRESS.md ]; then
  echo "Recent progress (tail of PROGRESS.md):"
  tail -n 25 PROGRESS.md
fi
exit 0
