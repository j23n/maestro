#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit): format the edited file if the formatter is available. Never blocks.
# swift format picks up the repo's .swift-format (4 spaces, line length 120); ruff uses pipeline/pyproject.toml.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
input="$(cat)"
file="$(json_field "$input" tool_input file_path)"
{ [ -z "$file" ] || [ ! -f "$file" ]; } && exit 0
root="$(repo_root "$(dirname "$file")")"
case "$file" in
  *.swift) swift format --in-place "$file" >/dev/null 2>&1 || true ;;
  *.py)    [ -n "$root" ] && [ -d "$root/pipeline" ] && (cd "$root" && uv run --project pipeline ruff format "$file" >/dev/null 2>&1) || true ;;
esac
exit 0
