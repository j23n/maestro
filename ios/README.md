# ios — SwiftUI shell

**Status: complete-but-untested scaffold.** Everything in `Maestro/` was
written off-Mac against the UniFFI-generated API and Apple's documented
iOS 26 surfaces; it has never been compiled. Expect a session of small
compile fixes, not a redesign. The core it calls IS tested (Linux:
`cargo test`, conformance vectors, Python-built-pack compat, and
`five_lessons.rs` walking a simulated learner through all five lessons).

**To build it: `BUILD.md`.** `project.yml` (XcodeGen) is the project's
source of truth; `Maestro.xcodeproj` is generated, not committed.

## What's here

| File | Role | Depends on |
| --- | --- | --- |
| `CoreBridge.swift` | Only file touching the core; Codable mirrors of `core/src/model.rs` | committed bindings |
| `MaestroApp.swift` | Entry, tabs, session launcher | — |
| `SessionView.swift` | Session player: grammar cards, drills, passages, vocab review, speaking, writing; per-activity evidence events; `scenario_completed` at the end | CoreBridge |
| `SpeakingPracticeView.swift` | Read-aloud: mic + it-IT model consent, SpeechAnalyzer → `alignTranscript` → per-word colors, then optional LLM notes | Spike B outcome |
| `ProgressScreen.swift` | Can-do list, grammar labels, CEFR estimate | CoreBridge |
| `FlagSheet.swift` | Report a broken item in one sentence; the reports list and its export | CoreBridge |
| `WritingActivityView.swift` | Writing capture: offline rubric, then LLM grading | CoreBridge, FeedbackService |
| `LLM/PromptLibrary.swift` | Renders the bundled `prompts.json` — the same prompts the harness scores | `maestro-pack prompts` |
| `LLM/LLMBackend.swift` | Apple Foundation Models + Anthropic behind one protocol; eval gates | `gates_resolved.json` |
| `LLM/FeedbackService.swift` | Queue → pick an allowed backend → render → parse; privacy ledger | core feedback queue |
| `project.yml` | XcodeGen spec: target, bundled pack, permission strings | XcodeGen |
| `Deferred/` | Pack updater — written, excluded from the target | see `Deferred/README.md` |

## The two events that carry the loop

Both are easy to lose in a refactor and neither fails loudly:

- **`scenario_completed`**, emitted once when a session ends
  (`SessionView.recordCompletion`). `pick_scenario` orders by completion
  count, so without it the composer offers lesson one forever and lessons
  2–5 are unreachable. `core/tests/five_lessons.rs` pins this: delete the
  event and the test fails with the composer still on `a0-01-in-aereo`.
- **`introduced`**, emitted when a grammar card is dismissed
  (`GrammarCardView.markIntroduced`). Without it the grammar stays new,
  every session picks the `introduction` archetype, and the learner is
  re-taught the same points indefinitely.

## Mac checklist

1. **Spike A — core embedding.** Follow `BUILD.md`. Fix compile drift
   until a session plays on a device. Record friction → Rust-vs-Swift-core
   off-ramp decision (plan §2.2).
2. **Spike B — SpeechAnalyzer fairness.** Speaking activities now arrive
   in the session plan as `speaking_prompt` items with authored target
   text. Run one with deliberately non-native pronunciation; judge whether
   word-level alignment feels fair; tune `core/src/align.rs` near-match
   tolerances if not. Write the verdict into docs/plans/.

## The optional tutor, and why it's off

Three tasks are wired: writing grading (did they answer the prompt, what's
wrong), speaking feedback (why a word was off, on top of the deterministic
alignment), and re-explaining a drill mistake a different way.

Two rules hold the layer in place, and both are load-bearing:

- **Prompts come from the bundle, never from Swift string literals.**
  `prompts/runtime/*.yaml` is the one source; `maestro-pack prompts`
  compiles it to `build/prompts.json`. That shared source is what makes
  "the eval measures what ships" true, and `tests/unit/test_prompts.py`
  fails if a template grows a placeholder the app doesn't supply.
- **A backend runs only if measurement says it may.** `gates_resolved.json`
  comes from the eval harness. With no scorecard every Apple FM gate is
  closed, so wiring the framework in does not switch it on — the app
  queues the submission and shows why. `BUILD.md` has the sequence that
  opens them.

The deterministic layer is what the learner is owed and it always runs:
alignment verdicts for speaking, the length/vocabulary rubric for writing,
the pre-authored explanation for drills. The model only ever adds to that,
which is why a closed gate degrades to "saved for detailed feedback"
rather than a broken screen.

## Reporting broken content

Any activity can be reported from the nav bar, and a rejected answer gets a
second, higher-signal entry point right on the feedback panel — seeded with
what the learner typed, since "«salve» should count here" is the report worth
having. A report is an `item_flagged` event in the same append-only log as
everything else, so it works offline; the fold ignores it, so reporting can
never nudge mastery (`backup_and_feedback.rs` pins that).

Nothing is sent anywhere. Reports leave the device only when the learner
exports them from Progress → Reported problems, which writes a small
`maestro-flags.jsonl` — deliberately narrower than a backup, so reporting a
typo doesn't mean handing over a learning history. Each flag carries the
`pack_version` it was raised against, because the same item id can be fixed
and re-shipped.

On the other end:

```bash
uv run python -m authoring.cli flags maestro-flags.jsonl
```

pairs each report with the pack source it names and prints them together —
the complaint, the prompt, the answers it actually accepts. Reviewing is
read-only; `--apply` is the opt-in that marks those items `status: flagged`,
which takes them out of the next build.

## Core surface still to wire

Each is a straightforward wiring task once Spike A compiles:

- **Media from the bundle**: `listMedia()` / `getMedia(path)` — play pack
  audio (dialogue turns carry `audio` paths, speaking prompts a model
  pronunciation, vocab cards a front reading) and render images. Replaces
  the `TODO(on-Mac)` in `SessionView`; keep AVSpeechSynthesizer as the
  fallback for `audio == null`, which is every dialogue today.
- **Pack updates**: `packStatus()` (schema compat), `listTombstones()`;
  `Deferred/PackManager.swift` should read `index.json` +
  `release.json.sig` and verify the ed25519 signature with the bundled
  `keys/release_signing.pub` (sha256 alone is integrity, not
  authenticity).
- **Backup**: `exportLog()` / `importLog(data)` — the settings screen's
  export/restore actions are one call each.
- **Draining the queue in the background**: `listPendingFeedbackJobs` /
  `completeFeedbackJob(id, backend, result)`. A submission made while a
  gate was shut sits in the queue forever right now — nothing retries it
  when a backend later becomes available. The core side is done; what's
  missing is something that sweeps on launch.

## Deliberately not built yet

Settings/backup screens and scenario narrative framing.

The privacy ledger has a type and `FeedbackService` appends to it, but no
screen shows it — and nothing needs one yet: on-device feedback never
leaves the device, and the cloud tier is off unless someone supplies an
API key, which no UI currently offers. Build the screen with the key
field, not before.
