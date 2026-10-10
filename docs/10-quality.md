# 10 · Testing, tooling and definition of done

The rule that makes agent work reliable: **every task ends with checks you can run, and evidence a person can look at.**

## Test layers

| Layer | Framework | Runs on | Command | What it covers |
|---|---|---|---|---|
| LearningCore unit | Swift Testing | Linux and macOS | `make test-core` | FSRS fixtures, graders and normaliser fixtures, pattern expansion, feedback machine, rating policy, replay, eligibility, planner, check scoring, placement, merge rules, multi-device simulation, payload decoding from `fixtures/packs/mini-payloads.json` |
| Storage | Swift Testing | Linux and macOS (macOS is the reference: GRDB's Linux support is community-maintained) | `make test-storage` | migrations, pack reader against a pack built at test time from `schemas/content-pack.sql` and `fixtures/packs/payload-examples.json` and against `fixtures/packs/mini.sqlite` once it exists (every payload decodes, every reference resolves), event append + derived updates + `sync_pending` in one transaction (with injected failures), incremental replay = full rebuild, `fixtures/replay/*.json` through the store, settings scopes and last-writer-wins, telemetry bookkeeping, learner-DB recovery from damaged files, a 50,000-event rebuild timing |
| Pipeline | pytest | Linux and macOS | `make test-pipeline` | tokeniser, elision table, Morph-it! loader, chunk matcher, detection rules (one test per grammar point), each check (1–5) with passing and failing fixtures, pattern expansion parity with Swift, pack build determinism. Tests that pin facts about a course run on the frozen seed course `fixtures/seed-course/` (or a copy of it), so they don't change as lessons are drafted; only tests about the live course (it lints and checks without errors, its lock files are fresh, its review pages resolve, its dev pack builds deterministically) read `content/` |
| Content | `content` CLI | Linux and macOS | `make check-content` | lint, annotation freshness, checks 1–5 on the real course |
| App unit and snapshot | Swift Testing + swift-snapshot-testing | macOS (iOS Simulator + Mac) | `make test-app` | view models with fakes; snapshots of components and exercise views (compact and regular, light and dark, AX5) |
| UI flows | XCUITest | iOS Simulator, macOS | `make test-ui` | onboarding → Today → Unit 2 Lesson 1 complete; review session; unit check; Mac keyboard path; the Mac player fills the window; resume after quitting (M3.6); Unit 0 complete on iPhone (M6.3). Each test launches with its own throwaway learner database and the Debug auto-answer bar (`docs/02` § App configuration); shared helpers in `ItalianoUITests/UITestSupport.swift` |
| Agent visual check | MobileBuildMCP | iOS Simulator | via MCP tools | screenshots of the screen you changed, compared with `design/screens/` |
| Manual device | checklist | iPhone, iPad, Mac | `docs/11` gates | audio, speech, sync, feel |

**Fixture policy:**

- `fixtures/fsrs/` is generated from py-fsrs and never edited by hand; a hook blocks it.
- `fixtures/grading/` grows with every grader bug.
- Each fixture file names the spec section it encodes. Where a fixture is more specific than the prose, the fixture wins and the prose is updated in the same change.
- SwiftPM can't bundle files outside a package, so tests load repo-root fixtures through a path built from `#filePath`.

## Makefile targets

M0.1 creates a skeleton whose targets print "not yet (task Mx.y)" and exit 0 until their task lands; each later task fills in its targets. macOS ships GNU Make 3.81, so don't use `.ONESHELL`, `!=` or `$(file …)`.

```
make bootstrap       # uv sync, git lfs pull, make data, resolve Swift packages, check tool versions
make data            # download Morph-it! and the frequency list into pipeline/data/ (checksums in SOURCES.md)
make test            # test-core + test-storage + test-pipeline + check-content + test-app-logic
make test-app-logic  # scripts/check-app-logic.sh --test: App view models, fakes and their tests, on any OS
make test-core       # swift test --package-path Packages/LearningCore
make test-storage    # swift test --package-path Packages/Storage
make test-pipeline   # uv run pytest pipeline
make annotate        # uv run content annotate (refresh the lock files after a content edit)
make check-content   # uv run content lint && uv run content annotate --check && uv run content check
make pack            # check-content + content build (dev mode; gitignored, built locally and in CI)
make mini-pack       # uv run content build --mini → fixtures/packs/mini.sqlite + mini-payloads.json (from fixtures/seed-course)
make pack-release    # content build --release --allow-partial → build/release/ (never committed)
make project         # xcodegen generate --spec App/project.yml → App/Italiano.xcodeproj (gitignored; the app targets run it)
make build           # build-ios and build-mac
make build-ios       # xcodebuild -scheme Italiano -destination 'generic/platform=iOS Simulator' build CODE_SIGNING_ALLOWED=NO
make build-mac       # xcodebuild -scheme Italiano -destination 'platform=macOS' build CODE_SIGNING_ALLOWED=NO
make test-app        # xcodebuild test (iPhone simulator, unsigned) + test (macOS, ad-hoc signed), unit and snapshot only
make test-ui         # xcodebuild test -only-testing:ItalianoUITests (iPhone simulator, then macOS ad-hoc signed)
make screenshots     # UI tests that save reference screenshots to artifacts/screens/ (Screenshots: iOS PNGs in
                     #   artifacts/screens/<task>/, TEST_RUNNER_ITA_SCREENS_TASK=M6.4 names the folder;
                     #   MacScreens: XCTAttachments in artifacts/screens/mac.xcresult)
make lint-guards     # scripts/check-core-imports.sh + python3 scripts/check-contrast.py
                     #   + scripts/gen-tokens.py --check (Tokens.swift and the AccentColor and
                     #     LaunchBackground colour sets match design/tokens.json)
                     #   + scripts/check-app-logic.sh (App files importing only Foundation, Observation,
                     #     LearningCore and Storage type-check against the packages, on Linux too)
make archive CONFIG=Study   # [owner] pack-release, swap the release pack into the bundle, xcodebuild archive with
                     #   the owner's signing, restore the dev pack on exit (trap); never run by agents
make ci-linux        # what CI's Linux job runs: lint-guards, the packages, the pipeline (tests and ruff), the content checks
make ci-macos        # what CI's macOS job runs: Storage, the dev pack built twice (pack-determinism), build, test-app
make ci              # ci-linux, then on a Mac build and test-app
```

`project`, `build`, `build-ios`, `build-mac` and `test-app` come from `.apple-ci/apple.mk`, a copy of the rules every j23n app shares (j23n/apple-ci's build contract; `make update-apple-ci` refreshes it, never edit it by hand); the Makefile sets what differs (the pack built first, both platforms' tests, the UI tests skipped, ad-hoc signing with `Italiano-NoCloud.entitlements`). `IOS_SIMULATOR ?= iPhone 17` and `IPAD_SIM ?= iPad Air 11-inch (M3)` are overridable. At M0, check the names your Xcode actually offers (`xcrun simctl list devicetypes`) and update the defaults. **Signing:** iOS builds and simulator tests run with `CODE_SIGNING_ALLOWED=NO`; macOS test runs that need a signed runner use ad-hoc "Sign to Run Locally" (`CODE_SIGN_IDENTITY=-`, no team) with `Italiano-NoCloud.entitlements` (`docs/02`). Signing with a team is the owner's alone; when something can't build without it, the agent stops and asks.

## CI (`.github/workflows/ci.yml`)

Both jobs are j23n/apple-ci's shared workflows, which every j23n app's CI calls; each runs one `make` target. They run on every push and pull request.

- **`linux` job (ubuntu), `make ci-linux`:**
  - The Swift toolchain **pinned to the same version as Xcode 27's** (Swift 6.4.0, the official `swift:6.4.0-noble` image from Amazon ECR Public's mirror, since Docker Hub's pull limit failed the job), so "no new warnings" means the same thing on both: `make test-core`.
  - uv + Python 3.12: `make test-pipeline`, the pipeline's ruff check and format check (`make lint-pipeline`), and `make check-content`.
  - `make lint-guards`.
- **`macos` job, `make ci-macos`:**
  - A macOS 26 runner with the Xcode the job asks for (see docs/13 § Proposed changes on Xcode 27, which the hosted runners don't have yet).
  - `make test-storage`, then the dev pack built twice: the pack isn't committed (`docs/04` § Pack build), and two builds must give the same `content pack-hash` (`make pack-determinism`).
  - `make build test-app`: the app for the iOS Simulator and the Mac (unsigned), and its unit and snapshot tests.
- **`claude-review` workflow:** `anthropics/claude-code-action@v1` on pull requests. It reviews the diff against the task's spec and acceptance criteria and posts findings as PR comments; it never pushes. It needs the Claude GitHub App installed on the repo and the `ANTHROPIC_API_KEY` secret (or `claude_code_oauth_token`), and its `claude_args` grant only the comment and diff tools.

## Agent harness (already in this repo)

| Piece | File | Purpose |
|---|---|---|
| Memory | `CLAUDE.md` | commands, hard rules, workflow (short on purpose) |
| Path rules | `.claude/rules/*.md` | extra rules loaded only when working in `content/`, Swift or `pipeline/` |
| Skills | `.claude/skills/italian-content`, `content-review`, `ios-ui`, `add-exercise-format` | domain know-how loaded on demand |
| Subagents | `.claude/agents/spec-reviewer.md`, `content-critic.md`, `ui-reviewer.md` | fresh-context reviewers (read-only) |
| Hooks | `.claude/settings.json` + `.claude/hooks/*.sh` | block edits to approved content, the teacher's review files (`reviews/inbox/`), licences, fixtures and harness config (also in worktrees); block agents from running `content approve/reopen`; run fast checks on the branch's changes before a turn ends; print recent progress at session start |
| MCP | `.mcp.json` | MobileBuildMCP 2.7.1 (`npx -y mobilebuildmcp@2.7.1 mcp`), workflows `simulator,ui-automation,macos,swift-package,session-management,project-discovery` |
| Worktrees | `.worktreeinclude` | copies `pipeline/data/**` into new worktrees, so content checks work there |
| Formatting | `.swift-format` | 4-space indent, line length 120 (the PostToolUse hook runs `swift format` with it) |

**Optional Xcode tools:** Xcode 26.3+ can expose its own MCP tools to external agents. Turn on Xcode → Settings → Intelligence → "Allow external agents to use Xcode tools", then run `claude mcp add --transport stdio xcode -- xcrun mcpbridge` (local scope, not committed; the project must be open in Xcode). Use it for previews and documentation search; builds and tests still go through `make`.

## Working practices for agent sessions

- **One task per session and per branch** (`docs/11` task IDs). Start with `claude --permission-mode plan` for anything touching more than 3 files, and get the plan approved.
- **Parallel work:** use `claude --worktree <task-id>` for independent areas (LearningCore, pipeline, App UI, content). Never run two sessions on the same module. The hooks find the worktree's own root, and `.claude/worktrees/` is gitignored.
- **Order:** tests from the acceptance criteria first, then code, then the task's **Verify** commands, then screenshots for UI.
- **Before finishing:** run the spec-reviewer subagent on the diff; fix or explain each finding; update `PROGRESS.md`.
- **When stuck:** after two failed attempts at the same problem, stop and write down what you tried. Don't loosen a test to make it pass; if a test seems wrong, say why and ask.
- **Headless batch runs** (content drafting, migrations): `claude -p "<task>" --output-format json --max-turns 40 --permission-mode acceptEdits`, one run per file, each in its own worktree.

## Definition of done (every task)

1. The task's acceptance criteria are met and each one is demonstrated by a test or a screenshot.
2. `make test` and `make lint-guards` pass. On macOS, `make build-ios build-mac test-app` pass for any App change. Tasks marked `[owner]` in `docs/11` also need the owner's sign-off in `PROGRESS.md`.
3. No new warnings in Swift (strict concurrency included) or ruff.
4. Accessibility identifiers and labels are present for new UI. VoiceOver order checked on one screen per task.
5. Docs are updated if behaviour or a format changed (the same PR changes the spec, the code and the fixtures).
6. The spec-reviewer subagent finds no blocking issue.
7. `PROGRESS.md` has an entry: date, task ID, what changed, evidence (test names, screenshot paths), follow-ups.
