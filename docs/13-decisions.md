# 13 · Decisions and open questions

Decisions here are settled. Build on them; don't reopen them inside a task. To change one, write a short proposal in "Proposed changes" at the end and stop: the owner (Johannes) decides.

Facts were checked on 7 October 2026. Versions move, so confirm a version when you first add a dependency and record what you pinned in `PROGRESS.md`.

## Architecture decisions

| ID | Decision | Why | Rejected alternatives |
|---|---|---|---|
| ADR-01 | One multiplatform SwiftUI app target with iPhone, iPad and **Mac (native macOS, not Catalyst)** destinations. Deployment target iOS / iPadOS / macOS **26.0**. Build with **Xcode 27.0+ (Swift 6.4)**, which needs an Apple-silicon Mac on macOS 26.6+. Swift 6 language mode with complete strict concurrency. | 26.0 gives on-device Italian speech recognition (SpeechTranscriber) on all three platforms. The Mac version should behave like a Mac app (menus, windows, keyboard). | Mac Catalyst (cheaper, less native); a 27.0 minimum (would cut off devices for little gain). |
| ADR-02 | Code is split into `Packages/LearningCore` (pure Swift, Foundation only, builds and tests on Linux), `Packages/Storage` (GRDB) and `App` (SwiftUI plus platform adapters). | Agents can test the learning logic anywhere, including cloud sessions without Xcode. GRDB's Linux support is community-maintained and untested upstream, so storage stays out of the Linux-tested package. | One package (storage would break Linux builds); logic inside the app target (slow, simulator-only tests). |
| ADR-03 | Persistence uses **GRDB.swift 7.11.x** (MIT) with two SQLite files: a read-only **content pack** shipped in the bundle and a read-write **learner database**. | Full SQL control, mature, Swift 6 ready; the content pack is produced by the Python pipeline as plain SQLite. | SwiftData or Core Data (CloudKit uniqueness and conflict limits, opaque schema). |
| ADR-04 | Sync uses **CKSyncEngine** on the private CloudKit database. Only immutable **events** and a few **settings** records sync; all learner state is derived by replaying events. Write our own delegate. | Append-only events with UUIDs can't conflict; replay is deterministic and idempotent. | SQLiteData's SyncEngine (MIT, good) — it adds macros and schema rules for little gain on an append-only log. Revisit only if our delegate exceeds ~600 lines. |
| ADR-05 | Scheduling uses **FSRS-6**, our own Swift implementation, verified against **py-fsrs 6.3.2** using `fixtures/fsrs/fsrs6-reference.json`. Config: default 21 parameters, desired retention 0.9, **no learning or relearning steps, no fuzz**, maximum interval 36,500 days. | swift-fsrs has FSRS-6 only on an untagged `main`; the algorithm is about 150 lines; fixtures prove parity. No fuzz keeps replay deterministic across devices. | swift-fsrs pinned to a commit; FSRS-5; per-user optimisation (later, needs data). |
| ADR-06 | Content is authored as YAML in `content/`, checked and compiled by a Python 3.12 pipeline (`pipeline/`, CLI `content`) into `content.sqlite` plus audio. **Morph-it!** provides lemma and morphology lookup **at build time only**. Annotations are written to committed lock files. | Deterministic, reviewable builds; the checker enforces the syllabus; the app needs no NLP at runtime. | Runtime lemmatisation; spaCy or UD models (non-commercial licences). |
| ADR-07 | Audio is pre-rendered with **Azure AI Speech batch synthesis** (REST, `api-version=2024-04-01`). Use **standard (non-HD) it-IT neural voices**, one per character, with `wordBoundaryEnabled: true` for word timings and IPA `<phoneme>` overrides for mistakes. Encode as AAC `.m4a`. Cache by content hash in Git LFS. | Cheap (about $15 per 1M characters), word timings drive read-along highlighting, and IPA fixes stress errors. HD voices are real-time only, and the Dragon HD Omni variants don't take `<phoneme>`. | AVSpeechSynthesizer at runtime (quality varies, premium voices need a manual download); human voices (after the study). |
| ADR-08 | Speech recognition uses **SpeechAnalyzer + SpeechTranscriber (it-IT)** on device, with `DictationTranscriber` as the fallback. Availability is checked at runtime. There is **no pronunciation scoring**. A failed speaking attempt **never** becomes an FSRS lapse. | Apple has no pronunciation API; ASR guesses from context, so it can't judge double consonants. | Azure pronunciation assessment (no Italian phoneme names or prosody, needs a backend). |
| ADR-09 | Grading is deterministic and lives in LearningCore: an answer-pattern language, accent tolerance except for accent-minimal pairs, strict focus tokens and typo tolerance elsewhere. Feedback is stepped (hint, then answer plus rule). Only the **first attempt** feeds FSRS. | Explainable, testable with fixtures, works offline. | LLM grading (variable, needs network or recent hardware). |
| ADR-10 | No third-party LLMs or analytics SDKs. Foundation Models hints for writing are an optional, **flagged** extra, **off in study builds**. | Privacy, App Review simplicity, and a consistent experience for the study. | Cloud LLM role-play (post-MVP). |
| ADR-11 | Study telemetry is opt-in. A random install ID, batched JSON uploads to one small HTTPS endpoint (contract in `docs/12`), and no account. | The validation study needs item data; nothing more is collected. | Third-party analytics. |
| ADR-12 | Fonts are **Literata** (Italian text and headings) and **Instrument Sans** (UI), both SIL OFL 1.1, bundled from `design/fonts/`. | The Libro direction; OFL allows bundling. | System fonts only. |
| ADR-13 | Mascot: **Moka** (the stovetop coffee pot) is assumed — it was the last pick. Tito (pigeon) and two cups exist as alternates. The mascot is an asset set behind one `Mascot` view, so swapping it is an asset change. | Unblocks UI work; the final pick is an open question. | — |
| ADR-14 | Content IDs are permanent once released. `content/ids.lock` lists every ID ever compiled in a **release** build; removing one requires a `retired:` entry. Draft IDs may change until their file is first approved. | Events in iCloud reference these IDs forever; drafts must stay cheap to rework. | Locking every dev-build ID (stalls drafting). |
| ADR-15 | A content file is protected once `review.status: approved`. A hook blocks agent edits, `content lint` verifies `review.hash`, and `content approve`/`reopen` refuse to run from an agent's shell (no TTY or `CLAUDECODE` set). Changing approved content means the human sets it back to `in-review`. | "Nothing ships unreviewed" must hold mechanically. | Directory-based locking. |
| ADR-16 | Lessons run in order. The next unit unlocks once the current unit check has been **completed** (any score). A failed check schedules a targeted review and offers a retake. Placement can skip units. | Keeps momentum; the eligibility rule still guarantees nothing untaught appears. | Hard pass gates (frustrating, and the study measures finishing). |
| ADR-17 | The pack ships inside the app (no downloads in the MVP). Audio budget is **≤ 150 MB**: AAC-LC, 24 kHz mono, 48 kbps. If Units 0–1 project above budget, drop to 40 kbps. | Simplest; offline from first launch. | On-demand resources or background assets (post-MVP). |
| ADR-18 | Working name **Italiano**. Bundle ID **`com.j23n.italian`** (owner, 7 Oct 2026) on every platform; iCloud container **`iCloud.com.j23n.italian`**. The team ID stays out of the repo until the owner signs (Q10). | The bundle ID can't change after release; CloudKit containers can't be deleted, so both are fixed once. | — |
| ADR-19 | The **owner creates the Xcode project** once (M0.2) from Xcode 27's Multiplatform App template with synchronized folders, test targets, the two local packages and the shared scheme. Agents never edit `project.pbxproj`; they add files through the synchronized folders and change build settings in `App/Config/*.xcconfig`. Agents and CI build **unsigned** (`CODE_SIGNING_ALLOWED=NO`, an entitlements file without iCloud); sync runs only in the owner's signed builds with `ITA_SYNC_ENABLED`. | Hand-edited project files break easily; a CloudKit container is permanent once registered, so only the owner's deliberate first signed CloudKit build should create it. | XcodeGen or Tuist (another tool to maintain); agent-written `project.pbxproj`. |
| ADR-20 | **Articles before they are taught are part of the noun** (the lexical-article rule, `docs/04`): an article directly before a noun item, or before an adjective and a noun item, is part of that noun until the article's own unit (*un/una*: Unit 2; *il/la/lo…*: Unit 3). Cards always show nouns with the **definite article** (`il cornetto`, `l'acqua (f)`), and generated answers accept either article. | Learners meet nouns with their article from day one (*learn every noun with its article*) without the level gate rejecting Units 0–2. | Articles only from Unit 2 (bans *la signora Rossi* in Unit 1); display forms that switch article at Unit 3 (two forms to relearn, state-dependent rendering). |
| ADR-21 | Five colour tokens differ from the design canvas to meet contrast (input borders and switch tracks ≥ 3:1, dark accent text on its tint ≥ 4.5:1); `design/tokens.json` lists them in `$contrastChanges`, and `scripts/check-contrast.py` checks the pairs the UI uses. | Accessibility acceptance criteria in `docs/07`. | Keeping the canvas values (fails WCAG 1.4.11). |
| ADR-22 | **The content lead reviews on generated review pages and, from M6.10, in the app's review mode.** Both produce the same review file; `content review-import` files it unchanged in `reviews/inbox/` and adds its comments to a per-unit ledger, where agents record a resolution for each. Approval needs the teacher's sign-off, whose file hashes must match the files being approved (`docs/04` § Content review loop). | The teacher works in a browser or the app, never in YAML or Git; every comment is anchored to an ID and traceable to what was done about it; what's approved is exactly what was reviewed. | Comments in Word or Google Docs (anchors drift, hard to import); reviewing YAML in GitHub (needs Git skills); approval without hashes (later edits slip in). |

## Licences

Hard rule: nothing under a non-commercial licence enters the repo, the pipeline or the app, not even as a build-time helper.

| Resource | Licence | Our use |
|---|---|---|
| Morph-it! 0.4.7 (Zanchetta & Baroni) | CC BY-SA 2.0 or LGPL (dual) | Build-time lemma and morphology lookup only; never shipped. Keep its licence in `pipeline/data/morph-it/`. The licence notice is internally inconsistent (headed LGPL, text says GPL); we rely on CC BY-SA 2.0. |
| FrequencyWords, OpenSubtitles 2018 `it_50k` (hermitdave) | Lists: CC BY-SA 4.0; code: MIT | Build-time word ordering only; ranks are not shipped. |
| Wiktionary via kaikki.org | CC BY-SA (4.0 or 3.0) or GFDL | Optional build-time cross-check of glosses (warnings only). Never copy its glosses. |
| Tatoeba sentences | CC BY 2.0 FR by default; a CC0 subset | Not needed in the MVP. If ever shipped: CC0 subset only. Audio: only CC BY, BY-SA or CC0 recordings (empty licence = not reusable). |
| py-fsrs 6.3.2 | MIT | Reference for the fixtures only. |
| GRDB.swift 7.11, swift-snapshot-testing 1.19, MobileBuildMCP 2.7 | MIT | Dependencies or tools. |
| Literata, Instrument Sans | SIL OFL 1.1 | Bundled fonts; include OFL text in Acknowledgements. |
| Azure neural TTS output | Paid-tier output, commercial use allowed | Course audio; disclose "synthetic voices" in Acknowledgements. |
| **Forbidden** | non-commercial | Kelly lists (CC BY-NC-SA), spaCy `it_core_news_*` (CC BY-NC-SA 3.0), UD Italian ISDT, VIT, ParTUT, PoSTWITA and KIParla (NC), UDPipe 2 models (NC), Stanza's default Italian models (trained on NC data), De Mauro's Nuovo vocabolario di base (all rights reserved; consult only, by a human). |
| Exam papers and syllabi (CILS, CELI, PLIDA, joint syllabus) | copyrighted | References for humans. Never copy their wording, tasks or examples into content or the app. Past papers are used only offline in the study. |

CC BY-SA material stays at build time. Nothing derived from it ships, apart from facts such as lemma names. The app ships only our own content, OFL fonts and Azure audio. An Acknowledgements screen credits Morph-it!, FrequencyWords, Azure voices and the fonts anyway. This is not legal advice: the owner gets a quick legal read before App Store release.

## Open questions

Each has a default so work never blocks. The owner replaces the default when they decide.

| # | Question | Default until decided | Needed by |
|---|---|---|---|
| Q1 | ~~Who is the content lead?~~ **Answered 7 Oct 2026:** the owner has an Italian teacher as content lead. Their name goes into `content approve --by`. Reviews follow `docs/04` § Content review loop | — | — |
| Q2 | Bologna, or a fictional town? | Bologna; real places are fact-checked by the content lead | week 3 |
| Q3 | Passato prossimo for production from Unit 9 (CILS: P at A1; CELI Impatto: R)? | Produce from Unit 9 (avere) and Unit 11 (essere) | week 3 |
| Q4 | Synthetic voices for all MVP audio? | Yes; human story voices only after the study | week 4 |
| Q5 | Moka or Tito? | Moka (ADR-13) | before production art, week 8 |
| Q6 | Exam-practice mode? | Not in the MVP | after the study |
| Q7 | Pricing (subscription $50–70/yr or one-time)? | No payments in the MVP or TestFlight | after the study |
| Q8 | Story illustrations? | None in the MVP; layouts leave room for one image per story | week 8 |
| Q9 | Study endpoint host (any small HTTPS host)? | Build against the contract in `docs/12` with a local mock | week 12 |
| Q10 | Apple team ID (bundle ID and container are decided, ADR-18) | none in the repo; agents never sign (ADR-19) | before the owner signs a build (M6.8) |
| Q11 | Unit check pass rule | ≥ 70% overall and ≥ 50% in each section (docs/05) | week 6 |
| Q12 | Name of the village in Unit 11 | Content lead decides; use a fictional name to avoid fact-checking | week 3 |
| Q13 | Learner-facing English: American or British? | American English in the app and in glosses (largest market); these specs keep British spelling | week 3 |

## Content questions for the content lead (C1)

The seed content takes a default for each; the content lead confirms or changes it during sign-off.

| # | Question | Default in the seeds |
|---|---|---|
| CQ1 | *c'è / ci sono*: is the Unit 3 chunk *in questa foto c'è…* enough before the P point in Unit 6? | yes: the chunk in Unit 3, the point in Unit 6 |
| CQ2 | *bere* P in Unit 5 (core for the bar and food units)? | R in Unit 8 with *dare, dire* |
| CQ3 | Luca says Lei to Signora Rossi and to strangers; Signora Rossi says tu to "you" (assumes a younger learner)? | as in `story-bible.yaml` |
| CQ4 | Marco says Lei to Zia Rosa until she says *Dammi del tu!* (a switch point in Unit 11)? | tu from the start (family) |
| CQ5 | *cornetto* only, or also *brioche* (common in Bologna) as a recognise-only item? | *cornetto*; *brioche* in the item note |
| CQ6 | Bar Aurora prices (caffè 1,20 · cappuccino 1,60 · cornetto 1,40 · spremuta 3,20) and the other facts in `story-bible.yaml` → `facts_to_check` | as listed |
| CQ7 | `disambiguation.yaml`'s *la / l'* rule lists no proper nouns after *l'*, so *l'Italia* would be read as the clitic pronoun. Add `NPR` to its next-word list? | not yet in the seeds (no seed text has it); found by the annotator (M1.6) |
| CQ8 | `w:buono` has no `forms`, so *buon* (Morph-it! gives it its own lemma) doesn't resolve. Add `forms: [buon]`? | not yet |
| CQ9 | `w:italiano` is an adjective only, so *in italiano* (Unit 2 lesson 1, line 5) reads as the adjective. Give it a language-noun sense? | adjective (works, but the gloss is off) |
| CQ10 | The Unit 2 check targets nothing for `c:vorrei`, so the *vorrei* syllabus entries are never assessed. Add a check item for it? | not yet (found by check 1, M1.11) |
| CQ11 | The story bible has no register row for some pairs (Zia Rosa ↔ Giulia, Zia Rosa ↔ Sara). Which register do they use? | none: check 5 rejects the first line that needs one |
| CQ12 | `w:buono` (3 encounters) and `w:oggi` (4) need reuse in Unit 2 lessons 2–3 to reach the encounter target | to be written with lessons 2–3 |

## Implementation decisions (7 Oct 2026)

The owner asked agents to treat the handoff as a starting point: where it was wrong or underspecified, implement the better solution and record it. Each item below is also written into the spec it changes; `PROGRESS.md` has the evidence.

**Repository and build**
- The bundled pack and its audio are build outputs, not commits; only the paid TTS renders stay in LFS, as FLAC. CI checks pack determinism (two builds, one hash) instead of freshness. The mini pack is plain Git.
- GRDB 7.11.1 builds and passes on Linux (with `libsqlite3-dev`), so Storage tests run in `make test`, `make ci` and Linux CI; macOS stays the reference.
- `make lint-guards` also checks `Tokens.swift` against `design/tokens.json` (`scripts/gen-tokens.py --check`) and compiles the platform-neutral App files against the real packages (`scripts/check-app-logic.sh`; `--test` runs their tests on Linux).
- macOS sandbox capabilities are build settings, not entitlement keys; M0.2 deletes the template's `@main`, ContentView, asset catalog and entitlements. `Italiano-Info.plist` lives in `App/Config/`; `Signing.xcconfig` (gitignored) holds the owner's team ID.
- Morph-it! **0.4.8** (the last release) is pinned rather than 0.4.7.
- `server/` adds `GET /v1/export/events` (owner token) as the JSONL export docs/12 asks for; each line is `{installId, app, receivedAt, event}`.

**Content model and lint (M1.1, M1.2)**
- Lint, not the build, catches what a schema can't: match lengths, choice indices, sentence-building tiles, sound-pair `play`, conversation graphs, `pass` ≤ points, unit grammar vs `points.yaml`, IDs in the wrong place.
- Homograph slug collisions fail lint; an ID in `ids.lock` keeps its name, so only the newcomer needs a `~sense`. `ids.lock` is one ID per line with `#` comments.
- A ledger comment whose target is gone is an error while open, a warning once resolved (a fix may remove its target). The ledger entry format is defined in docs/04.
- Can-do `stretch` is optional; the two assessments files carry `review:` blocks; `approve` refuses an approved file (reopen first).

