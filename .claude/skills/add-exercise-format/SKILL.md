---
name: add-exercise-format
description: Implement a new exercise format or step kind end to end (schema, pipeline, LearningCore grading, pack, SwiftUI view, events, tests). Use for every M4 task and whenever a lesson type is added or changed.
---

# Adding an exercise format or step kind, end to end

A format touches every layer. Do them in this order and don't skip a layer: a format that works in the app but not in the checker (or the reverse) is not done.

1. **Spec.** Read the format's section in `docs/06` and the grading rules in `docs/05`. If a field, a grading rule, an event or an identifier is missing or unclear, add a proposal to `docs/13` and ask before building.
2. **Authoring schema.** Extend the JSON Schema in `schemas/` for the YAML fields. Add one valid and one invalid fixture under `pipeline/tests/fixtures/`.
3. **Pipeline.**
   - Compile the payload: pattern expansions with focus spans, token arrays for Italian strings, audio IDs, `exercise_targets` and `exercise_requires`.
   - Make the level gate and the production gate see every Italian string in the format.
   - Tests: `make test-pipeline`.
4. **LearningCore.**
   - A `Codable` payload type.
   - A grader, or reuse one from `docs/05`, wired into `FeedbackMachine`.
   - Its row in `RatingPolicy`.
   - Fixture-driven tests: add cases to `fixtures/grading/` when grading is new.
   - Run `make test-core`.
5. **Golden content and the mini pack.** Make sure the golden sample (or a draft fixture lesson) contains at least one item of this format. Rebuild the mini pack with `make mini-pack` (it writes `fixtures/packs/mini.sqlite` and `mini-payloads.json`), check that LearningCore decodes the JSON and `PackReader` decodes the SQLite pack.
6. **App.**
   - A view and view model from `DesignSystem` components (see the `ios-ui` skill).
   - The identifiers listed in `docs/06`.
   - Mac keyboard handling, VoiceOver labels and announcements.
   - Behaviour without speech or audio where relevant.
7. **Events.**
   - `attempt` events with the right `format`, `targets`, per-target outcomes, `attemptIndex` and `mode`.
   - Check that replay produces the expected memory change (a LearningCore test with this format's events).
8. **Tests and evidence.**
   - Snapshots: compact and regular, light and dark, AX5.
   - One XCUITest path through the golden item.
   - Simulator and Mac screenshots in `artifacts/screens/<task-id>/`.
9. **Verify.** Run `make test`, `make build-ios build-mac test-app`, the ui-reviewer, then the spec-reviewer.
10. **Record.** Update the docs if anything changed, and add a `PROGRESS.md` entry with the evidence.
