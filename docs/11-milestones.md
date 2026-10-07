# 11 · Milestones and tasks

Work one task at a time, in dependency order. Each task lists the specs it relies on, what "done" means and how to verify it. Weeks count from the start (week 1). The **content track (C)** runs in parallel and is led by humans; agents draft and check.

**`[owner]`** marks a task, or the part of a task, that needs a person: signing, real devices, iCloud accounts, testers, App Store Connect or human judgement. The agent does everything up to that point, meets the **proxy** criterion given (a fake, a simulator, a script), lists what is left for the owner in `PROGRESS.md`, and stops. The owner records the result there.

## Gates

| Gate | Week | Passes when | Owner |
|---|---|---|---|
| **G0 Harness** | 1 | An agent can build (unsigned), test and screenshot the app with no human help (M0 done) | agent, verified by owner |
| **G1 Sign-off** | 3 | The content lead approves the syllabus, every unit spec, the grammar points and the story bible (C1) | content lead |
| **G2 Every lesson type works** | 8 | Units 0–1 approved and running complete on iPhone, iPad and Mac; all 20 lesson types usable; 5 testers pass the Unit 1 check | owner |
| **G2b Beta out** | 9 | TestFlight study build with every approved unit (at least Units 0–1) and consented telemetry goes to the beta cohort (15–20); later units follow in new builds as they're approved | owner |
| **G3 Content complete** | 18 | Every unit passes all ten checks; coverage 100% (`coverage_mode: enforce`) | content lead + owner |
| **G4 MVP complete** | 20 | Placement and final check built; sync tested on three devices; TestFlight build out | owner |
| Early signal | 30 | Beta cohort's final check and 30-day test | owner |
| Go / no-go | 39 | Study thresholds (`docs/01`) | owner |

Changes from the plan document:

- Sync work moves from weeks 18–20 to weeks 9–14, while engineering has slack during content production. This de-risks G4; the three-device test still happens at G4.
- Telemetry, the study endpoint and `beta-import` move into M6, because the beta (G2b, week 9) needs them. The review pages and review import move into M1, because sign-off (C1) needs them in week 2; review mode in the app follows in M6.10.

If a task can't meet its criteria, stop and report. If content slips, the unit moves back; nothing ships unreviewed.

**Dependencies in short:** M0 → M1 (pipeline) and M2 (engine) in parallel; M2.1 needs M1.10 (payload fixtures) and M2.3 needs M1.4 (shared pattern fixtures); M3.6 needs M2.7, M2.8, M2.11 and M2.12; M4 needs M3.6; real read-along needs M5.2 and speaking needs M5.3; M6.1 needs C3; M7.2 needs the owner's signing (Q10).

---

