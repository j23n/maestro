# core — the portable core (Rust)

Phase 0 walking skeleton of the portable core described in
`docs/plans/03-implementation-plan.md` §2: pack reader, learner event log,
and deterministic scoring, exported to Swift (and later Kotlin) via UniFFI.

```bash
cargo test                      # unit + roundtrip tests (any platform)
./generate-swift-bindings.sh    # Swift bindings → bindings/swift/ (any platform)
./build-xcframework.sh          # MaestroCore.xcframework (macOS only)
cargo run --example make_fixture -- fixture.pack.sqlite   # dev pack for the shell
```

Current API surface (see `src/lib.rs`): `Core.open(pack, learnerDb)`,
`manifest()`, `listItemIds()`, `getItemJson(id)`, `scoreAttempt(id, response)`,
`recordEvent(json)`, `listEventsJson()`.

Phase 3 adds the derived-state folds (mastery, FSRS, can-do rollup) and the
session composer behind the same object; the FFI style stays coarse-grained —
few calls, whole values.
