#!/usr/bin/env bash
# Type-check, and unit-test, the App target's platform-neutral Swift on any machine with a Swift toolchain (Linux
# included), against the real LearningCore and Storage packages. SwiftUI, UIKit, AppKit and the Apple-only
# frameworks don't exist on Linux, so this covers the files that import only Foundation, Observation, LearningCore
# and Storage (configuration, view models, adapter protocols, fakes) and the App tests that import only those plus
# Testing and `@testable import Italiano`. Views, adapters and snapshot tests are built by Xcode (make build-ios).
#
# Usage: scripts/check-app-logic.sh [--test]     (make lint-guards runs the type-check; --test also runs the tests)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/App/Italiano"
tests="$root/App/ItalianoTests"
[ -d "$app" ] || { echo "no App/Italiano yet"; exit 0; }
command -v swift >/dev/null 2>&1 || { echo "check-app-logic: no Swift toolchain, skipped"; exit 0; }

neutral() {  # neutral <file> <allowed-modules-regex>
  local f="$1" allowed="$2" mod
  grep -qE '#if[[:space:]]+(os\(|canImport|targetEnvironment)' "$f" && return 1
  while IFS= read -r mod; do
    [[ "$mod" =~ $allowed ]] || return 1
  done < <(grep -E '^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+' "$f" | sed -E 's/.*import[[:space:]]+([A-Za-z_]+).*/\1/')
  return 0
}

# One work directory per checkout, so worktrees (parallel agents) never share one.
work="${TMPDIR:-/tmp}/italiano-app-logic-$(printf '%s' "$root" | cksum | cut -d' ' -f1)"
# Two runs in the same checkout (make test and make lint-guards side by side) take turns instead of rebuilding
# each other's sources mid-build.
mkdir -p "$work"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$work.lock"
  flock 9
fi
rm -rf "$work/Sources" "$work/Tests"
mkdir -p "$work/Sources/Italiano" "$work/Tests/ItalianoTests"
n=0
while IFS= read -r f; do
  if neutral "$f" '^(Foundation|Observation|LearningCore|Storage|Dispatch)$'; then
    ln -s "$f" "$work/Sources/Italiano/$(echo "${f#"$app"/}" | tr '/' '_')"
    n=$((n + 1))
  fi
done < <(find "$app" -name '*.swift' | sort)
t=0
if [ -d "$tests" ]; then
  while IFS= read -r f; do
    if neutral "$f" '^(Foundation|Observation|LearningCore|Storage|Dispatch|Testing|Italiano)$'; then
      ln -s "$f" "$work/Tests/ItalianoTests/$(echo "${f#"$tests"/}" | tr '/' '_')"
      t=$((t + 1))
    fi
  done < <(find "$tests" -name '*.swift' | sort)
fi
[ "$n" -gt 0 ] || { echo "check-app-logic: no platform-neutral files"; exit 0; }
test_target=""
[ "$t" -gt 0 ] && test_target=", .testTarget(name: \"ItalianoTests\", dependencies: [\"Italiano\", \"LearningCore\", \"Storage\"], swiftSettings: [.swiftLanguageMode(.v6)])"
cat > "$work/Package.swift" <<EOF
// swift-tools-version: 6.2
import PackageDescription
let package = Package(
    name: "Italiano",
    platforms: [.iOS(.v26), .macOS(.v26)],
    dependencies: [.package(path: "$root/Packages/LearningCore"), .package(path: "$root/Packages/Storage")],
    targets: [.target(name: "Italiano", dependencies: ["LearningCore", "Storage"],
                      swiftSettings: [.swiftLanguageMode(.v6)])$test_target]
)
EOF
echo "check-app-logic: $n platform-neutral App files, $t test files"
cmd=(swift build --package-path "$work")
[ "${1:-}" = "--test" ] && [ "$t" -gt 0 ] && cmd=(swift test --package-path "$work")
[ "${1:-}" != "--test" ] && [ "$t" -gt 0 ] && cmd=(swift build --build-tests --package-path "$work")
if out="$(ITALIANO_ROOT="$root" ITALIANO_SWIFTPM_BUILD="$work/.build" "${cmd[@]}" 2>&1)"; then
  echo "$out" | grep -E "warning:|✘|passed after|Test run" | sed "s|$work/Sources/Italiano/||; s|$work/Tests/ItalianoTests/||" || true
  echo "App logic OK"
else
  echo "$out" | grep -E "error:|warning:|✘|failed" | sed "s|$work/Sources/Italiano/||; s|$work/Tests/ItalianoTests/||" >&2
  echo "App logic does not compile or its tests fail" >&2
  exit 1
fi
