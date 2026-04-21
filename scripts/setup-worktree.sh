#!/usr/bin/env bash
# Set up a linked git worktree for local development.
#
# Copies .env / .env.scripts from the main repo (if missing) and symlinks the
# static audio directory so generated WAV files (word_*.wav, phrase_*.wav,
# lesson_*.wav, per-language dirs) are shared across worktrees. This avoids
# unnecessary Azure TTS regeneration on server startup and removes the need to
# hand-copy .env every time.
#
# Usage:
#   scripts/setup-worktree.sh
#
# Idempotent: safe to re-run. Skips anything that already exists.
set -euo pipefail

GIT_DIR="$(git rev-parse --git-dir)"
COMMON_DIR="$(git rev-parse --git-common-dir)"

if [[ "$(cd "$GIT_DIR" && pwd)" == "$(cd "$COMMON_DIR" && pwd)" ]]; then
    echo "Not running inside a linked worktree (git dir == common dir). Nothing to do." >&2
    exit 0
fi

WORKTREE_ROOT="$(git rev-parse --show-toplevel)"
MAIN_ROOT="$(cd "$COMMON_DIR/.." && pwd)"

if [[ "$WORKTREE_ROOT" == "$MAIN_ROOT" ]]; then
    echo "Worktree root equals main root; refusing to run." >&2
    exit 1
fi

echo "Main repo:  $MAIN_ROOT"
echo "Worktree:   $WORKTREE_ROOT"

copy_if_missing() {
    local name="$1"
    local src="$MAIN_ROOT/$name"
    local dst="$WORKTREE_ROOT/$name"
    if [[ -e "$dst" || -L "$dst" ]]; then
        echo "  skip $name (already exists)"
        return
    fi
    if [[ ! -f "$src" ]]; then
        echo "  skip $name (not in main repo)"
        return
    fi
    cp "$src" "$dst"
    echo "  copy $name"
}

echo "Env files:"
copy_if_missing ".env"
copy_if_missing ".env.scripts"

AUDIO_REL="src/maestro/static/audio"
AUDIO_SRC="$MAIN_ROOT/$AUDIO_REL"
AUDIO_DST="$WORKTREE_ROOT/$AUDIO_REL"

echo "Audio directory:"
if [[ ! -d "$AUDIO_SRC" ]]; then
    echo "  skip $AUDIO_REL (not in main repo)"
elif [[ -L "$AUDIO_DST" ]]; then
    echo "  skip $AUDIO_REL (already a symlink)"
else
    # Replace the worktree's checked-out audio dir with a symlink to the main
    # repo's audio dir. The tracked a0_*.wav files remain accessible via the
    # symlink target, and untracked word_*.wav / phrase_*.wav / per-language
    # audio are shared across worktrees.
    if [[ -d "$AUDIO_DST" && ! -L "$AUDIO_DST" ]]; then
        rm -rf "$AUDIO_DST"
    fi
    mkdir -p "$(dirname "$AUDIO_DST")"
    ln -s "$AUDIO_SRC" "$AUDIO_DST"
    echo "  link $AUDIO_REL -> $AUDIO_SRC"
fi

echo "Done."
