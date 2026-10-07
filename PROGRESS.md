# Progress log

Append one entry per finished task (newest at the bottom). Agents read the tail of this file at session start.

Template:

```
## YYYY-MM-DD · <task ID> · <short title>
- Changed: <what, in a few bullets>
- Evidence: <test names / counts, screenshot paths, commands run>
- Decisions or findings: <e.g. pinned versions, permission behaviour, surprises in Morph-it! tags>
- Follow-ups: <new questions, proposals added to docs/13>
```

## 2026-10-07 · handoff · Repository seeded from the handoff pack
- Changed: specs (docs/), agent harness (.claude/, .mcp.json, scripts/), content seeds (syllabus, grammar points and detection rules, all unit specs, story bible, items for Units 0–2, golden Unit 2 Lesson 1 with its task and check), fixtures (FSRS-6 reference from py-fsrs 6.3.2; grading), design assets.
- Evidence: no app code yet. Seed YAML parses; every ID reference in the lesson, task and check files resolves (references into units not yet written are pending); the golden story's 106 tokens all resolve to items, chunks or the allowlist; every new P item of the golden lesson has ≥ 4 retrievals; the pack schema loads in SQLite; the hooks were exercised in a scratch repo; `scripts/check-contrast.py` passes.
- Decisions or findings: see docs/13 (bundle ID com.j23n.italian in ADR-18; the owner has an Italian teacher as content lead, Q1; ADR-19 to ADR-22, incl. the content review loop, and the content questions came out of two independent AI-agent reviews of the pack, engineering and Italian L2 content, plus a consistency check). Versions checked 7 Oct 2026: Xcode 27.0 (Swift 6.4), GRDB 7.11.1, swift-snapshot-testing 1.19.6, MobileBuildMCP 2.7.1, py-fsrs 6.3.2.
- Follow-ups: start with M0.1; the owner creates the Xcode project at M0.2.

