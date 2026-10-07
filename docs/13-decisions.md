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

## Proposed changes

Agents add proposals here (date, ADR or question, proposal, reason) and stop. Don't implement a proposal until the owner accepts it.
