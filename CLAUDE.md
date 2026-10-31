@.apple-ci/claude/j23n.md
@.apple-ci/claude/apps.md

# Italian learning app

Native SwiftUI app (iPhone, iPad, Mac) for learning Italian through graded reading and listening, with an offline dictionary, verb tables, grammar reference and a spaced-repetition "Remember" deck. Full spec: `HANDOFF.md`. Read it before making product or data-model decisions.

## Non-negotiables

- **Offline first.** Every feature works in airplane mode. No runtime network calls except CloudKit sync and Background Assets pack downloads.
- **No backend.** No accounts, analytics servers or APIs of our own.
- **Text first.** The reader shows clean text. No highlighting layers, colour coding or inline glosses. Help appears only when the learner taps or selects.
- **Reference, not drills.** No conjugation drills or grammar quizzes. Practice happens only through Remember flashcards the learner chose to keep.

## Stack

- Swift 6, strict concurrency. SwiftUI multiplatform with a native macOS target (not Catalyst). Minimum OS: iOS, iPadOS and macOS 27.
- Content: bundled read-only SQLite via GRDB, FTS5. Built offline by a script in `tools/`; never modified on device.
- Learner data: SwiftData + CloudKit private database. Preferences in `NSUbiquitousKeyValueStore`.
- Scheduling: FSRS-6 behind a `Scheduler` protocol. The schedule is computed from review logs into a local-only store (`ScheduleState`, `cloudKitDatabase: .none`) and never syncs.
- Speech: `AVSpeechSynthesizer` (it-IT). Translation: Apple Translation framework (test on device; it does not run in the Simulator).

## Build, CI and TestFlight

- `make` is the interface, as in every j23n app (`.apple-ci/claude/apps.md`, j23n/apple-ci's README): `make bootstrap`, `make test` (every package in `Packages/` and the pipeline's pytest tests in `tools/`), `make build`, `make test-app`, `make ci-linux`, `make ci-macos`.
- **CI** (`.github/workflows/ci.yml`): Linux runs `make ci-linux` on every push. The Mac runs `make ci-macos` with Xcode 27 on `main`, by hand, and on pull requests labeled `ci:mac`, but only once the repository variable `HOSTED_XCODE_27` is `true`, since the hosted runners don't have Xcode 27 yet. Until then, `macos-xcode-26` runs in its place and compiles the app with Xcode 26 against iOS and macOS 26 (`make build-xcode-26`), a check only, so keep the app's code and its packages' platforms within the 26 SDKs.
- **TestFlight** (`.github/workflows/testflight.yml`): the owner pushes a `v*` tag on `main`; the tag's version becomes `MARKETING_VERSION` and the build number is the commit count. Agents never push such a tag or run `make archive` or `make testflight`.

## SwiftData + CloudKit rules (break these and sync breaks)

- No `@Attribute(.unique)`. Deduplicate in the merge pass.
- Every property optional or with a default; every relationship optional.
- Never rename, delete or change the type of a property once the schema is deployed to Production. Add new properties instead.
- `ReviewLog` is append-only and authoritative; the FSRS schedule is a local cache rebuilt from logs, never a synced field.
- Cards reference content by stable string IDs (`lemmaID`, `senseID`, `grammarID`), never by copying entries.
- Merge pass: dedupe cards on `itemKey` after resolving IDs through `id_redirect`; keep the oldest, never edit logs, never merge or delete a card whose IDs the local content DB doesn't know.

## Content IDs and form tags (HANDOFF.md 6.5)

- Lemma, sense and grammar IDs come only from the ID registry in `content/ids/`, written by the pipeline. Never edit or invent them by hand.
- Verb forms use only the form tags in HANDOFF.md 6.5 (`cond.pass.1p`); labels are rendered from tags, never stored.
- Pack text is NFC; token and sentence ranges are UTF-16 `[start, length]`. Pack files must validate against `content/schema/`.

## Code layout (suggested)

- `Packages/LexiconKit`: lookup cascade, forms, entries
- `Packages/GrammarKit`: verb tables, grammar topics
- `Packages/SRSKit`: FSRS, log replay
- `Packages/PackKit`: pack loading, `PackStore`, downloads
- `Packages/SpeechKit`: TTS, sentence and word highlighting
- `Packages/SyncStore`: SwiftData models, merge pass
- `App/`: SwiftUI screens per platform
- `tools/`: content database and pack build scripts
- `content/`: pack sources (Markdown + front matter), `ids/` registry, `schema/`, `fixtures/`

## Conventions

- UI copy in English; Italian strings marked with the `it-IT` language for VoiceOver.
- Touch targets ≥ 44 pt on iOS. Every icon-only button has an accessibility label.
- Colours and type come from `design/tokens.json`. Use New York for Italian reading text, SF Pro for UI.
- Write tests for the lookup cascade, conjugation generation, FSRS replay and the sync merge pass.
