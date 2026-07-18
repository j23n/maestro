# 05 — Audit resolution: what the learn/* stack fixed

Status: record of the Mac-independent fixes applied across the
`learn/01` … `learn/08` stage branches, against the findings in
`04-product-readiness-audit.md`. Everything here is built and tested in
CI-equivalent runs (pytest, cargo test incl. conformance +
pack_compat against the real bundle, clippy `-D warnings`, ruff);
nothing needed a Mac or an API key — real providers are key-gated
behind interfaces whose plumbing offline mocks prove.

## The Ferragosto walkthrough, revisited

The audit walked a themed "Ferragosto" pack through the pipeline and
found every step broken. The same walkthrough now:

1. **Author it.**
   `generate --type reading --theme "Ferragosto" --level A1` (and
   `--type drill|listening|vocab|speaking|writing|grammar_ref`; scopes:
   `--gp`, `--scenario`, `--cando`, `--theme`). Theme mode embeds the
   allowed grammar/function inventories and the leveled vocab list, so
   thematic drafts stay curriculum-grounded. File mode
   (`--from-file`) works for every family. The repo carries the result:
   a 14-item Ferragosto mini-pack drafted exactly this way
   (`packs/it/*/ferragosto.draft.yaml`, promoted after review).
2. **Validate it.** `validate --quality` runs the four quality gates
   (vocab level via lemmatization, answer-key solvability,
   near-duplicates, orthography) as warnings;
   `validate --adversarial[-from-file]` runs the second-model
   defensible-answer pass. Dogfooding these on the seed content
   surfaced 12 missing lemmas and 6 mislevelings — the
   "review finding becomes a validator" loop working.
3. **Review it.** The tool covers every item family, renders items as
   the learner sees them (with audio players and images inline), shows
   the spec cell's material and live validator warnings beside the
   Accept button, has keyboard triage, an L1-reviewer mode, a coverage
   matrix with per-cell generate commands, and a release diff.
4. **Media.** `generate-audio` renders per-turn dialogue audio,
   speaking-prompt pronunciations, and vocab fronts (Azure / OpenAI /
   offline mock; sha-cached re-renders); `generate-images` renders
   scenario art, vocab illustrations, and reading headers (gpt-image-1
   / offline mock). `build` embeds bytes into the bundle's `media`
   table; the core exposes `get_media`; dangling refs fail the build.
5. **Release it.** ed25519-signed manifests (`release keygen` once,
   `.pub` committed for the app), a version catalog (`index.json`),
   an overwrite guard, and a tombstone guard: releasing while an item
   from the previous release is missing and untombstoned is refused.
6. **Update safety.** Tombstones flow source → bundle table → core
   (`list_tombstones`); the core refuses future schema versions
   (`pack_status().compatible` for the UI).
7. **Runtime.** The composer's vocab-review slot serves due SM-2 cards;
   speaking prompts feed the alignment scorer; writing submissions
   queue as feedback jobs offline and fold back as evidence when a
   backend appears; `export_log`/`import_log` is the backup story.
8. **Measure it.** The eval loop has a pinned, versioned judge with
   scorecard provenance, a `speaking_feedback` task, and — new — a
   `content_generation` task that grades what `generate` produces
   using the real authoring prompt + the quality validators, so
   "which model may draft lesson content" is a scorecard, not a vibe.

## Finding → fix map (audit §2)

| Audit finding | Fixed in | How |
| --- | --- | --- |
| A4: 4 of 7 item families missing | stage 2 | vocab/speaking/writing/grammar-ref schemas + build + seeds |
| A3/D2: no audio anywhere | stage 3 | generate-audio providers → media table → core get_media |
| D1: images not a concept | stage 3 | generate-images providers; scenario art by convention path |
| A5: tombstones nowhere | stages 2/3/4 | sources → build table + guards → core reads + compat check |
| A6: no backup | stage 5 | export_log / import_log, all-or-nothing restore |
| C3: no feedback queue | stage 5 | feedback_jobs + typed contract + evidence fold-back |
| A4: vocab loop dead | stages 2/6 | vocab cards + spec_vocab table + composer vocab_review slot |
| B1: generate drills-only, gp-only | stage 3 | all families; gp/scenario/cando/theme scopes |
| B2: quality validators missing | stage 3 | vocab-level, solvability, near-dup, orthography, adversarial |
| B3: review tool 3/6 workflows, drills-only | stage 3 | all six workflows, all families |
| B4: unsigned, undistributed releases | stage 3 | ed25519 signing, index.json, guards, verify command |
| B5: normalizer parity unguarded | stages 2/4 | shared golden vectors, pytest + cargo runners |
| C1/C7: gates file emitted blind | stage 7 | --resolve-gates refuses empty results without explicit flag |
| C4: judge unpinned/unversioned | stage 7 | JUDGE_MODEL + judge_prompts/default.v1.yaml + scorecard fields |
| C5: thin case sets, inert hallucination gate | stage 7 | 16/8/6/4 cases, must_not_contain canaries, seeder tool |
| C6: legacy second eval system | stage 7 | compare.py + jsonl deleted |
| (new) content generation unmeasured | stage 7 | content_generation eval task over the real authoring prompt |
| E2/E3: conformance pins folds only | stage 6 | session-plan, scoring, alignment, normalize vectors |
| E5: core doc drift (FSRS, "Phase 3") | stage 8 | core/README.md + lib.rs headers rewritten |

## Still Mac/API-gated (unchanged from the audit)

Spike A/B (Xcode project, xcframework, SpeechAnalyzer fairness), the
Apple FM eval runner build and the first *live* scorecards, real
audio/image rendering with provider keys, TestFlight logistics, and
content fill at volume — the pipeline for all of it is now in place;
`ios/README.md` carries the updated wiring checklist.