**Annotation (M1.4–M1.7)**, all forced by the real Morph-it! tags
- The elision table wins for its own forms; capitalised words take the lowercase readings and drop proper-noun ones (*Al*).
- Articulated prepositions map to their grammar point; `plural` counts as a surface form (*spremute*).
- `disambiguation.yaml` context rules apply even with a single candidate (clitic *la*); neighbours match on readings synthesised from items too.
- Detection matchers gain `any: true` (one analysis is enough) for verb forms Morph-it! files under several moods and participles it also lists as adjectives; *quando* is `detect: none`.
- `{ME.home}` may complete a chunk (`abito {ME.home}` → `c:abito`); near-miss patterns are annotated leniently; unit-title words of units without an items file are pending.
- Choice options are Italian unless the Italian is the stimulus (story, listening or reading steps, or an exercise with `prompt_it`, `audio_text` or `source`), which fits every seed exercise (see Proposed changes).

**Pack payloads (M2.1)**
- The JSON inside the pack tables has a contract, `schemas/pack-payloads.schema.json`, with examples; the builder validates against it and LearningCore decodes it. Patterns travel as `{source, expansions}`; a cloze gap's source is its content.
- Dev packs carry `meta.review_files` (`{idPrefix: {file, hash}}`) for the app's review mode. Review-comment categories are the kebab-case keys `italian-error`, `naturalness`, `level`, `answer-key`, `hint-or-rule`, `english`, `culture-or-facts`, `audio`, `other`.

