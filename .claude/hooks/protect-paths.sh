#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit|NotebookEdit): blocks edits that must stay human-only: generated FSRS fixtures,
# the harness, ids.lock, licences, approved content and the content lead's review files (reviews/inbox/).
# Exit 2 blocks the tool call and shows the message to Claude (CLAUDE.md hard rules 1, 8 and 10; docs/13 ADR-15).
# Works inside worktrees: the repo root comes from the edited file's own git top level, not from CLAUDE_PROJECT_DIR.
# Fails closed: if the input can't be read, the edit is blocked.
set -uo pipefail
command -v python3 >/dev/null 2>&1 || { echo "Blocked: python3 is missing, so the protect-paths hook can't check this edit." >&2; exit 2; }
exec python3 "$(dirname "$0")/protect_paths.py"
