#!/usr/bin/env bash
# PreToolUse (Bash): blocks shell commands that would do what only people may do (CLAUDE.md hard rules 1, 8, 10):
#   - running `content approve` / `content reopen`, however it is invoked;
#   - writing protected files from the shell (fixtures/fsrs, the harness, ids.lock, approved content, the teacher's
#     review files in reviews/inbox): redirection
#     targets, and the files given to rm, mv, tee, truncate, chmod, sed -i, perl -i, cp/rsync/install (destination),
#     git checkout/restore/rm/mv. Reading them stays allowed.
# Defence in depth: the CLI also refuses to approve without a TTY, and `content lint` checks approval hashes.
set -uo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 "$(dirname "$0")/guard_bash.py"