**Grading (M2.3–M2.6)**
- Expansions never mix genders; dictation marks *e* for *è*, and another form of the same item, as wrong; slot-like names are errors; model answers use the masculine expansion while feedback shows the joined forms.
- After the spec review: equal-cost alignments prefer more exact word pairs, so a slot never takes a word the learner typed; in transcripts a slot weighs less than any literal. Strict gender forms make the other alternative an `ending` error. `H.MM` after a time cue (*alle*, *dalle*, *verso*…) reads as a time, otherwise both readings count. A `1` before a word matches *un/uno/una*. Hundreds elide (*centotto*). Only a missing or added accent on an accent-sensitive word makes another word, so *é* for *è* is `almost`. The generic hint comes from the first hard error. Corrections keep the author's case. Spoken talk answers collapse double consonants. Check, final and placement record every answer as `done(recorded)` and show nothing.
- The cross-language error contract is the message text (`PatternError.message` in Python, `PatternError.description` in Swift).

**Storage (M2.11, M2.12)**
- PackReader refuses a pack unless `schema_version` matches, the required meta keys exist (`schema_version`, `pack_version`, `content_hash`, `course_id`, `locale`, `release`), all tables exist and every query prepares. Match target order comes from the payload.
- The learner database checkpoints the whole derived state (`canonicalEncoding()`) and replays only later events at launch; the docs/03 tables are its queryable copy. New derived fields need a `derived_version` bump, not a migration. Remote payload bytes are stored as received, so fields from newer clients survive. `eraseProgress()` (Reset, zone deletion) is the only deletion. A local settings change is stamped `max(now, stored + 1)` so it wins over a device whose clock ran ahead.

