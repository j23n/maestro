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

- `fixtures/fsrs/` is generated from py-fsrs and never edited by hand.
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
make project         # xcodegen generate --spec project.yml → Italiano.xcodeproj (gitignored; the app targets run it)
make signing TEAM=…  # [owner] the team, in the gitignored Signing.xcconfig
make build-number    # the build number the next build gets: the number of commits
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
make app-archive CONFIG=Study   # [owner] pack-release, swap the release pack into the bundle, xcodebuild archive with
                     #   the owner's signing, restore the dev pack on exit (trap); never run by agents
make ci-linux        # what CI's Linux job runs: lint-guards, data, the fast suite (make test) and the pipeline's ruff checks
make ci-macos        # what CI's macOS job runs: Storage, the dev pack built twice (pack-determinism), build, test-app
make ci              # ci-linux, then on a Mac build and test-app
```

`project`, `build`, `build-ios`, `build-mac`, `test-app`, `signing` (the owner's), `build-number`, `update-apple-ci`, `archive` and `testflight` come from `.apple-ci/apple.mk`, a copy of the rules every j23n app shares (j23n/apple-ci's build contract; `make update-apple-ci` refreshes it, never edit it by hand); the Makefile sets what differs (the pack built first, both platforms' tests, the UI tests skipped, ad-hoc signing with `Italiano-NoCloud.entitlements`). Its `archive` and `testflight` stop with a message, because they would bundle the dev pack; `make app-archive` is this app's archive. `IOS_SIMULATOR ?= iPhone 17` and `IPAD_SIM ?= iPad Air 11-inch (M3)` are overridable. At M0, check the names your Xcode actually offers (`xcrun simctl list devicetypes`) and update the defaults. **Signing:** iOS builds and simulator tests run with `CODE_SIGNING_ALLOWED=NO`; macOS test runs that need a signed runner use ad-hoc "Sign to Run Locally" (`CODE_SIGN_IDENTITY=-`, no team) with `Italiano-NoCloud.entitlements` (`docs/02`). Signing with a team is the owner's alone; when something can't build without it, the agent stops and asks.

## CI (`.github/workflows/ci.yml`)

The jobs are j23n/apple-ci's shared workflows, which every j23n app's CI calls; each runs one `make` command. maestro is private and the owner's plan is GitHub Free: its included minutes count a macOS minute ten times and round every job up to a whole minute. So the Linux job runs on every push to any branch, the Mac jobs only on pushes to `main`, by hand (`workflow_dispatch`), and on a pull request once it's labeled `ci:mac`, and a Mac job that doesn't apply is skipped by its `if:`, which starts no runner (docs/13 § Implementation decisions, "CI on a free plan"). The label is the review's call: `claude-review` adds it when its verdict is pass and the diff touches what only the Mac builds, which runs the Mac jobs once on the pull request's merge with `main` at that moment; the owner can add it too. A later push doesn't run them again until the label is added anew. A pull request starts a CI run of its own only when it's labeled, and only `ci:mac` runs a job in it: a branch's commits are tested by their pushes, so each commit runs once.

- **`linux` job (ubuntu), `make ci-linux`, on every push:**
  - The Swift toolchain **pinned to the same version as Xcode 27's** (Swift 6.4.0, the official `swift:6.4.0-noble` image from Amazon ECR Public's mirror, since Docker Hub's pull limit failed the job), so "no new warnings" means the same thing on both.
  - `make lint-guards`, `make data`, then the fast suite, `make test` (LearningCore, Storage, the pipeline's tests, `make check-content` and the App logic), and the pipeline's ruff check and format check (`make lint-pipeline`).
  - A pull request from a branch of this repository skips it, since the push already ran it, so the pull request's merge result isn't tested on Linux, only its branch's last commit (GitHub Free has no required checks for a private repository anyway). A pull request from a fork has no push here, so it runs it only when it's labeled. Tags don't run it.
- **`macos-xcode-26` job, `make pack-determinism build` with the newest Xcode 26, until the hosted runners have Xcode 27:** the dev pack built twice (the pack isn't committed, `docs/04` § Pack build, and two builds must give the same `content pack-hash`), and the app for the iOS Simulator and the Mac (unsigned), the only compiler check of the Apple-only code. The app's tests don't build with Xcode 26, since they rely on Swift 6.4 (`ReviewModeTests` names a local `review` after the `review()` it calls inside `#require`).
- **`macos` job, `make ci-macos` with Xcode 27 (ADR-01), once the repository variable `HOSTED_XCODE_27` is `true`:** `make test-storage`, the dev pack built twice, `make build` and `make test-app` (the app's unit and snapshot tests). When apple-ci's *Runner inventory* workflow shows Xcode 27 on the hosted macOS runners, the owner sets the variable (Settings › Secrets and variables › Actions › Variables), which also turns `macos-xcode-26` off. `xcode-missing: skip` still lets the job pass with a note if a runner lacks Xcode 27.
- **`claude-review` workflow:** `anthropics/claude-code-action@v1` on pull requests. It reviews the diff against the task's spec and acceptance criteria and posts findings as PR comments; it never pushes. Only `[blocking]` findings fail a review: a bug a realistic input triggers in behavior the specs, the task or the description define; an acceptance criterion not met or without evidence; or a broken hard rule. A case the specs don't decide is a `[question]` for the owner, even when the pull request picked a behavior; anything else is `[minor]`. A newer push cancels a review in progress, and a re-review checks the earlier blocking findings and what changed since the commit its last summary names, in the pull request's own files (`git diff`, whose `--output` could write a file: a risk accepted for pull requests from the owner and Claude); after three reviews with blocking findings in one feature, it reports further edge cases there as questions for the owner. When its verdict is pass and the change needs the Mac's build, it adds the `ci:mac` label, which starts the Mac jobs (it may run `gh pr edit` for that). It needs the Claude GitHub App installed on the repo and the `CLAUDE_CODE_OAUTH_TOKEN` secret (from `claude setup-token`), and its `claude_args` grant only the comment and diff tools (and set the model and `--effort high`, as in `claude`).
- **`claude` workflow:** `anthropics/claude-code-action@v1` on issues, comments and reviews that mention `@claude` from someone with write access (other comments start no runner, so it costs Linux minutes only when asked). Claude works on a `claude/…` branch, follows `CLAUDE.md` (a change to more than 3 files gets a plan in the issue first) and opens the pull request itself (`gh pr create` in its `claude_args`, which also set the model and `--effort`); CI and `claude-review` then run on that pull request. Before changing code it reads the open issues and pull requests (the read-only `gh issue` and `gh pr` commands). A change too big for one review goes up as a stack of pull requests, and an issue that needs an open pull request builds on top of it (`.apple-ci/claude/apps.md`, "Stacks"): the workflow installs `gh stack` (github/gh-stack, pinned), and `claude_args` allow `git switch` and the `gh stack` commands that build a stack, but not `merge`, `unstack` or `sync`. Checkout doesn't persist `GITHUB_TOKEN`, so Claude's pushes go out as claude[bot] and start CI. Both Claude workflows stop after 60 minutes and leave `.mcp.json`'s MobileBuildMCP out (`--strict-mcp-config`; it needs Xcode). Work from an issue has no task ID (CLAUDE.md, "Work from a GitHub issue"), and `claude-review` then reviews against the issue. An issue also starts it when it's labeled `ready` (the action's `label_trigger`): Claude takes the issue's text as the request, and the workflow takes `needs refinement` off the issue. Feedback the owner approves in j23n/feedback is filed here labeled `needs refinement` and waits for that label (ADR-23). It needs the Claude GitHub App and the `CLAUDE_CODE_OAUTH_TOKEN` secret (from `claude setup-token`).

## Agent harness (already in this repo)

| Piece | File | Purpose |
|---|---|---|
| Memory | `CLAUDE.md` | commands, hard rules, workflow (short on purpose), after j23n's shared rules, which it imports from `.apple-ci/claude/` (`j23n.md` for every j23n repository, `apps.md` for the apps; copies from j23n/apple-ci, refreshed by `make update-apple-ci`) |
| Subagent | `.claude/agents/spec-reviewer.md` | a fresh-context reviewer (read-only) |
| MCP | `.mcp.json` | MobileBuildMCP 2.7.1 (`npx -y mobilebuildmcp@2.7.1 mcp`), workflows `simulator,ui-automation,macos,swift-package,session-management,project-discovery` |
| Worktrees | `.worktreeinclude` | copies `pipeline/data/**` into new worktrees, so content checks work there |
| Formatting | `.swift-format` | 4-space indent, line length 120 (`swift format` reads it) |

**Optional Xcode tools:** Xcode 26.3+ can expose its own MCP tools to external agents. Turn on Xcode → Settings → Intelligence → "Allow external agents to use Xcode tools", then run `claude mcp add --transport stdio xcode -- xcrun mcpbridge` (local scope, not committed; the project must be open in Xcode). Use it for previews and documentation search; builds and tests still go through `make`.

## Working practices for agent sessions

- **One task per session and per branch** (`docs/11` task IDs). Start with `claude --permission-mode plan` for anything touching more than 3 files, and get the plan approved.
- **Parallel work:** use `claude --worktree <task-id>` for independent areas (LearningCore, pipeline, App UI, content). Never run two sessions on the same module. `.claude/worktrees/` is gitignored.
- **Order:** tests from the acceptance criteria first, then code, then the task's **Verify** commands, then screenshots for UI.
- **Before finishing:** for a change to what the specs define (not CI, workflows or other tooling), run the spec-reviewer subagent on the diff; fix or answer each blocking finding, put its questions under Proposed changes in `docs/13` (minors are optional), and run it again with the blocking findings if you changed code for them; update `PROGRESS.md`.
- **When stuck:** after two failed attempts at the same problem, stop and write down what you tried. Don't loosen a test to make it pass; if a test seems wrong, say why and ask.
- **Headless batch runs** (content drafting, migrations): `claude -p "<task>" --output-format json --max-turns 40 --permission-mode acceptEdits --allowedTools "Bash(make annotate),Bash(make check-content),Bash(uv run content annotate:*),Bash(uv run content check:*)"`, one run per file, each in its own worktree. No settings file allows commands, so the run names the ones it may use; add others a task needs.

## Definition of done (every task)

1. The task's acceptance criteria are met and each one is demonstrated by a test or a screenshot.
2. `make test` and `make lint-guards` pass. On macOS, `make build-ios build-mac test-app` pass for any App change. Tasks marked `[owner]` in `docs/11` also need the owner's sign-off in `PROGRESS.md`.
3. No new warnings in Swift (strict concurrency included) or ruff.
4. Accessibility identifiers and labels are present for new UI. VoiceOver order checked on one screen per task.
5. Docs are updated if behaviour or a format changed (the same PR changes the spec, the code and the fixtures).
6. The spec-reviewer subagent finds no blocking issue (a change only to CI, workflows or other tooling skips it).
7. `PROGRESS.md` has an entry: date, task ID, what changed, evidence (test names, screenshot paths), follow-ups.
