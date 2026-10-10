# Italiano: handoff pack for building the MVP with coding agents

This folder is the starting state of the repository. Unzip it into an empty Git repo and point Claude Code at it. It holds everything an agent needs to build the full-A1 MVP from the plan: specs, ordered tasks with acceptance criteria, the agent harness (memory, skills, reviewers, hooks, MCP), seed content with a golden lesson, test fixtures and design assets. There is no app code yet; the agent writes it, starting with task M0.1.

## What's inside

```
CLAUDE.md                    agent memory: commands, hard rules, workflow (short on purpose)
docs/                        the specs (start at docs/README.md); 11-milestones.md is the task list
.claude/settings.json        permissions + hooks (protect approved content and fixtures, block agent approvals,
                             run checks before stopping)
.claude/agents/              spec-reviewer, content-critic, ui-reviewer (read-only reviewers)
.claude/skills/              italian-content, content-review, ios-ui, add-exercise-format
.claude/rules/               extra rules that load only in content/, Swift or pipeline/ folders
.mcp.json                    MobileBuildMCP (build, run, tap and screenshot the app in the Simulator)
content/                     syllabus inventory (116 entries), 76 grammar points (+ detection rules), 14 unit specs,
                             story bible, seed items (Units 0–2), the golden sample (Unit 2, Lesson 1) and its task and check
schemas/content-pack.sql     the normative SQLite schema shared by the Python pipeline and the Swift app
fixtures/                    FSRS-6 reference vectors (from py-fsrs 6.3.2) and grading cases
design/                      tokens, fonts (OFL), Moka SVGs, reference screens, canvas sources
scripts/                     guards: LearningCore imports, colour contrast
.github/workflows/           CI, Claude's pull request review and its @claude replies (docs/10 § CI)
.swift-format, .worktreeinclude, .gitattributes (Git LFS), .gitignore
tools/fixtures/              the FSRS fixture generator
PROGRESS.md                  the running log agents append to
```

## Before the first session (you)

| Need | Why | When |
|---|---|---|
| Apple-silicon Mac on macOS 26.6+, **Xcode 27** | builds for iPhone, iPad and Mac (Xcode 27 runs only on Apple silicon) | day 1 |
| Claude Code; Node 18+ (for MobileBuildMCP via `npx`); `uv`; `git-lfs`; `ffmpeg` | agent, simulator automation, pipeline, audio | day 1 |
| **XcodeGen** (`brew install xcodegen`, 2.46.0+); `make project` generates `App/Italiano.xcodeproj` from `App/project.yml` | the project is generated, never committed or hand-edited (ADR-19) | day 1 |
| GitHub repo with Actions; optionally `ANTHROPIC_API_KEY` as a secret and the Claude GitHub App installed | CI and automated PR review | week 1 |
| Apple Developer Program and your team ID (bundle ID `com.j23n.italian` and container `iCloud.com.j23n.italian` are set, ADR-18) | signing, CloudKit, TestFlight. Agents never sign with a team; you do | before you sign anything (Q10) |
| Azure AI Speech resource (key and endpoint in your shell, never committed) | course audio (a few dollars in total) | week 4 (M5.1) |
| Your Italian teacher (the content lead) and the *Profilo della lingua italiana* | content sign-off and approvals; how they review is under "How the teacher reviews" below | week 1 |

## Start

```bash
unzip italiano-handoff.zip && cd italiano          # the zip's top folder is the repo root
git init -b main && git lfs install && git add -A && git commit -m "Seed from handoff pack"
claude                                              # approve the project MCP server (MobileBuildMCP) when asked
```

If `npx -y mobilebuildmcp@2.7.1 mcp` fails to start, the tool may still be published under its old name: in `.mcp.json` use `xcodebuildmcp@2.7.0` and rename the variables to `XCODEBUILDMCP_ENABLED_WORKFLOWS` and `XCODEBUILDMCP_SENTRY_DISABLED`.

**Kickoff prompt** (first session):

> Read CLAUDE.md, docs/README.md, docs/01-product.md, docs/13-decisions.md and the M0 section of docs/11-milestones.md. Then make a plan for M0.1–M0.6 in plan mode: files you'll create, the commands you'll run to verify each task, and what you need from me (M0.2 is mine: creating the Xcode project). Don't write code until I approve the plan.

**Each later task:**

> Do task M2.2 from docs/11-milestones.md. Read the specs it cites first. Write the tests from the acceptance criteria, implement, run the Verify commands, then run the spec-reviewer subagent and fix what it finds. Finish by appending to PROGRESS.md.

**Parallel work:** run independent tasks in separate worktrees (`claude --worktree M2-fsrs`), never two on the same module. The hooks work inside worktrees, and `.worktreeinclude` copies the pipeline's reference data. LearningCore and pipeline tasks also run in cloud sessions, since both are Linux-tested.

**Content drafting** (from week 3, after sign-off):

