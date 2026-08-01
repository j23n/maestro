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
| `SessionView.swift` | Session player: grammar cards, drills, passages, vocab review, speaking; per-activity evidence events; `scenario_completed` at the end | CoreBridge |
| `SpeakingPracticeView.swift` | Read-aloud: SpeechAnalyzer (it-IT) → `alignTranscript` → per-word colors | Spike B outcome |
| `ProgressScreen.swift` | Can-do list, grammar labels, CEFR estimate | CoreBridge |
| `FlagSheet.swift` | Report a broken item in one sentence; the reports list and its export | CoreBridge |
| `project.yml` | XcodeGen spec: target, bundled pack, permission strings | XcodeGen |
| `Deferred/` | Pack updater and LLM tutor — written, excluded from the target | see `Deferred/README.md` |

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
- **Writing + feedback queue**: `enqueueFeedbackJob` /
  `listPendingFeedbackJobs` / `completeFeedbackJob(id, backend, result)`.
  Writing prompts are authored and in the pack, but the composer's
  production slot currently draws speaking only; the capture UI is the
  missing half.
- **Prompts**: bundle `prompts/runtime/*.yaml` and render the same
  templates the eval harness measures — hardcoding prompt strings in
  Swift breaks the "eval measures what ships" invariant.

## Deliberately not built yet

Settings/backup screens, the writing-capture UI, scenario narrative
framing, and the privacy ledger (nothing leaves the device in the MVP,
so there is nothing yet to show).
