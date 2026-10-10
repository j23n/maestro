#!/usr/bin/env bash
# [owner] `make archive CONFIG=Study|Release|Review` (docs/10, ADR-19). Never run by agents: it signs with the
# owner's team (from the gitignored Signing.xcconfig at the root). Swaps the release pack into the bundle for the
# archive only and restores the dev pack on exit, whatever happens.
set -euo pipefail
config="${1:-Release}"
[ -n "${CLAUDECODE:-}" ] && { echo "archive is the owner's step (ADR-19)." >&2; exit 1; }
pack="App/Italiano/Resources/Content/content.sqlite"
release="build/release/content.sqlite"
[ "$config" = "Review" ] || [ -f "$release" ] || { echo "no $release: run make pack-release first" >&2; exit 1; }
[ -f "$pack" ] || uv run --project pipeline content build        # the dev pack is a build output, not committed
backup="$(mktemp)"
cp "$pack" "$backup"
restore() { cp "$backup" "$pack"; rm -f "$backup"; echo "restored the dev pack"; }
trap restore EXIT
# Review archives keep the dev pack (drafts included); Release and Study archives bundle the release pack.
[ "$config" = "Review" ] || cp "$release" "$pack"
xcodebuild -project Italiano.xcodeproj -scheme Italiano -configuration "$config" \
  -destination 'generic/platform=iOS' -archivePath "build/archive/Italiano-$config.xcarchive" archive
