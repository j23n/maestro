# Fixtures

Ground truth for tests. Each file names the spec section it encodes. Never edit `fsrs/` by hand (a hook blocks it); the other fixture files grow whenever a bug is fixed.

| File | Encodes | Used by |
|---|---|---|
| `fsrs/fsrs6-reference.json` | FSRS-6 with our config (no learning or relearning steps, no fuzz, retention 0.9): 35 scenarios, 317 reviews, generated from py-fsrs 6.3.2 | `make test-core` (FSRS6Tests) |
| `grading/normalizer.json` | answer normalisation, accent stripping, accent-sensitive words (`docs/05`) | Swift and Python tests (parity) |
| `grading/patterns.json` | answer-pattern expansion order, focus, gender, slots, limits (`docs/03`) | Swift and Python tests |
| `grading/typed-answers.json` | typed-answer grading outcomes, mismatches and hint kinds (`docs/05`) | `make test-core` |
| `grading/dictation.json` | per-word dictation marks (`docs/05`) | `make test-core` |
| `grading/transcripts.json` | speech transcript matching (`docs/05`) | `make test-core` |
| `packs/mini.sqlite` | a tiny pack built from the golden sample (created in M1.10 by `make mini-pack`; audio added in M5.1) | Storage and App tests, previews |
| `packs/mini-payloads.json` | every step and exercise payload of the mini pack as JSON (same task) | LearningCore decode tests on Linux |
| `replay/resume-mid-step.json` | a learner quits mid-way through a practice step and resumes at the same exercise: the expected presentation order (block, then the mix shuffled with SplitMix64 seeded by FNV-1a 64 of the step ID, computed independently in Python) and the cursor after each phase (`docs/05` § Replay) | `make test-core` (ReplayFixtureTests) |
| `replay/two-devices.json` | an iPad and an iPhone of one learner write events offline (an earlier start on the iPad, a newer client's event type, two events in the same millisecond) and converge in any delivery order: expected introductions, memory reps, step progress, unit states and daily activity (`docs/05` § Replay, `docs/08` § Merge rules) | `make test-core` (ReplayFixtureTests) |

The event IDs in `replay/` refer to the synthetic course in `Packages/LearningCore/Tests/LearningCoreTests/Support/TestCourse.swift` (shaped like the golden Unit 2 Lesson 1). Events are envelopes as `EventCodec` writes them (camelCase, `docs/03` § The learner database).

To regenerate the FSRS fixtures (only if the reference implementation or our config changes, and only with the owner's approval):

```
git clone --depth 1 --branch v6.3.2 https://github.com/open-spaced-repetition/py-fsrs /tmp/py-fsrs
python3 -I tools/fixtures/gen_fsrs_fixtures.py /tmp/py-fsrs fixtures/fsrs/fsrs6-reference.json
```
