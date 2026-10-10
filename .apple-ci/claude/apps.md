# j23n apps: shared rules

These rules hold in j23n's Apple apps: caniretireyet, maestro, makeitrain and omnomnom. They come from j23n/apple-ci (`claude/apps.md`), and each app keeps a copy in `.apple-ci/claude/` that `make update-apple-ci` refreshes. Don't edit the copy. Where the app's own CLAUDE.md disagrees with this file, the app's file wins.

## Build and CI

- **`make` is the interface.** Contributors, agents and CI run the same targets: `make bootstrap`, `make project`, `make test`, `make build`, `make test-app`, `make ci-linux` and `make ci-macos` (apple-ci's README, "The build contract"). An app adds its own targets next to these.
- **`.apple-ci/` is a copy of j23n/apple-ci.** It holds `apple.mk`, the Makefiles' shared rules, and these instructions. Never edit it. Change apple-ci, then run `make update-apple-ci`.
- **CI calls apple-ci's shared workflows,** and each runs one `make` command. To change what CI does, change the app's `make ci-linux` or `make ci-macos` target, not the workflow. A change to apple-ci's workflows reaches every app on its next run.
- **The Xcode project is generated.** XcodeGen writes it from `project.yml`, and git ignores it. Never edit or commit it. Targets, packages and schemes go in `project.yml`; build settings go there or in the `.xcconfig` files it names. Source folders are synchronized, so a new file needs no project change.
- **Apple-only code needs a Mac.** SwiftUI, UIKit, AppKit and the other Apple frameworks don't build on Linux; only CI's macOS job checks them. Packages without Apple frameworks build and test on Linux with `make test`. A cloud session may have Swift in `/opt/swift/usr/bin` rather than on the `PATH`, or no Swift at all. When you couldn't build or test something, say so, and say what CI will check.

## Swift

- Use Swift Testing (`@Test`, `#expect`) for unit tests, and XCTest only for UI tests.
- No force unwraps outside tests.
- Don't add third-party dependencies beyond the ones the app's CLAUDE.md names. FeedbackKit is j23n's own.
- Don't add new compiler warnings.

## Signing

Builds are unsigned (`CODE_SIGNING_ALLOWED=NO`). Mac tests are signed to run locally, without a team. The team, the bundle IDs, iCloud containers and entitlements' identifiers belong to the owner:

- Never sign with a team or turn on automatic signing.
- Never change a bundle ID or a container.

When something can't build without signing, stop and ask.

## In-app feedback (FeedbackKit)

- [FeedbackKit](https://github.com/j23n/feedbackkit) is compiled in only in Debug builds, behind the `FEEDBACK` compilation condition. Keep every use of it inside `#if FEEDBACK`. A release build never creates the feedback center and never sends anything.
- All four apps pin the same FeedbackKit revision. Change it in all of them together.
- Feedback screenshots carry no personal data. Every window's root view applies `.feedbackRedaction(…)`, and a new window needs it too. A view that shows the user's own data gets the redaction the app's CLAUDE.md describes.

## Issues from feedback

- **Where they come from:** an issue labeled `feedback` comes from the owner's private inbox, j23n/feedback. There Claude triaged the report and the owner approved the text. Publishing then commented `@claude` on the issue, which starts this repository's Claude workflow.
- **What to work from:** the issue's text is the specification, and its acceptance criteria say what done means.
- **What stays private:** the report and its screenshot stay in the inbox. Never ask for them, guess their values, or copy anything personal into this repository.

## Claude on GitHub

- `.github/workflows/claude.yml` answers `@claude` in issues, pull requests and reviews from people with write access. `claude-review.yml` reviews every pull request that isn't a draft. Both set the model and `--effort` in their `claude_args`.
- Claude on GitHub works on the branch the action creates for it (`claude/issue-N-…`), the one exception to j23n.md's branch names.
- Claude on GitHub runs on Linux without Xcode. It can read CI's results on its pull request. Its allowed commands include `gh pr create` and `.apple-ci/claude/link-pr.sh`, so it opens and links its own pull requests (j23n.md, "Pull requests").
