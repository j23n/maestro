#!/usr/bin/env bash
# CLAUDE.md hard rule 3: LearningCore imports Foundation only, and takes time, IDs and randomness
# from Clock, UUIDSource and a seeded RNG. Run by CI (make lint-guards). Usage: check-core-imports.sh [dir]
set -euo pipefail
dir="${1:-Packages/LearningCore/Sources}"
[ -d "$dir" ] || { echo "no $dir yet"; exit 0; }
mods='GRDB|SwiftUI|UIKit|AppKit|AVFoundation|AVFAudio|Speech|CloudKit|FoundationModels|os|OSLog|Combine|SwiftData|CoreData|Network'
# any attributes (@preconcurrency, @testable, @_exported…), optional kind (import struct Foo.Bar), optional submodule
if grep -rnE "^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+((typealias|struct|class|enum|protocol|let|var|func)[[:space:]]+)?($mods)([.[:space:]]|$)" "$dir"; then
  echo "LearningCore must import Foundation only (CLAUDE.md hard rule 3)." >&2
  exit 1
fi
if grep -rnE "canImport\(($mods)\)" "$dir"; then
  echo "LearningCore must not branch on canImport of platform modules (CLAUDE.md hard rule 3)." >&2
  exit 1
fi
if grep -rnE '\bDate\(\)|\bUUID\(\)|\.random\(|\bDate\.now\b|SystemRandomNumberGenerator' "$dir"; then
  echo "LearningCore must use Clock, UUIDSource and a seeded RNG instead of Date(), Date.now, UUID() or system randomness (CLAUDE.md hard rule 3)." >&2
  exit 1
fi
echo "LearningCore imports OK"
