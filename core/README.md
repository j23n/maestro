# core — the portable core (Rust)

The portable core described in `docs/plans/03-implementation-plan.md`
§2, exported to Swift (and later Kotlin) via UniFFI: pack reader
(schema-compat checked, media + tombstones included), learner event log
with export/import backup, derived-state folds (decayed mastery, SM-2
vocab scheduling — FSRS deferred, `decisions.md` #5 — functions,
scenario depth, can-do rollup), session composer (incl. the
vocab-review slot), deterministic scoring + transcript alignment, and
the LLM pending-feedback queue.

```bash
cargo test                      # unit + integration + conformance (any platform)
MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test pack_compat
./generate-swift-bindings.sh    # Swift bindings → bindings/swift/ (any platform)
./build-xcframework.sh          # MaestroCore.xcframework (macOS only)
cargo run --example make_fixture -- fixture.pack.sqlite   # dev pack for the shell
```

API surface (see `src/lib.rs`): `Core.open(pack, learnerDb)`,
`manifest()`, `packStatus()`, `listItemIds()`, `getItemJson(id)`,
`listMedia()`, `getMedia(path)`, `listTombstones()`,
`scoreAttempt(id, response)`, `recordEvent(json)`, `listEventsJson()`,
`exportLog()`, `importLog(data)`, `enqueueFeedbackJob(json)`,
`listPendingFeedbackJobs()`, `completeFeedbackJob(id, backend, json)`,
`progressSummary(now)`, `composeSession(optionsJson)`, plus the free
function `alignTranscript(target, transcript)`.

Every API takes `now` explicitly where time matters — no wall-clock
reads in fold/compose paths; determinism is pinned by the golden
vectors in `../conformance/` (folds, session plan, scoring,
normalization, alignment), which any second implementation must pass.
