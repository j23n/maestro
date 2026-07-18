# ios — SwiftUI shell

**Status: complete-but-untested scaffold.** Everything in `Maestro/` was
written off-Mac against the UniFFI-generated API and Apple's documented
iOS 26 surfaces; it has never been compiled. Expect a session of small
compile fixes, not a redesign. The core it calls IS tested (Linux:
`cargo test`, conformance vectors, Python-built-pack compat).

## What's here

| File | Role | Depends on |
| --- | --- | --- |
| `CoreBridge.swift` | Only file touching the core; Codable mirrors of `core/src/model.rs` | generated bindings |
| `MaestroApp.swift` | Entry, tabs, session launcher | — |
| `SessionView.swift` | Session player: drills (typed + choices), passages with per-question scoring, evidence events | CoreBridge |
| `SpeakingPracticeView.swift` | Read-aloud: SpeechAnalyzer (it-IT) → `alignTranscript` → per-word colors | Spike B outcome |
| `ProgressScreen.swift` | Can-do list, grammar labels, CEFR estimate | CoreBridge |
| `PackManager.swift` | release.json check → download → sha256 verify → atomic swap | `maestro-pack release` output |
| `LLMBackend.swift` | Backend protocol, Anthropic + Apple FM impls, eval-gate loading, privacy-ledger entry type | `evals/` gates |

## Mac checklist (in order)

1. **Spike A — core embedding.**
   `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`, then
   `../core/build-xcframework.sh`. New iOS-26 app project here; add the
   xcframework + `core/bindings/swift/maestro_core.swift` + the files in
   `Maestro/`. Bundle a pack: `python -m authoring.cli build` and add
   `build/it.pack.sqlite` as resource `it.pack.sqlite` (or use
   `cargo run --example make_fixture`). Fix compile drift until the seed
   drill plays on a device. Record friction → Rust-vs-Swift-core
   off-ramp decision (plan §2.2).
2. **Spike B — SpeechAnalyzer fairness.** Run `SpeakingPracticeView`
   with deliberately non-native pronunciation; judge whether word-level
   alignment feels fair; tune `core/src/align.rs` near-match tolerances
   if not. Write the verdict into docs/plans/.
3. **Eval runner.** `cd ../evals/applefm-runner && swift build -c release`,
   then from repo root:
   `python -m evals.harness.run --task writing_feedback --runner apple_fm`
   and `--resolve-gates`. Bundle `build/gates_resolved.json` into the app.
4. Mic + speech permission strings (`NSMicrophoneUsageDescription`,
   `NSSpeechRecognitionUsageDescription`) in the target's Info tab.

## Deliberately not built yet

Vocab-review UI (needs vocab item type in packs), writing capture +
pending-feedback queue UI, settings/backup screens, scenario narrative
framing. All have core support or clean seams already.