## M0 · Harness (week 1) → G0

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M0.1 | **Makefile skeleton** (every target in `docs/10`; unfinished targets print "not yet (task Mx.y)" and exit 0). `Packages/LearningCore` (swift-tools 6.2; no dependencies; iOS/macOS 26 + Linux) and `Packages/Storage` (GRDB **exactly** 7.11.1), one test each. `App/Config/` xcconfig files (Base, Debug, Release, Study with `#include? "Secrets.xcconfig"`) and the two entitlements files, ready for the owner to assign | 02, 10, 13 | LearningCore tests pass on macOS and Linux, Storage tests on macOS; `make lint-guards` passes | `make test-core test-storage lint-guards` |
| M0.2 | **[owner] Create the Xcode project** (ADR-19): Xcode 27 → Multiplatform App "Italiano" in `App/`; iOS, iPadOS and macOS 26.0; synchronized folders; unit and UI test targets; link the local packages to the app target; add swift-snapshot-testing 1.19.6 to the test target; assign the `App/Config` xcconfigs; **delete the files the template generates that the repo already has** (its `ItalianoApp.swift`, `ContentView.swift`, `Assets.xcassets`, `Preview Content` and `.entitlements` file: the app's `@main`, resources and entitlements live in `App/Italiano/AppMain`, `App/Italiano/Resources` and `App/Config`); commit the shared scheme `Italiano` | 02, 13 | the project opens and builds in Xcode with no team selected | owner, in Xcode |
| M0.3 | App skeleton: Swift 6 language mode and complete strict concurrency (xcconfig), bundle ID `com.j23n.italian` (ADR-18) in `Base.xcconfig`, `Italiano-NoCloud.entitlements` for agent builds, fonts registered at launch, a `TabView` with 4 empty tabs (`tab.today`, `tab.course`, `tab.words`, `tab.settings`) | 02, 07 | builds unsigned and launches on iPhone and iPad simulators and on Mac | `make build-ios build-mac`; MobileBuildMCP `build_run_sim` + `screenshot` → `artifacts/screens/M0.3/` |
| M0.4 | `pipeline/`: uv project, package `itcontent`, typer CLI `content` with `lint` limited for now to YAML parsing (ruamel.yaml, YAML 1.2) and ID format; pytest, ruff; `make data` downloads Morph-it! and FrequencyWords with pinned SHA-256s into `pipeline/data/` (gitignored), licence files kept | 04 | `content lint` passes on the seed content | `make test-pipeline`; `uv run content lint` |
| M0.5 | CI: adapt `.github/workflows/ci.yml` (steps guarded until their tools exist; unsigned builds; pinned Swift) and `claude-review.yml`. **[owner]** push the branch and open a PR (pushing needs approval and GitHub access) | 10 | CI green on the PR | proxy: `make ci` passes locally; owner: both jobs green |
| M0.6 | Harness check: hooks block an edit to `fixtures/fsrs/` and to a file marked approved, **also from a worktree**; the Bash hook blocks `content approve`; the Stop hook runs the relevant checks on the branch's committed and uncommitted changes; `.worktreeinclude` copies `pipeline/data`; MobileBuildMCP tools are listed; `PROGRESS.md` records pinned versions (Xcode, Swift, GRDB, swift-snapshot-testing, MobileBuildMCP, Python, uv, simulator runtime) | 10 | evidence in `PROGRESS.md` | as described |

## M1 · Content model and pack (weeks 1–3; needs M0.4)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M1.1 | JSON Schemas for every YAML type (course, syllabus, grammar points, detection rules, items, story bible, voices, countries, allowlist, disambiguation, pronunciation, checker, unit, lesson, task, check, assessments) and for review files and ledgers; `lint` loads them | 03, 06 | all seed files validate; `pipeline/tests/fixtures/invalid/*` fail with messages that name the file, path and problem | `make test-pipeline` |
| M1.2 | IDs: format (incl. generated and unit-level IDs), uniqueness, collisions, references, `ids.lock` (release builds only), `retired.yaml`; `content approve` / `reopen` with the approval hash checked by `lint`; both refuse without a TTY or with `CLAUDECODE` set | 03, 04, 13 | tests for each rule; approving a file and editing it makes `lint` fail; `CLAUDECODE=1 uv run content approve …` exits non-zero | `make test-pipeline` |
| M1.3 | **Review pages** (`content review-export --specs` and `--unit`): one self-contained HTML file per scope with every element of `docs/04` § Content review loop: accepted answers expanded, near-misses, verdict, category, comment and suggestion per element, autosave in the browser, **Download my review**, **Sign off** with file hashes (audio players come in M5.1) | 04 | **[owner]** the content lead reviews the C1 files on the page and sends back a review file; proxy: snapshot tests of the page, and a scripted browser test (Playwright, dev dependency; skipped where no browser is installed) that comments, downloads and signs off | `make test-pipeline`; `uv run content review-export --specs` |
| M1.4 | Answer-pattern parser, expander (expansion order, 512 cap) and normaliser in Python; shared fixtures `fixtures/grading/normalizer.json` and `patterns.json` | 03, 05 | fixtures pass | `make test-pipeline` |
| M1.5 | Morph-it! loader (encoding → UTF-8 NFC), elision table, tokeniser (case-sensitive names, foreign words, numbers) | 04 | tests for elision, names (*Rosa* vs *rosa*), foreign words, digits | `make test-pipeline` |
| M1.6 | Chunk matcher (`case_sensitive`), item resolution (surface forms first, the lexical-article rule), `disambiguation.yaml` conditions, `annotate` and `annotate --check` with lock files; `make annotate` | 04 | the golden lesson, task and check annotate with no unknown tokens; ambiguity errors name the line and candidates | `make annotate`; `uv run content annotate --check` |
| M1.7 | Grammar detection and morphology unlocks from `content/grammar/detection.yaml`; rules for every point in Units 0–3 first (later units as content arrives) | 03, 04 | one passing and one failing test per implemented point; invariable nouns never count as plurals | `make test-pipeline` |
| M1.8 | Checks 2 (level gate, incl. titles exempt, `recognise`, chunk-exempt production gate), 4 (alignment) and 5 (register matrix with precedence and switch points), with `check.json` and `check.md` reports | 04 | the golden lesson passes; mutations fail with precise messages (adding *abbiamo mangiato* to the Unit 2 story fails the construction gate; a `tu` line from Giulia to Marco in Unit 2 fails check 5) | `make check-content` |
| M1.9 | Pack builder core from `schemas/content-pack.sql`: units, lessons, texts, tokens, items, step and exercise payloads (lesson and unit-level steps, `docs/06`), dev vs release mode, missing-audio warnings, pack hash rules | 03, 04, 06 | pack builds; `pack-hash` identical across two runs and unaffected by `git_sha` | `make pack` twice |
| M1.10 | Requirements (§ Requirements), introductions, scheduled flags, `note_items`, `assessments`, generated preview exercises; `make mini-pack` → `fixtures/packs/mini.sqlite` and `mini-payloads.json` (no audio yet) | 04, 05, 06 | mini pack committed; every requirement row of the golden lesson matches a hand-checked expectation file | `make mini-pack`; `make test-pipeline` |
| M1.11 | Checks 1 (coverage) and 3 (recycling and balance) with the partial-content rules; `content report`. `checker.yaml: coverage_mode: report` until G3, then `enforce` | 04 | coverage report lists every syllabus entry with its three locations; incomplete units are `pending`; `make check-content` passes with only the golden lesson written | `uv run content check --json` |
| M1.12 | `content freq` and `content suggest --topic --unit` (frequency ranks, high-frequency candidates not yet in items) | 04 | tests with a small frequency fixture | `make test-pipeline` |
| M1.13 | **Review import and ledger:** `content review-import` (inbox copy, target checks, stale detection, ledger `reviews/<scope>.yaml`), `--since` re-export with resolutions and change marks, `content approve --signoff` (no open comments, hashes match), open comments in `content report`; the `content-review` skill's procedure works end to end on a fixture review | 04 | importing `pipeline/tests/fixtures/review-u02.json` creates the ledger; approving with a stale sign-off fails | `make test-pipeline` |

## M2 · Learning engine (weeks 2–4; LearningCore and Storage)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M2.1 | Typed IDs, content types, payload `Codable`s for every step kind and format (needs M1.10) | 03, 06 | every payload in `fixtures/packs/mini-payloads.json` decodes; unknown keys ignored; a missing required key fails | `make test-core` |
| M2.2 | FSRS-6 | 05 | all scenarios in `fixtures/fsrs/fsrs6-reference.json` pass (relative tolerance 1e-9, exact due dates); `roundHalfEven` unit test | `make test-core` |
| M2.3 | `Normalizer` and `AnswerPattern` (parser, expansion, focus spans), at parity with M1.4 | 03, 05 | `normalizer.json` and `patterns.json` pass | `make test-core` |
| M2.4 | Typed-answer grader and dictation grader | 05 | `typed-answers.json` and `dictation.json` pass | `make test-core` |
| M2.5 | Choice, order, content-point and English-answer graders; `ItalianNumbers` (0–9999, prices, times); `TranscriptMatcher` | 05 | `transcripts.json` passes; number cases for prices and times | `make test-core` |
| M2.6 | `FeedbackMachine`, `RatingPolicy` | 05 | every transition and every rating row tested (incl. spoken fail → no update, skipped → none) | `make test-core` |
| M2.7 | Events, `Replay` reducer, `LearnerState`, merge rules, derived resume cursor, rebuild triggers | 05, 08 | 1,000 seeded runs with shuffled delivery and duplicates give identical states; incremental equals full rebuild | `make test-core` |
| M2.8 | Introductions (incl. grammar-point rule and `catchup`), eligibility, unit progression | 05 | tests include placement-introduced items and a missing introduction (mini-preview signal) | `make test-core` |
| M2.9 | `Planner`, `ReviewSessionBuilder`, `CardSelector` (generated `gen:` cards), `Interleaver` | 05, 06 | a 60-day simulated learner never sees ineligible content; caps, focus-first ordering and interleaving constraints hold | `make test-core` |
| M2.10 | Check scoring (half credit for `almost`, best-score retakes), can-do status, placement algorithm, progress metrics | 05, 06 | rule tests from `docs/05` | `make test-core` |
| M2.11 | Storage: `PackReader` (read-only `DatabaseQueue`, schema check, all queries) | 02, 03 | every payload in `mini.sqlite` decodes through `PackReader` | `make test-storage` |
| M2.12 | Storage: `LearnerStore` (migrations; append + derive + `sync_pending` in one transaction; replay driver; settings; `telemetry_sent`) | 02, 03, 08 | Storage tests pass; 50,000 synthetic events rebuild in < 1.5 s on an M-series Mac (device check in M9) | `make test-storage` |

## M3 · App shell and design system (weeks 3–5)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M3.1 | `DesignSystem`: tokens (light and dark), fonts registered at runtime, text scale, every component in `docs/07` | 07 | snapshot matrix (`docs/07`); `scripts/check-contrast.py` passes | `make test-app`; `make lint-guards` |
| M3.2 | `Mascot` view and Moka assets (4 poses); `ItalianText` speech language checked per token | 07, 13 | snapshots; VoiceOver label; finding on `accessibilitySpeechLanguage` recorded in `PROGRESS.md` | `make test-app` |
| M3.3 | `AppDependencies`, `AppConfig` (incl. `ITA_SYNC_ENABLED`), Debug menu with every item in `docs/02` and the `-ITAJumpToUnit` launch argument | 02 | builds in Debug, Release and Study; the Debug menu appears only in Debug | `make build-ios build-mac` |
| M3.4 | Onboarding (all screens, settings writes, `onboardingCompleted`; placement entry stubbed) | 05, 07, 08 | UI test completes onboarding on iPhone and Mac; screenshots compared by ui-reviewer | `make test-ui` |
| M3.5 | Today, Course (Indice), Unit overview, wired to `Planner` and `PackReader` | 05, 07 | screenshots match references in layout; VoiceOver order; AX5 | `make test-ui`, screenshots |
| M3.6 | Lesson player framework: step routing, progress, derived resume, close, eligibility guard with mini-preview, step events, `session` events (with `platform`) | 05, 06 | UI test: launch with `-ITAJumpToUnit u02`, start Unit 2 Lesson 1, quit mid-step, relaunch, resume at the same exercise | `make test-ui` |
| M3.7 | Words (list or table, filters, search, skill bars) | 05, 07 | screenshots on iPhone, iPad and Mac | `make test-app` |
| M3.8 | Settings (every setting in `docs/08`, text size, research section, Acknowledgements from `docs/13`'s licence table incl. OFL texts); the macOS `Settings` scene and the Lesson and View menus | 07, 08, 12 | settings persist; menus and shortcuts work (⇧⌘H, ⌘L, ⌘+/⌘−/⌘0); acknowledgements complete | `make test-app`; Mac UI test |
| M3.9 | Error states: pack-mismatch screen, learner-DB recovery (backup, fresh DB, rebuild) | 02 | tests with a pack of the wrong schema version and a corrupt learner DB | `make test-app` |
| M3.10 | Local reminders (`NotificationScheduling`): `reminder.enabled`, `reminder.time`; permission asked only when the learner turns reminders on | 02, 08 | fake scheduler tests; **[owner]** a reminder arrives on a device | `make test-app` |

## M4 · Lesson types (weeks 4–8). Use the `add-exercise-format` skill for each

| ID | Task | Specs | Done when (beyond the per-type criteria in `docs/06`) | Verify |
|---|---|---|---|---|
| M4.1 | Answer input, accent keys, Check, hint, `FeedbackPanel`; **cloze** and **recall** (typed) | 05, 06 | golden-lesson cloze and recall items work with stepped feedback on all three platforms; Mac keyboard path | `make test-app test-ui` |
| M4.2 | **Preview** step (meet, match, generated recall and choice) | 05, 06 | the golden preview runs; introductions written at step start | `make test-ui` |
| M4.3 | **Story** step: reader, word panel or sheet, glosses, audio bar, read-along (fake timeline until M5.2), comprehension questions | 06, 09 | the golden story passes its acceptance list (audio parts after M5.2) | `make test-app test-ui` |
| M4.4 | **Grammar note** step | 06 | the golden note renders as in `Grammar.png` | snapshots |
| M4.5 | **Practice** step (block then seeded mix); **sentence building**, **choice**, **true-false**, **match** | 05, 06 | golden practice runs; VoiceOver can complete sentence building | `make test-app test-ui` |
| M4.6 | **Dictation**; **sound pairs** and the sounds step | 05, 06 | golden items work; diff view shows doubling notes | `make test-app` |
| M4.7 | **Listening** step | 06 | transcript hidden until answered; `plays` respected | `make test-app` |
| M4.8 | **Real-world reading** step with every layout type in `docs/06` § 4 | 06 | snapshot per layout type (compact, regular, AX5); tap-to-gloss in every field | `make test-app` |
| M4.9 | **Repeat after me**; **Say it** on recall (needs M5.3) | 05, 06, 09 | proxy: fake recogniser paths (pass, fail, skip, unavailable) in the Simulator; **[owner]** device test on iPhone, iPad and Mac | `make test-app` |
| M4.10 | **Conversation** (typed, then spoken), incl. node-level `register` and `near` | 05, 06 | the Unit 2 task conversation completes typed and spoken (fake recogniser) on both branches; goals tick | `make test-ui` |
| M4.11 | **Talk about it**; **guided writing** (forms and free text) | 05, 06 | points found shown; model answer; forms validate; responses stored | `make test-app` |
| M4.12 | **Relay** | 05, 06 | time, price, number and text answer types tested | `make test-app` |
| M4.13 | **Review session** and **Session complete** | 05, 06 | a review of mini-pack items runs from Today; complete screen as reference | `make test-ui` |
| M4.14 | **Unit check** (check mode, results, mistakes, retake) | 05, 06 | the Unit 2 sample check runs and scores (half credit for `almost`); result screen | `make test-ui` |
| M4.15 | **Opener**, **use** step, **fluency replay** | 06 | unit-level steps run in order; fluency replay logs time | `make test-ui` |

## M5 · Audio and speech (weeks 4–7)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M5.1 | `content tts`: voices, SSML, Azure batch client (recorded responses in tests, no network in CI), WAV cache, alignment, PCM assembly, encode once; rebuild the mini pack with audio; audio players and `audio` comments in the review pages | 04 | the golden lesson renders (owner's key); every token has timings; `--dry-run` prints characters and cost | `make test-pipeline`; **[owner]** `uv run content tts --unit u02` |
| M5.2 | `AudioPlaying`: AVPlayer, rates, segments, read-along observer, audio session, encoder-delay test | 09 | highlight drift < 50 ms in a unit test with a fake clock and in the encoder-delay test; **[owner]** device check | `make test-app` |
| M5.3 | `SpeechRecognizing`: SpeechTranscriber (one transcriber, locale reserved), availability, asset download UI, DictationTranscriber fallback, silence stop, fake; write `fixtures/speech/sentences.txt` (30 sentences) | 09 | proxy: fake and availability states tested; **[owner]** works on iPhone, iPad and Mac for the 30 sentences; permission behaviour recorded in `PROGRESS.md` | `make test-app`; device |
| M5.4 | Audio budget projection; IPA override workflow | 04 | `content report` shows MB per unit; one override demonstrated | `uv run content report` |

## M6 · Units 0–1 vertical slice and beta (weeks 6–9) → G2, G2b

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M6.1 | Integrate approved Units 0–1 (C3) in a release pack; fix what they expose | 04 | `make pack-release` succeeds with Units 0–1 | `make pack-release` |
| M6.2 | App icon (Moka, `docs/07`) and launch screen | 07 | icon present in all three platforms' builds | `make build-ios build-mac`; screenshot |
| M6.3 | Debug "auto-answer" hook; XCUITest completes Unit 0 on iPhone | 06, 10 | passes; screenshots in `artifacts/screens/M6.3/` | `make test-ui` |
| M6.4 | Playthroughs of Units 0–1 on iPhone, iPad and Mac, saving a screenshot of every step kind | 06, 10 | all three pass; screenshots in `artifacts/screens/M6.4/` | `make test-ui` |
| M6.5 | Telemetry uploader: consent screen (text marked `TODO(owner)`), `study.installId`, batches, retry, 4xx handling, `telemetry_sent`, events from the consent date only, local-origin only, delete request | 12 | tests against a mock server; nothing is sent without consent | `make test-app` |
| M6.6 | Reference endpoint in `server/`: study batches (append-only, no IP logging, JSONL export, delete) and review comments (`docs/12`) | 12 | contract tests pass for both routes | `make -C server test` |
| M6.7 | `content beta-import`: item statistics and the rejected-answers report | 04, 12 | tests with a recorded JSONL fixture | `make test-pipeline` |
| M6.8 | **[owner]** Internal TestFlight (owner signs with `make archive CONFIG=Release`, which bundles the release pack; sync off), feedback link in Settings, crash logs via Xcode Organizer (no SDK) | 02, 12 | proxy: release build archives unsigned; owner: 5 testers complete the Unit 1 check (G2) | owner |
| M6.9 | **[owner]** Study build: consent text, telemetry to the real endpoint (`Secrets.xcconfig`), external TestFlight group, `ITA_SYNC_ENABLED = NO` until M7.5 | 12 | beta cohort installs the build (G2b) | owner |
| M6.10 | **Review mode in the app** (`docs/06` § Shared player behaviour): Review build configuration (dev pack, no sync or telemetry), unlocked units with a jump menu, comment sheet, answer key, "This should be accepted", Send and Export of the review file. **[owner]** an internal TestFlight group "Content review" with the teacher | 04, 06, 12 | proxy: UI test files a comment on `u02.l1.ex07` and exports a review file that `content review-import` accepts; owner: the teacher sends a review from the app | `make test-ui`; owner |

## M7 · Sync (weeks 9–14)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M7.1 | Multi-device simulator and merge tests (if not complete in M2.7) | 05, 08 | 1,000 seeded runs converge | `make test-core` |
| M7.2 | `CloudSync` (actor) with CKSyncEngine: zone, record mapping, state persistence, pending changes written with the event, batching, zone deletion, pause | 08 | proxy: the in-memory two-device simulator and a fake engine cover every handler; **[owner]** two signed devices exchange events | `make test-app`; owner |
| M7.3 | Settings last-writer-wins and the Settings sync status row | 08 | status texts as `docs/08`; LWW tested | `make test-app` |
| M7.4 | Account changes: sign in, sign out, switch with archive | 08 | proxy: handler tests with fake account events; **[owner]** manual checklist passes | `make test-app`; owner |
| M7.5 | **[owner]** Deploy the CloudKit schema to production; turn sync on in TestFlight builds | 08 | the next TestFlight build syncs | owner |
| M7.6 | **[owner]** Three-device checklist (`docs/08` § Tests) and a 10,000-event first sync | 08 | results in `PROGRESS.md` | owner |

## M8 · Assessments and QA tools (weeks 10–17)

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M8.1 | Placement flow, algorithm wiring, catch-up queue, "Start from the beginning" | 05, 06 | UI test places a scripted learner at Unit 3; catch-up cards appear | `make test-ui` |
| M8.2 | Final A1 check (speaking always recorded) and the examiner export zip | 05, 06, 09, 12 | export opens in the share sheet with the documented contents | `make test-ui` |
| M8.3 | **Answer adjudication:** answers rejected in the beta (`content beta-import`) appear in the next review page as "Answers to adjudicate" (accept / near-miss with a hint / wrong); `content review-import` turns the verdicts into pattern changes for the agent to apply | 04 | an imported adjudication adds the accepted answer to the pattern after `content reopen` | `make test-pipeline` |
| M8.4 | (Optional) Foundation Models writing hints behind `ITA_LLM_HINTS` | 02, 06 | off in Study and Release builds | `make build-ios build-mac` |

## M9 · Hardening and release (weeks 18–20) → G4

| ID | Task | Specs | Done when | Verify |
|---|---|---|---|---|
| M9.1 | Performance | 02 | proxy: budgets measured in release builds on the Simulator and an M-series Mac; **[owner]** every budget in `docs/02` met on the oldest supported iPhone and iPad, or documented with a plan | tests; owner |
| M9.2 | Accessibility audit: full VoiceOver pass, AX5, Reduce Motion, contrast, keyboard-only Mac | 07 | issues fixed or listed | `make test-ui`; checklist |
| M9.3 | Privacy manifest, acknowledgements, `ITSAppUsesNonExemptEncryption = NO`, App Store metadata draft for the owner | 12 | **[owner]** reviews | owner |
| M9.4 | Release pack with all approved units; `coverage_mode: enforce`; content freeze tag | 04 | `make pack-release` passes with every unit | `make pack-release` |
| M9.5 | **[owner]** Final study TestFlight build; three-device sync test; release checklist | 08, 12 | G4 | owner |

---

## Content track (humans lead; agents draft and check)

| ID | Weeks | Work | Done when |
|---|---|---|---|
| C1 | 1–3 | The content lead reviews `syllabus/a1-syllabus.yaml`, every `units/*/unit.yaml`, `grammar/points.yaml` and `story-bible.yaml`, plus the content questions in `docs/13`, on the review pages (M1.3); agents import each review, apply the comments and re-export until the teacher signs off (`docs/04` § Content review loop), and the owner answers Q2, Q3 and Q12 | all signed off and approved → **G1** |
| C2 | 2–5 | Item graph `items/u00…u12.yaml` drafted by agents (`content suggest`, need then frequency), reviewed with the specs | approved per unit |
| C3 | 3–7 | Units 0 and 1: lessons, tasks, checks drafted → `make annotate` → `make check-content` → critic → review page → teacher's comments → fixes → sign-off → approve → `content tts` → audio review (same loop) | Units 0–1 approved by week 7 |
| C4 | 5–8 | Critic calibration: the content lead rates 20–30 drafts; compare with the critic's verdicts; tune `.claude/agents/content-critic.md`; reviewed drafts become the golden set | agreement recorded in `PROGRESS.md` |
| C5 | 8–18 | Units 2–12 and the final review, in batches of three; the content lead reviews about one unit a week | all approved → **G3** |
| C6 | 12–17 | Placement and final-check items, with the assessment reviewer | approved |
