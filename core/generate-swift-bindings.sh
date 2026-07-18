#!/usr/bin/env bash
# Generate Swift bindings for the core into core/bindings/swift/.
# Works on any platform (bindings are source files, not binaries).
set -euo pipefail
cd "$(dirname "$0")"

cargo build
LIB=target/debug/libmaestro_core.so
[[ -f "$LIB" ]] || LIB=target/debug/libmaestro_core.dylib
cargo run --bin uniffi-bindgen -- generate \
    --library "$LIB" --language swift --out-dir bindings/swift
echo "bindings in core/bindings/swift/"
