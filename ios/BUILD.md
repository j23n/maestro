# Building Maestro on a Mac

Everything here needs macOS + Xcode. The steps below are verified: the
app compiles cleanly and runs on the iOS simulator (first full session
played 2026-08-02, see `README.md` for what remains).

## First run

```bash
# 1. Rust toolchain for iOS, once per machine
rustup target add aarch64-apple-ios aarch64-apple-ios-sim

# 2. Build the core as an xcframework (macOS only)
./core/build-xcframework.sh          # -> core/build/MaestroCore.xcframework

# 3. Build the content bundle the app ships with
uv run python -m authoring.cli build --include-draft   # -> build/it.pack.sqlite

# 4. Compile the shared prompts and resolve the eval gates
uv run python -m authoring.cli prompts                  # -> build/prompts.json
uv run python -m evals.harness.run --resolve-gates --allow-no-scorecards

# 5. Generate and open the Xcode project
brew install xcodegen
cd ios && xcodegen && open Maestro.xcodeproj
```

Then set a signing team on the Maestro target and run.

**The on-device tutor ships switched off.** `--allow-no-scorecards` emits a
gates file with every Apple FM task disabled, because nothing has measured
it yet. The app will queue submissions and say so rather than calling a
model. To open the gates:

```bash
cd evals/applefm-runner && swift build -c release && cd ../..
uv run python -m evals.harness.run --task writing_feedback --runner apple_fm
uv run python -m evals.harness.run --task speaking_feedback --runner apple_fm
uv run python -m evals.harness.run --task mistake_explanation --runner apple_fm
uv run python -m evals.harness.run --resolve-gates      # now scorecard-backed
```

Re-run `xcodegen` is not needed — just rebuild so the new
`gates_resolved.json` is bundled. This ordering is the point of the
design: a feature is enabled by measurement, not by being written.

`--include-draft` at step 3 is deliberate and, right now, essential.
The whole A0 band — 39 lessons, 680 items — is authored but not yet
human-reviewed, and a plain `build` compiles only `reviewed` content:

```
build --include-draft   961 items   the A0 arc, all 13 scenarios
build                    51 items   the older reviewed seed, ~1 lesson
```

The build line tells you which you got. Until the review pass runs
(`maestro-pack review`), a device build without `--include-draft` is not
worth installing.

## Audio and art: two choices that decide how it feels

Neither is wired into the build, and the defaults are not obviously
right.

**Audio — ship none.** The pack carries no audio at all: 311 listening
turns, 251 vocab cards and 78 speaking prompts all have `audio: null`,
and the app falls back to the system Italian voice
(`DialogueSpeaker`, `AVSpeechSynthesisVoice(language: "it-IT")`).
That fallback is decent.

**Do not run `generate-audio --provider mock` before a device build.**
Mock renders *valid silent WAVs*. The app plays audio when the field is
set, so mock audio replaces a working synthetic voice with silence —
strictly worse than nothing. Mock exists to prove the plumbing, not to
ship. Real audio needs a keyed run:

```bash
uv run python -m authoring.cli generate-audio --provider azure   # or openai
```

**Art — the mock images are 1×1 pixels.** `generate-images --provider
mock` writes valid 69-byte PNGs, which is enough for the media table and
the tests and nothing else; on a phone the lesson cards render blank. A
real run is 463 images (39 lesson cards, 251 vocab, 42 readings, 37
scenarios, 94 prompts) and needs a key:

```bash
uv run python -m authoring.cli generate-images --provider openai
```

Lesson art is the most visible of these — it is what the Learn path is
made of — so `--targets lessons,scenarios` (76 images) is the cheap
version worth doing first.

The Swift bindings (`core/bindings/swift/`) are committed, so step 1 of
the old checklist — running `generate-swift-bindings.sh` — is no longer
needed. Re-run it only after changing the core's exported API.

## What to expect

`ios/project.yml` is the source of truth; `Maestro.xcodeproj` is
generated and not committed. Re-run `xcodegen` after changing the spec.
Never hand-edit the project — the edit will be lost.

The one live risk: **`SpeakingPracticeView.swift`** — it compiles, but
the `SpeechAnalyzer` mic/recording session was written from
documentation alone and has never run against a real microphone. That is
Spike B. (The other friction once expected here — UniFFI call-site
drift, Swift 6 concurrency — did not materialize; everything else
compiles and runs as written.)

## Checking it actually works

The learning loop is verified on Linux by `core/tests/closes_a0.rs`,
which composes all thirty-nine A0 lessons in curriculum order, walks a
simulated learner through every one, and asserts all thirteen A0 can-dos
come out *achieved*. On device, the equivalent smoke test is:

1. Start a 15-minute session. It should open with a grammar reference
   card, not a drill.
2. Work through it. The summary should show a correct/total count, and
   the session should **end on its capstone** — the one activity with no
   model answer on screen at depth 3.
3. Start a second session — it must offer **a0-02-in-albergo**, not
   lesson one again. If it repeats lesson one, the `scenario_completed`
   event isn't reaching the core; that is the single most load-bearing
   event in the app.
4. Keep going. The arc is **breadth before depth**
   (`BREADTH_BEFORE_DEPTH = 3`): you get depth 1 of the first few
   scenarios before any scenario offers you its depth 2. Seeing
   `a0-04-in-giro` before `a0-01-in-aereo.d2` is correct, not a bug.
5. Open **Progress**. After finishing all three depths of a scenario its
   can-do should read *achieved*, not *in progress*. That is the whole
   point of the lesson design, and the only place in the app where the
   learner is told what they can now do.
6. Airplane mode: everything above must still work. The MVP makes no
   network calls at all (`PackManager` and `LLMBackend` are excluded
   from the target — see `Deferred/README.md`).

## Not in the MVP target

`Deferred/` holds the pack updater and the LLM tutor layer. Both are
written and both are excluded from the build; see `Deferred/README.md`
for what each needs to come back.