**Checks and pack (M1.8–M1.12)**
- Checks read the annotation lock files. Prompts, options, tiles, `say` lines and notes go through the level gate as text. Chunk-only grammar points fail the construction gate outside their chunk. A speaker pair without a story-bible register row is an error. Coverage counts only written content; gaps in incomplete units are pending. `content suggest --topic` only shows context (the frequency list has no topics).
- Every exercise requires its own primary targets. A lesson's target grammar points are excluded only from steps before its note. Every unit with a spec gets an opener; task and check steps exist only when their files are written. Payload near-misses may be `correctWithNote` (a bare noun in generated recall).

**Review loop (M1.3, M1.13, M8.3)**
- Scopes `specs`, `uNN` and `assessments`. The content questions above are review targets `CQ1…`, hashed by their own section. A ledger status `noted` records an OK without a comment. Import refuses a file with any unknown target. Beta answers to adjudicate open each unit page; verdicts become proposals an agent applies after the owner reopens the file.

**Learner engine (M2.7–M2.10, M7.1)**
- Resume cursor: the answered prefix of a step, counting only lesson and check attempts with a `stepId`. In check, final and placement contexts every attempt is final. Conversations restart on resume.
- Each device's events get strictly increasing `at`, so an answer and the `checkCompleted` it ends replay in order.
- The daily review limit is the limit minus today's reviews; focus cards don't count against it.
- When "at most 2 in a row" is impossible, interleaving uses the smallest achievable run ⌈c/(n−c+1)⌉; grammar cards stay within ±2 of their even slots.
- Generated read cards fill distractors from other parts of speech when needed and place the answer with the session RNG.
- A "wrong article" is a singular article of the other gender (*l'* is never wrong).
- Placement blocks are scored like a check (*almost* = half). Failed-check focus lasts 3 days.
- Settings tie on time and device → the larger canonical JSON wins (merging stays commutative). `display.textScale` is device-scoped.

**Sync (M7.2–M7.4)**
- All sync logic is in `SyncDriver`, a platform-neutral actor over a `SyncEngine` seam, tested on Linux with a fake engine and in-memory private databases (two devices over many seeds). `CloudSync` only maps CloudKit types. Fetched events are stored with one `insertRemote` per zone fetch (or every 2,000), so a fetch costs at most one full replay.
- An event is immutable, so it is always saved as a new record; `.serverRecordChanged` on an event counts as saved, and only settings cache system fields. A send takes at most 400 records. `.quotaExceeded` pauses with a reason instead of retrying in a loop.
- The database belongs to the first iCloud account it syncs with (`local_meta.icloud_account`); a sign-in to another account counts as a switch, also when it happened while the app wasn't running. `CloudSync` exists only when `ITA_SYNC_ENABLED` and `ITA_ICLOUD_ENTITLEMENT` are YES, because iOS can't read its own entitlements and `CKContainer` crashes without one.

**Audio (M5.1, M5.4)**
- The pack compiler is the one source of audio needs; `content tts` and `content build` share it. A mock provider renders the same formats offline, so the whole flow runs in tests without a key.
- Audio IDs hash the assembly manifest (encode settings, renders' digests and sample counts, silences, effects), not the encoded file, so they don't depend on the ffmpeg build; the encode is pinned and writes an edit list (priming skipped, exact length).
- The render cache stores FLAC plus JSON metadata (`<key[:2]>/<key>.flac|json`); only the FLAC is in LFS. Mock renders and encoded files are build outputs. A need that can't be voiced is reported, never guessed (`c:sono-nato` got an `audio_say`).

**App**
- Platform-neutral view models for every exercise format and the lesson player are tested on Linux; the SwiftUI views and Apple-framework adapters still need their first Xcode build.
- A listening step ends with a transcript page (Show transcript), so the transcript appears only after its questions.
- Real-world layout strings are numbered in reading order; that number is `glossTapped.line` and `reading.field.<n>`.
- Telemetry sends the OS major version only; `onboardingCompleted` keeps only `reason` and `beginner`; unknown event types stay local and are marked sent.
- Onboarding is complete once `profile.forms` has a value; it syncs, so a second device skips onboarding. "Not now" on the study consent screen records a refusal (`granted: false`), and Settings → Research records a new consent date each time sharing is turned on; the install ID stays.
- The forms examples in onboarding and Settings (*americano/americana*) come from the pack's countries, not Swift. The fixed Italian UI lines docs/07 lists (greetings, *Bravo!*, *Indice*) are in `Localizable.xcstrings` with English comments. The Welcome headline is English ("Learn Italian, one story at a time."): `Welcome.png`'s Italian line is placeholder text and not on the list (see Proposed changes). The forms examples show the nationality pair only; docs/07's *nato/nata* has no source in the pack's countries.

**Placement and final check (M8.1, M8.2)**
- Placement runs only the blocks a pack can: up to the first block without exercises. Passing them all starts at the first unit without questions; a pack whose first block is empty (today's skeleton) offers no placement and "Yes, I know a little" goes straight to Today. The offer comes back at launch if placement never finished and the learner has nothing else (docs/05 § Placement, points 6–7).
- Leaving placement offers only Start from the beginning (or Keep going), so a placement left half-way never skips a unit.
- Placement is exempt from the eligibility rule (hard rule 4): it tests what the learner brings before anything is taught. The final check isn't: its missing requirements go through the mini-preview before the first item.
- The final check is entered from the final review unit's overview; a speaking section the device can't take is left out of the sitting, not only unscored. Talk and writing follow check mode in every check (no result, no Try again), which also fixes the unit check.
- Recordings are named by the `attempt` event's ID: written as `pending` while the learner speaks, renamed when the attempt is written (docs/09).
- The examiner export uses the app's own stored-ZIP writer instead of `NSFileCoordinator` `.forUploading` (deterministic, no extra wrapping folder, tested on Linux). The zip is written when the check ends and shared through `ShareLink`, which can't report whether sharing finished, so writing the zip counts as the successful export that deletes the raw recordings; the zip itself is kept 30 days so a cancelled share can be retried from the result or the final review unit. Without an install ID the file is `final-check-<date>.zip`; the date is the calendar date in the learner's time zone. `responses.json` has a documented shape (docs/12).
- App tests can't use LearningCore's test course (the Xcode test target links only the App), so they use their own synthetic course (`AssessmentCourse`): no pack has placement or final-check items yet.

**App shell (M3.3, M3.8, M3.10, M6.5)**
- The Debug menu's jump writes `placementCompleted` plus one `introduced` with `via: debug` (the enum value docs/05 already had), not `via: placement`: jumped-over items don't enter the catch-up queue, so debug data never looks like a real placement. `-ITAJumpToUnit` also completes onboarding with its defaults when it hasn't run, and writes only what is missing, so relaunching with it (the M3.6 resume test) writes nothing.
- The clock offset is a `DebugClock` (device clock + whole days) that the whole app runs on in builds with the Debug menu, observable by hand so time-dependent screens redraw; its offset is kept in `UserDefaults`, not in the learner database.
- "Export the learner DB" needed a Storage call: `LearnerStore.exportCopy(to:)` (SQLite online backup of a read snapshot, switched to a rollback journal so the copy is one file). The file exporter saves it (macOS: user-selected files).
- "Simulate speech by typing" wraps the real recogniser instead of swapping in `FakeSpeechRecognizer`: a recording asks for typed text in the player's debug overlay, so the real flow (live transcript, grading, cancel) runs unchanged.
- The Lesson-menu items are focused scene values published next to the existing in-view buttons (which keep their shortcuts for iPad keyboards); writing tasks don't publish Check, so Return still makes a new line. The View menu's text-size items step through fixed sizes and remember a size still being written, so ⌘+ pressed twice quickly goes up two steps. Whether a sheet's focused values reach the menu bar, and whether ⌘= also triggers ⌘+, need the owner's Mac check.
- Reminders: only turning the switch on asks for permission. At launch, refused notifications keep the switch on with a note (the reminder comes back when they're allowed again); a restored database on an install that never asked turns the switch off rather than asking.
- Telemetry: uploads also run after launch and after each session (docs/12 named background and every 15 minutes), queued so no event is in two requests at once; the uploader reads whichever learner store is open (an account switch replaces it). "Delete my study data" turns consent off before the DELETE and keeps it off if the request fails.
- `SettingsScreen` called `SettingsGroup(title:)`, which has an unlabeled title, and put `Divider()`s inside groups that draw their own hairlines; both fixed. `ReviewHost` had a copy of `PlayerHost`'s check-result functions referring to members it doesn't have; removed.

**Review mode (M6.10)**
- Hard rule 4 holds because review mode needs two keys: the build flag (`ITA_REVIEW_MODE = YES`, only Debug and Review; `AppConfig` refuses it in study builds and in any build of the release pack) and a dev pack (`meta.release = 0`), which learner builds never bundle. Only then is `ReviewMode.isActive`, and every bypass asks it: the Indice opens every unit, the player opens at the step or exercise picked in the jump menu (a step opened from Today or the Unit overview resumes when it is half done, else opens at its first page), and the mini-preview is skipped (the content lead sees content as authored). A test resolves the xcconfig chain and checks that Release and Study never get it. Debug builds have it on; `-ITANoReviewMode` turns it off for UI tests and screenshots of the learner's path.
- One review file per scope (the scope of the comment's file, as `content report` counts it), and per file version: the schema allows one hash per file, and `review-import` files a review in its scope's ledger. A unit-level step (opener, check) is a target in the unit spec, as the pipeline's index says, so its comments go to `specs`.
- The comment's `file` is required (the schema says so): a target whose file the pack's `meta.review_files` doesn't name can't be commented on, and the sheet offers only targets that resolve. Line targets are offered only for texts with numbered lines (real-world layouts have none).
- Comments live on the device in a JSON file, not in the event log: they are the content lead's working copy, not learner state, and never sync. Send posts only unsent comments; sent ones can't be deleted. Optional fields and an empty comment are written as `null`, like the page.
- "This should be accepted" appears in every feedback panel (inside `FeedbackPanel`, through the environment) when the exercise on screen has a rejected answer (the latest attempt draft was `wrong` with a response); a later accepted answer clears it, Show answer keeps it. It files `answer-key` / `change` with `response`, which `review-import` already turns into an accept proposal; conversation turns target `<exerciseId>/<nodeId>`.
- The review bar adds Previous and Next (any page without answering), so the content lead can reach every exercise; moving never writes `stepCompleted`, and finishing a unit check paged through this way never scores it (`checkCompleted`).
- The acceptance proxy is a Linux test (`ReviewModeTests`): it jumps to `u02.l1.ex07` on the mini pack, files an accept request and a comment, exports, checks the files against the schema's keys, enums and patterns, and compares them with `pipeline/tests/fixtures/review-app-*.json` (hashes aside), which a pipeline test validates with jsonschema and imports. The XCUITest waits for the UI test target (M0.2).

## Proposed changes

Agents add proposals here (date, ADR or question, proposal, reason) and stop. Don't implement a proposal until the owner accepts it.

| Date | Area | Proposal | Reason |
|---|---|---|---|
| 2026-10-07 | docs/06 choice | An explicit `options_lang: it \| en` on `choice` exercises, defaulting to today's inferred rule | The annotator infers the options' language from the context; an explicit field can't be wrong when an exercise moves |
| 2026-10-07 | LearningCore | Make `FeedbackMachine.FeedbackShown` a typealias of the event's `FeedbackShown` | Two identical enums; the App maps one to the other by raw value |
| 2026-10-07 | M1.6 lock files | Annotate each distinct expansion once | The lock files total 460 KB, mostly repeated pattern expansions |
| 2026-10-07 | Swift style | Run `swift format lint` (the toolchain ships it) in `make lint-guards` after one formatting pass | `.swift-format` exists but nothing enforces it; the code has drifted from it |
| 2026-10-08 | M1.6 lock files | Store a fingerprint of each string's sources (items, allowlist, chunks) in the lock files | `content check` reads the lock files; today only `annotate --check` catches an items edit that changes a token |
| 2026-10-08 | M1.12 topics | Add a licensed topic resource (e.g. Wiktionary categories via kaikki.org, CC BY-SA) so `content suggest --topic` can filter | the pinned frequency list has no topics; an owner decision because of the licence |
| 2026-10-08 | docs/07 copy | Add the Welcome headline *Impara l'italiano, una storia alla volta.* (from `Welcome.png`) to the fixed Italian UI lines, with its English under it | The reference screen shows it, but hard rule 6 allows only the listed greetings; the app shows the English line until the owner decides |
