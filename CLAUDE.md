# Italian learning app

Native SwiftUI app (iPhone, iPad, Mac) for learning Italian through graded reading and listening, with an offline dictionary, verb tables, grammar reference and a spaced-repetition "Remember" deck. Full spec: `HANDOFF.md`. Read it before making product or data-model decisions.

## Non-negotiables

- **Offline first.** Every feature works in airplane mode. No runtime network calls except CloudKit sync and Background Assets pack downloads.
- **No backend.** No accounts, analytics servers or APIs of our own.
- **Text first.** The reader shows clean text. No highlighting layers, colour coding or inline glosses. Help appears only when the learner taps or selects.
- **Reference, not drills.** No conjugation drills or grammar quizzes. Practice happens only through Remember flashcards the learner chose to keep.

## Stack

- Swift 6, strict concurrency. SwiftUI multiplatform with a native macOS target (not Catalyst). Minimum OS 26 unless decided otherwise.
- Content: bundled read-only SQLite via GRDB, FTS5. Built offline by a script in `tools/`; never modified on device.
- Learner data: SwiftData + CloudKit private database. Preferences in `NSUbiquitousKeyValueStore`.
- Scheduling: FSRS behind a `Scheduler` protocol.
- Speech: `AVSpeechSynthesizer` (it-IT). Translation: Apple Translation framework (test on device; it does not run in the Simulator).

## SwiftData + CloudKit rules (break these and sync breaks)

- No `@Attribute(.unique)`. Deduplicate in the merge pass.
- Every property optional or with a default; every relationship optional.
- Never rename, delete or change the type of a property once the schema is deployed to Production. Add new properties instead.
- `ReviewLog` is append-only and authoritative; card scheduling fields are a cache rebuilt from logs.
- Cards reference content by stable string IDs (`lemmaID`, `senseID`, `grammarID`), never by copying entries.

## Code layout (suggested)

- `Packages/LexiconKit`: lookup cascade, forms, entries
- `Packages/GrammarKit`: verb tables, grammar topics
- `Packages/SRSKit`: FSRS, log replay
- `Packages/PackKit`: pack loading, `PackStore`, downloads
- `Packages/SpeechKit`: TTS, sentence and word highlighting
- `Packages/SyncStore`: SwiftData models, merge pass
- `App/`: SwiftUI screens per platform
- `tools/`: content database and pack build scripts
- `content/`: pack sources (Markdown + front matter)

## Conventions

- UI copy in English; Italian strings marked with the `it-IT` language for VoiceOver.
- Touch targets ≥ 44 pt on iOS. Every icon-only button has an accessibility label.
- Colours and type come from `design/tokens.json`. Use New York for Italian reading text, SF Pro for UI.
- Write tests for the lookup cascade, conjugation generation, FSRS replay and the sync merge pass.
