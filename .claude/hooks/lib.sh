#!/usr/bin/env bash
# Shared helpers for hooks. python3 ships with Xcode's command-line tools and with every Linux image we use.

# json_field '<json>' key [subkey…]: print one field of the hook input (empty if missing or unparsable).
json_field() {
  printf '%s' "$1" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1:]:
    d = d.get(k, "") if isinstance(d, dict) else ""
print(d if not isinstance(d, bool) else str(d).lower())' "${@:2}" 2>/dev/null
}

# repo_root <dir>: the git top level of <dir> (a worktree's own root inside .claude/worktrees/), or "".
repo_root() {
  local dir="$1"
  while [ -n "$dir" ] && [ ! -d "$dir" ]; do dir="$(dirname "$dir")"; done
  git -C "${dir:-.}" rev-parse --show-toplevel 2>/dev/null
}
