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

## New core surface to wire (landed off-Mac, after this scaffold)

The core now exposes more than the scaffold consumes — each is a
straightforward wiring task once Spike A compiles:

- **Media from the bundle**: `listMedia()` / `getMedia(path)` — play
  pack audio (dialogue turns carry `audio` paths, speaking prompts a
  model pronunciation, vocab cards a front reading) and render images
  (`images/scenarios/<id>.png` by convention, vocab/reading `image`
  fields). Replaces the `TODO(on-Mac)` in `SessionView`; keep
  AVSpeechSynthesizer as the fallback for `audio == null`.
- **Pack updates**: `packStatus()` (schema compat — prompt for an app
  update when `compatible == false`), `listTombstones()`;
  `PackManager` should read `index.json` + `release.json.sig` from the
  release layout and verify the ed25519 signature with the bundled
  `keys/release_signing.pub` (sha256 alone is integrity, not
  authenticity).
- **Backup**: `exportLog()` / `importLog(data)` — the settings screen's
  export/restore actions are now one call each.
- **Vocab review**: sessions include a `vocab_review` slot
  (`vocab_card` payloads: front/back/example + media) — a flip-card
  view with SM-2 self-grades (`srs_rating` on the evidence event).
- **Writing + feedback queue**: `enqueueFeedbackJob` /
  `listPendingFeedbackJobs` / `completeFeedbackJob(id, backend, result)`
  — the writing capture UI enqueues offline; when a backend is
  configured AND its gate allows, drain the queue, and completion folds
  the evidence event back automatically (the `feedback_source` label
  comes stamped).
- **Prompts**: bundle `prompts/runtime/*.yaml` and render the same
  templates the eval harness measures (including the new
  `speaking_feedback.yaml`) — hardcoding prompt strings in Swift breaks
  the "eval measures what ships" invariant.

## Deliberately not built yet

Settings/backup screens and the writing-capture UI (both now one core
call deep, see above), scenario narrative framing.