> Using the italian-content skill, draft content/units/01-piacere/lesson-1.yaml from its unit spec, the story bible and the golden sample. Run make annotate and make check-content until it passes, then the content-critic subagent, and report open questions for the content lead.

## How the teacher reviews

Your teacher never touches YAML or Git. The full loop is in `docs/04` § Content review loop.

1. **You send a review page.** An agent runs `uv run content review-export --specs` (sign-off, weeks 1–3) or `--unit u02` (each unit) and gives you one HTML file. You send it by email or a shared folder; it opens offline in any browser.
2. **The teacher comments on the page.** Each story line, note, exercise and word has OK / Change / Question buttons, a comment box and a "Suggested Italian" field. Every accepted answer is listed, so missing alternatives are easy to spot. Comments save as they type; **Download my review** gives them a file to send back to you.
3. **You import it.** Run `uv run content review-import review-u02-….json`, or ask an agent to. It files the teacher's comments unchanged and adds them to a per-unit ledger in `reviews/`.
4. **An agent applies the fixes** with the `content-review` skill. It records what it did about each comment (fixed, answered, declined with a reason, or a question for you) and makes the next page, which shows those answers and marks what changed.
5. **Repeat until the teacher signs off** on the page. Then you run the `content approve … --signoff` command the agent gives you. It refuses if anything changed since the teacher signed.

From about week 9 the teacher can also review **inside the app**: a Review build via TestFlight with every lesson unlocked, an answer key and a Comment button everywhere. When the app rejects an answer they think is right, "This should be accepted" files the comment in one tap. Add the teacher to an internal TestFlight group for that (task M6.10).

## What only people do

Tasks marked **[owner]** in `docs/11` are yours; the agent prepares them and stops.

- **Owner (you):**
  - Running `make project` and the first Xcode build (M0.2), and pushing the first PR (M0.5).
  - Decisions in `docs/13` (open questions Q1–Q13; proposals agents add).
  - Signing, provisioning and capabilities (your team; bundle ID `com.j23n.italian`).
  - Deploying the CloudKit schema to production before sync goes into TestFlight (M7.5).
  - TestFlight and App Store Connect.
  - The Azure key and the study token (`App/Config/Secrets.xcconfig`, gitignored).
  - Passing review files between the teacher and the repo, and running `uv run content approve <file> --by "<name>" --signoff <review>` after the teacher signs off. The command refuses to run from an agent's shell.
  - Study consent text and protocol.
  - Device testing (audio, speech, reminders, sync on three devices).
- **Content lead (your teacher):** sign-off of the syllabus, unit specs, grammar points and story bible (G1, week 3), including the content questions in `docs/13`; a review of each unit; deciding on answers the beta rejected. All of it on review pages or in the app's review mode.
- **Assessment reviewer:** unit checks, final check, rubric ratings in the study.
- **Audio reviewer:** listens to all audio.

## Where this pack goes beyond the plan (check these)

1. **Sync is scheduled earlier** (weeks 9–14 instead of 18–20), while engineering has slack during content production. The three-device test stays at the week-20 gate. Telemetry, the study endpoint and the beta import move into M6, because the week-9 beta needs them.
2. **Moka is assumed as the mascot** (it was your last pick). Tito and the two cups are included, and swapping is an asset change (Q5).
3. **FSRS-6 runs without learning steps or fuzz,** so replay is identical on every device. **Only first attempts count.** **Failed speaking never counts as a lapse.**
4. **The unit check passes at ≥ 70% overall and ≥ 50% per section** (Q11), with half credit for a near-miss. The next unit unlocks either way, and a failed check schedules targeted review.
5. **Learner-facing English is American** (Q13). Audio stays within a **150 MB** budget at 48 kbps AAC.
6. **You create the Xcode project; agents never sign with a team** (ADR-19: unsigned iOS builds, ad-hoc local signing for Mac tests), so only your own first signed build creates the permanent iCloud container.
7. **Articles before they're taught count as part of the noun,** and word cards always show the definite article (*il cornetto*) (ADR-20). This lets Units 0–1 say *la signora Rossi*.
8. **Five colour tokens are darker than the canvas** to pass contrast checks (input borders, switch tracks, one dark tint; ADR-21 and `design/tokens.json`).
9. **Seed content is a draft for the content lead:** the syllabus encoding, 76 grammar points with first-draft detection rules, all unit specs, the story bible (with TBDs and a facts-to-check list) and the golden lesson. Two independent AI-agent reviews (one engineering, one acting as an Italian L2 teacher) and a final consistency check went through the pack, and their fixes are applied; no person has reviewed the Italian yet.
10. **Facts were checked on 7 Oct 2026.** Notably:
    - XcodeBuildMCP is now **MobileBuildMCP**, and its `type_text` can't type accented letters.
    - swift-fsrs has FSRS-6 only on an untagged branch, which is why we port it ourselves against fixtures.
    - Azure HD voices can't be used with batch synthesis, so the course uses standard voices; Azure has no Italian child voice that we know of (see Luca in `content/voices.yaml`).
