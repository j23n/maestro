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
| `replay/` | event logs for multi-device convergence tests (created in M2.7) | `make test-core` |

To regenerate the FSRS fixtures (only if the reference implementation or our config changes, and only with the owner's approval):

```
git clone --depth 1 --branch v6.3.2 https://github.com/open-spaced-repetition/py-fsrs /tmp/py-fsrs
python3 -I tools/fixtures/gen_fsrs_fixtures.py /tmp/py-fsrs fixtures/fsrs/fsrs6-reference.json
```
