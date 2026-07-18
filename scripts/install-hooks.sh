#!/usr/bin/env bash
# Install git hooks: bash scripts/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$(git rev-parse --git-dir)/hooks"
mkdir -p "$HOOKS_DIR"
ln -sf "../../scripts/pre-commit" "$HOOKS_DIR/pre-commit"
echo "Pre-commit hook installed."
