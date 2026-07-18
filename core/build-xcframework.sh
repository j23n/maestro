#!/usr/bin/env bash
# Build MaestroCore.xcframework for iOS device + simulator. macOS only.
#
# One-time setup:
#   rustup target add aarch64-apple-ios aarch64-apple-ios-sim
set -euo pipefail
cd "$(dirname "$0")"

[[ "$(uname)" == "Darwin" ]] || { echo "requires macOS/Xcode"; exit 1; }

cargo build --release --target aarch64-apple-ios
cargo build --release --target aarch64-apple-ios-sim
./generate-swift-bindings.sh

# The modulemap must sit next to the header inside each library's headers dir.
HEADERS=bindings/swift
mv -f "$HEADERS/maestro_coreFFI.modulemap" "$HEADERS/module.modulemap" 2>/dev/null || true

rm -rf build/MaestroCore.xcframework
xcodebuild -create-xcframework \
    -library target/aarch64-apple-ios/release/libmaestro_core.a -headers "$HEADERS" \
    -library target/aarch64-apple-ios-sim/release/libmaestro_core.a -headers "$HEADERS" \
    -output build/MaestroCore.xcframework
echo "built core/build/MaestroCore.xcframework"
echo "add it to the Xcode project together with bindings/swift/maestro_core.swift"
