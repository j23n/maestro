#!/usr/bin/env bash
# Type-check the App target's platform-neutral Swift files on any machine with a Swift toolchain (Linux included),
# against the real LearningCore and Storage packages. SwiftUI, UIKit, AppKit and the Apple-only frameworks don't
# exist on Linux, so this covers the files that import only Foundation, Observation, LearningCore and Storage:
# configuration, view models, adapter protocols and fakes. Views and adapters are built by Xcode (make build-ios).
#
# Usage: scripts/check-app-logic.sh            (run by make lint-guards when a Swift toolchain is present)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/App/Italiano"
[ -d "$app" ] || { echo "no App/Italiano yet"; exit 0; }
command -v swift >/dev/null 2>&1 || { echo "check-app-logic: no Swift toolchain, skipped"; exit 0; }

allowed='^(Foundation|Observation|LearningCore|Storage|Dispatch)$'
files=()
while IFS= read -r f; do
  ok=1
  while IFS= read -r mod; do
    [[ "$mod" =~ $allowed ]] || { ok=0; break; }
  done < <(grep -E '^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+' "$f" | sed -E 's/.*import[[:space:]]+([A-Za-z_]+).*/\1/')
  grep -qE '#if[[:space:]]+(os\(|canImport)' "$f" && ok=0
  [ "$ok" = 1 ] && files+=("$f")
done < <(find "$app" -name '*.swift' | sort)

[ "${#files[@]}" -gt 0 ] || { echo "check-app-logic: no platform-neutral files"; exit 0; }

work="${TMPDIR:-/tmp}/italiano-app-logic"
rm -rf "$work/Sources"
mkdir -p "$work/Sources/AppLogic"
for f in "${files[@]}"; do ln -s "$f" "$work/Sources/AppLogic/$(echo "${f#"$app"/}" | tr '/' '_')"; done
cat > "$work/Package.swift" <<EOF
// swift-tools-version: 6.2
import PackageDescription
let package = Package(
    name: "AppLogic",
    platforms: [.iOS(.v26), .macOS(.v26)],
    dependencies: [.package(path: "$root/Packages/LearningCore"), .package(path: "$root/Packages/Storage")],
    targets: [.target(name: "AppLogic", dependencies: ["LearningCore", "Storage"],
                      swiftSettings: [.swiftLanguageMode(.v6)])]
)
EOF
echo "check-app-logic: type-checking ${#files[@]} platform-neutral App files"
if out="$(swift build --package-path "$work" 2>&1)"; then
  echo "$out" | grep -E "warning:" | sed "s|$work/Sources/AppLogic/||" || true
  echo "App logic OK"
else
  echo "$out" | grep -E "error:|warning:" | sed "s|$work/Sources/AppLogic/||" >&2
  echo "App logic does not compile" >&2
  exit 1
fi
