# Building Maestro on a Mac

Everything here needs macOS + Xcode. None of it has been run — the Swift
in `Maestro/` has never been compiled (see `README.md`). Budget a session
of small compile fixes, not a redesign.

## First run

```bash
# 1. Rust toolchain for iOS, once per machine
rustup target add aarch64-apple-ios aarch64-apple-ios-sim

# 2. Build the core as an xcframework (macOS only)
./core/build-xcframework.sh          # -> core/build/MaestroCore.xcframework

# 3. Build the content bundle the app ships with
uv run python -m authoring.cli build --include-draft   # -> build/it.pack.sqlite

# 4. Generate and open the Xcode project
brew install xcodegen
cd ios && xcodegen && open Maestro.xcodeproj
```

Then set a signing team on the Maestro target and run.

`--include-draft` at step 3 is deliberate: the five A0 lessons are
authored but not yet human-reviewed, so a plain `build` compiles only the
older reviewed seed content and you will get a much thinner pack. The
build line tells you which you got.

The Swift bindings (`core/bindings/swift/`) are committed, so step 1 of
the old checklist — running `generate-swift-bindings.sh` — is no longer
needed. Re-run it only after changing the core's exported API.

## What to expect

`ios/project.yml` is the source of truth; `Maestro.xcodeproj` is
generated and not committed. Re-run `xcodegen` after changing the spec.
Never hand-edit the project — the edit will be lost.

Expected friction, roughly in order of likelihood:

1. **`SpeakingPracticeView.swift`** — the `SpeechAnalyzer` calls were
   written from documentation alone and never compiled. This is the one
   file where the API surface may be materially different.
2. **UniFFI call sites** — `CoreBridge.swift` was audited against the
   committed `maestro_core.swift`, so the names and signatures should
   line up. Anything wrong here should be a one-line fix.
3. **Swift 6 concurrency** — the target pins Swift 5 on purpose. The
   evidence arrays crossing the core boundary are `[[String: Any]]`,
   which strict concurrency rejects inside a `View`. Making evidence a
   typed struct is the real fix, and it's post-MVP.

## Checking it actually works

The learning loop is verified on Linux by
`core/tests/five_lessons.rs`, which composes all five lessons and walks a
simulated learner through them. On device, the equivalent smoke test is:

1. Start a 15-minute session. It should open with a grammar reference
   card, not a drill.
2. Work through it. The summary should show a correct/total count.
3. Start a second session — it must offer **a0-02-in-albergo**, not
   lesson one again. If it repeats lesson one, the `scenario_completed`
   event isn't reaching the core; that is the single most load-bearing
   event in the app.
4. Airplane mode: everything above must still work. The MVP makes no
   network calls at all (`PackManager` and `LLMBackend` are excluded
   from the target — see `Deferred/README.md`).

## Not in the MVP target

`Deferred/` holds the pack updater and the LLM tutor layer. Both are
written and both are excluded from the build; see `Deferred/README.md`
for what each needs to come back.