## 2026-10-07 · M0.1 · Makefile skeleton, packages, App config
- Changed: `Makefile` with every docs/10 target (app targets print "not yet (task M0.2…)" until the owner's Xcode project exists); `Packages/LearningCore` (swift-tools 6.2, Foundation only; Clock, LocalDay with the 04:00 rollover, FNV-1a 64, SplitMix64, seeded shuffle, UUIDSource, CoreLogger) and `Packages/Storage` (GRDB exactly 7.11.1); `App/Config/` Base, Debug, Release, Study and Review xcconfigs (`#include?` of the gitignored Secrets.xcconfig and Signing.xcconfig), `Italiano-Info.plist` with the `ITA_*` keys, both entitlements files.
- Evidence: `make test-core` (SupportTests: FNV-1a and SplitMix64 published vectors, seeded shuffle, local days, seeded UUIDs), `make test-storage` (GRDB opens SQLite) on Linux, `make lint-guards` green.
- Decisions or findings: Swift 6.4.0 from the official image `swift:6.4.0-noble` (download.swift.org is blocked from cloud sessions; the Docker Hub layers were pulled and their digest verified). **GRDB 7.11.1 builds and passes on Linux** (needs `libsqlite3-dev`), so Storage tests run in Linux CI too; macOS remains the reference.
- Follow-ups: owner M0.2 (Xcode project; see the clean-up step now in docs/11).

## 2026-10-07 · M0.4 · pipeline skeleton and `make data`
- Changed: `pipeline/` uv project `itcontent` with the typer CLI `content` (`lint`: YAML 1.2 parse + ID formats), shared loader `itcontent/course.py` (walks lessons, tasks, checks and assessments, with file/path locations for every finding), `make data` → `python -m itcontent.data_fetch`, pins read from `pipeline/data/SOURCES.md`.
- Evidence: `uv run content lint` → 0 errors on the seed content; `make test-pipeline`; `make data` (cached and fresh-download paths both exercised).
- Decisions or findings: **Morph-it! 0.4.8** (`morph-it_048.txt`, the last release; docs/13 said 0.4.7) pinned at sha256 `705da322…fd55fa`. The official host was unreachable from the cloud session, so the hash comes from two independent GitHub mirrors that agree byte for byte; the fetcher tries the official archive first. Real tag facts (categories carry gender, `ART-*` vs `ARTPRE-*`, `spremuta` only as a participle, `c'`/`quant'`, `NPR`, two malformed lines) are recorded in SOURCES.md. FrequencyWords `it_50k.txt` pinned at `bb96cdcb…66fc19`. Versions: Python 3.13.16 (project requires ≥ 3.12), uv 0.11.32, ruamel.yaml 0.19.1, jsonschema 4.26.0, pydantic 2.13.5, typer 0.27.3, requests 2.34.2, pytest 9.1.1, ruff 0.16.10, playwright 1.63.0, ffmpeg 6.1.1, git-lfs 3.4.1.

## 2026-10-07 · M0.5 · CI (agent part)
- Changed: `.github/workflows/ci.yml` Linux job pinned to `swift:6.4.0-noble`, adds `libsqlite3-dev`, Storage tests, ruff, and a pack-determinism step (the pack isn't committed any more, see below); `claude-review.yml` header.
- Evidence: every Linux step was run locally (`make lint-guards test-core test-storage test-pipeline`).
- Follow-ups: **[owner]** confirm the macOS runner image name (`macos-26`) and the Xcode 27 path on the first PR run; add the `ANTHROPIC_API_KEY` secret for the review workflow.

## 2026-10-07 · M0.6 · harness check
- Evidence: the hooks were run directly with simulated tool inputs, in a checkout and in a git worktree: protect-paths blocks edits to `fixtures/fsrs/`, to a file with `review.status: approved`, and any write that sets `status: approved`, and allows ordinary content edits; guard-bash blocks `uv run content approve …`, `sed -i` on approved content and redirection into `fixtures/fsrs/`, and allows `git commit -m 'content approve flow'` and reads; the Stop hook runs the checks for committed, uncommitted and untracked changes, reports failures with exit 2, and lets the turn end when `stop_hook_active` is true. MobileBuildMCP 2.7.1 starts (`npx -y mobilebuildmcp@2.7.1 mcp`) and lists 49 tools (build_sim, build_run_sim, snapshot_ui, tap, type_text, screenshot, test_macos, swift_package_test …). `.worktreeinclude` is honoured by `claude --worktree`, not by every agent-worktree mechanism: copy `pipeline/data` or run `make data` in a new worktree.
- Pinned versions: Swift 6.4.0 (Linux toolchain; Xcode 27's Swift 6.4), GRDB 7.11.1, MobileBuildMCP 2.7.1, Python/uv as in M0.4. **[owner]** Xcode 27 build number, swift-snapshot-testing 1.19.6 (added to the test target in M0.2) and the simulator runtime.

## 2026-10-07 · M2.2 · FSRS-6
- Changed: `FSRS/FSRS6.swift` (MemoryState, review, retrievability, roundHalfEven, interval clamping), shared model types (typed IDs, Skill, ItemStatus, StepKind, ExerciseFormat with families, AttemptOutcome, FSRSRating…), `Learner/RatingPolicy.swift`.
- Evidence: FSRS6Tests — all 35 scenarios / 317 reviews of `fixtures/fsrs/fsrs6-reference.json` at relative tolerance 1e-9 with exact due dates; roundHalfEven; clamps; reps and lapses. RatingPolicyTests — every docs/05 row (incl. spoken fail → no update, skipped → none, second attempts → none, task formats → none however answered).
- Decisions or findings: the same-day stability floor applies for every rating ≥ Hard, as docs/05 says (the fixture confirms it: a same-day Hard keeps stability).

## 2026-10-07 · M6.6 · reference endpoint
- Changed: `server/` (standard library only): study batches, install deletion, review comments, owner-only JSONL exports; no IP logging; append-only storage; idempotent by event and comment ID.
- Evidence: `make -C server test` — 10 contract tests.
- Decisions or findings: added `GET /v1/export/events` (owner token) as the "export to JSONL" docs/12 asks for; one JSONL line per event: `{installId, app, receivedAt, event}`, the input of `content beta-import`.

## 2026-10-07 · M6.7 · `content beta-import`
- Changed: `itcontent/beta.py` and the command: first-attempt statistics per item+skill and per exercise (error rate, median latency, skips), gloss taps, rejected typed answers grouped by exercise and conversation turn → `build/reports/beta/{items,rejected}.{md,json}`, outliers first.
- Evidence: `pipeline/tests/test_beta_import.py` on the recorded fixture `pipeline/tests/fixtures/beta/events.jsonl` (dedupe, first attempts only, placement excluded from statistics, determinism, CLI).

## 2026-10-07 · handoff fixes · issues found in the handoff and fixed (owner asked for better solutions over the letter of the handoff)
- **The bundled pack is a build output, not a commit.** The handoff committed `content.sqlite` and the encoded audio through Git LFS and failed CI when they went stale. Both are deterministic outputs of `content/` and the TTS cache, so they're gitignored; `make bootstrap`/`make pack` build them, the app targets build the pack when it's missing, and CI checks determinism (two builds, one hash). Only the paid TTS renders stay in LFS, cached as FLAC (lossless, ~half of WAV). docs/02, docs/04, docs/10 updated.
- **The mini pack is plain Git.** A few KB, and Linux CI checks out without LFS.
- **Storage tests run everywhere** (`make test`, `make ci`, Linux CI), since GRDB works on Linux.
- **macOS sandbox capabilities are build settings** (`ENABLE_APP_SANDBOX`, `ENABLE_RESOURCE_ACCESS_AUDIO_INPUT`, `ENABLE_OUTGOING_NETWORK_CONNECTIONS`, `ENABLE_USER_SELECTED_FILES`, macOS SDK only), so the entitlements files carry no macOS-only keys into iOS signing. **[owner]** at the first signed build, check the macOS push key (`com.apple.developer.aps-environment`).
- **M0.2 clean-up step:** the Multiplatform template generates its own `@main`, ContentView, asset catalog and entitlements, which would collide with the repo's; docs/11 now says to delete them.
- **`display.textScale` is a device setting** (docs/08): a phone and a Mac need different text sizes.
- **Design tokens are generated** (`scripts/gen-tokens.py`) and `make lint-guards` fails when `Tokens.swift` drifts from `design/tokens.json`.
- **App logic is compiled and tested on Linux:** `scripts/check-app-logic.sh` builds every App file that imports only Foundation, Observation, LearningCore and Storage (and runs the matching App tests with `--test`), so view models, adapters' fakes, telemetry and review-mode logic don't wait for a Mac.
- Incident: the agent tool's worktree isolation created every parallel worker's worktree from the repository's original default branch, not from `italiano`. Each worker noticed within its first commands and moved to a branch made from `italiano`, but before that each listed that checkout's top-level names and recent commit subjects, and two (the learner-engine and lint workers) printed its `CLAUDE.md` (the same file this session was given automatically at start-up). Their code was written only from the `italiano` files; the annotation worker was stopped anyway, its worktree deleted and its task redone. From then on every worktree is created explicitly from `italiano` (`git worktree add … italiano`), never by the tool's isolation option.
