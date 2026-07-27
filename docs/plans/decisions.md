# Decisions log

Autonomous-run decisions, recorded for review. Newest phases last.
Each entry: what was decided, why, and what to revisit if you disagree.

## Environment constraints (affect everything below)

- **No Mac/iPhone in this environment.** Everything platform-independent
  is built and tested for real (Rust core, Python authoring, specs,
  content). Swift code is delivered as *clearly-labeled untested
  scaffolding*; the Phase 0 on-device spikes remain yours.
- **No live Anthropic calls made.** The `generate` command and eval
  runners are implemented and unit-tested against mocks; nothing was run
  against the paid API on your behalf. Content authored during this run
  was written directly by me and hand-checked, not API-generated.
- **Legacy web app NOT deleted** despite Phase 8 saying so — deleting it
  before the iOS app is verified on a device would leave you with no
  working product. Deferred until the Mac spikes pass. (`src/maestro/`
  is untouched; new code lives beside it.)
  *Superseded by decision 32: retired on explicit user instruction.*

## Phase 0–2 groundwork (previous sessions, for completeness)

1. **Scenario grammar refs resolved via descriptor expansion.** Legacy
   A1 scenarios reference `unistr_code` (Profilo descriptor), a group
   key. Refs expand to the full canonical-code cluster (clusters are
   level-homogeneous). 14 expansions logged in `spec/it/CONVERSION.md`.
2. **A0/A1 scenario shape unified**: `phase` (unlock grouping, default 1)
   + optional `sequence` (A0 linear order) + optional narrative fields.
3. **Normalization preserves accents** (e ≠ è), strips case/punctuation,
   unifies apostrophes. Tolerance beyond that belongs in authored
   acceptable-answer lists, not code.
4. **Distractor keys stored pre-normalized at build time**, mirroring the
   core's normalizer (`build_pack._normalize` = `normalize.rs`). If the
   normalizer changes, packs must be rebuilt — acceptable, packs are
   build artifacts.

## Phase 3 — learner model + tutor loop (this run)

5. **SM-2 kept, FSRS deferred.** Ported `vocab/srs.py` verbatim
   (conformance vector 03 pins it, including the subtle
   interval-uses-ease-before-update ordering). FSRS would add a heavy
   crate or hand-maintained math for marginal v1 gain; the fold boundary
   makes swapping later cheap.
6. **One mastery notion, not two.** Legacy had both decayed mastery
   scores and a recent-outcomes sliding window (used by
   `pick_archetype`). The core keeps only the decayed model
   (weights targeted 1.0 / productive 1.5 / receptive 0.5, decay
   0.95/day, threshold 0.8, min evidence mass 3.0, 50-event cap per GP);
   archetype selection now reads it too.
7. **Events carry explicit `evidence_class`** (targeted/productive/
   receptive) set by the recorder, rather than the core inferring it
   from modality — drills are `writing` modality but *targeted*
   evidence, so inference would be wrong.
8. **Events may carry explicit `at`; all core APIs take `now`.** Makes
   folds pure and conformance-testable; insertion time backfills `at`.
9. **Spec tables embedded in the pack bundle** (spec_grammar/functions/
   scenarios/can_dos). The bundle is self-contained: the composer has
   the DAG, phases, and can-do decompositions offline; the app never
   ships `spec/` itself.
10. **Can-do achieved = ≥80% grammar mastered AND ≥80% functions
    demonstrated AND ≥1 correct attempt on a `cando`-tagged application
    item.** The 80% (not 100%) avoids one stubborn grammar point
    blocking a visible achievement. New `cando` evidence axis added.
11. **Function "demonstrated" = ≥3 correct targeted/productive uses**
    (receptive exposure doesn't count). Known limitation: repeating the
    same item can inflate the count; bounded by the anti-repeat window,
    revisit when lesson-level analysis lands.
12. **CEFR is a rough classification, not a gate.** *(Superseded the
    legacy rule — highest level with ≥90% grammar mastered and ≥90%
    functions demonstrated. That rule measured against the Profilo's
    whole reference inventory, 351 Italian grammar points; with authored
    content for a fraction of them it reports "A0" indefinitely, so it
    could never have shipped.)* Can-dos are the learner-facing progress
    spine, which frees the level to be descriptive: the highest level
    where the learner has met ≥3 of its grammar points and mastered ≥60%
    of the ones they met, levels walked in order so none are skipped,
    levels with no spec inventory passed over rather than failed.
    Published with mastered/encountered/total counts and a `confidence`
    band (from level coverage) so the UI can show its working, plus
    per-modality attempt counts as before. Functions are reported but no
    longer decide the level — credited per correct use rather than per
    assessment, they are the weaker signal. Per-modality *estimates*
    still deferred until production evidence is rich enough to split.
12a. **`level_assessed` event** carries an `assessed_level` so a future
    CEFR level test has somewhere to land without a schema migration.
    It overrides the estimate only upward: evidence earned since the
    test can still raise the learner, and a stale result can't drag down
    someone who has since demonstrated more. No producer ships yet.
13. **Composer determinism**: explicit RNG seed (SplitMix64, no dep) in
    SessionOptions; same state + seed → identical plan (tested).
14. **Weakness weighting**: item weight = max over its grammar tags of
    1/(mastery+0.25); unseen ≈ 4× more likely than mastered. Anti-repeat
    window = last 50 attempted item ids, with starvation fallback
    (repeats allowed rather than an empty session).
15. **Curriculum gates ported as-is**: phase N+1 at ≥5 scenarios
    completed in phase N; depth ≥2 requires ≥3 scenarios completed at
    depth 1; archetype rules (new-unlocked → introduction, ≥70% mastered
    → application, else consolidation).
16. **Known gap**: no vocab_review slot in composed sessions yet — needs
    a vocab item type in packs (Phase 7); SM-2 state is already tracked
    and due cards are visible in progress_summary.

## Phase 1 completion — vocab list v0

17. **Vocab v0 = 393 lemmas** (A0 ~180 complete for crash-course scope,
    A1 core ~170, A2 starter ~40), one-line entries {id, cefr_level, pos,
    gloss}. Expansion to ~1,500 is Phase 7 mechanical work (frequency
    cross-check via the generate tooling). Wired into pack validation:
    vocab/cando evidence refs now must resolve.
18. **Token-level gloss enforcement deferred**: checking every content
    word against the list needs trustworthy lemmatization (simplemma or
    spaCy at authoring time); shipping a noisy checker would train the
    reviewer to ignore warnings. Lands with the Phase 2 generate
    validators once measured against real drafts.

## Phase 2 completion — authoring pipeline

19. **Item review lifecycle in the YAML**: `status: draft | reviewed |
    flagged` on every item (default `reviewed` so hand-authored files
    stay valid); `build` compiles only `reviewed` items and reports how
    many drafts it skipped. Git remains the audit trail.
20. **Review tool = plain HTML forms, not htmx** (plan §10 said
    FastAPI+htmx). Forms are the no-JS degradable base and enough for
    the queue/edit/coverage slice; htmx is sugar to add when the tool
    grows. Tool only rewrites files it acts on (YAML comments in a
    rewritten file are lost — draft files have none; hand-files are only
    touched if you edit their items through the tool).
21. **`generate` has a file mode** (`--from-file`) parsing a prepared
    model response — makes the pipeline testable without API calls and
    lets any chat session act as the drafting model. API mode uses the
    Anthropic SDK lazily (claude-sonnet-5 default). Batch ids continue
    the per-GP sequence (`drill.<gp>.NNN`).
22. **Readings/listenings compile to parent + question items.** The
    core's one-item-one-answer scoring model holds: the parent carries
    the passage/dialogue + ordered question ids (the composer's
    receptive slot); each question is a scorable child
    (`<parent>.qN`, evidence at half weight). Audio stays null until the
    Phase 7 render step; the shell falls back to per-turn system TTS.
23. **`release` output**: build/release/<version>/ with the bundle +
    release.json (sha256, size, item count). Publishing = static upload;
    the app verifies the digest after download.

## Phase 6 — eval harness (Python side)

24. **Scoring = 0.6 deterministic + 0.4 judge**, deterministic-only when
    no judge is configured. Deterministic checks catch the small-model
    failure modes that matter most: broken JSON, missed seeded errors,
    **hallucinated errors** (tracked as its own scorecard metric with its
    own gate threshold, 5%), missing required content, runaway length.
25. **Golden sets are hand-seeded, not generator-seeded** for now: each
    case records its seeding_note (what was injected into a correct
    text), giving ground truth by construction. 10 writing_feedback +
    4 mistake_explanation starter cases including a no-error
    "hallucination canary". An automated seeder (morphological
    transforms over pack sentences) is worth building only when growing
    past ~50 cases per task.
26. **Gate rule**: enabled iff mean ≥ floor AND hallucination ≤ 5% AND
    mean ≥ ratio × cloud reference (0.80/0.85 writing, 0.75/0.80
    explanation as starting thresholds — pin after the first real
    Apple FM scorecard). Resolved gates land in
    build/gates_resolved.json for the app to bundle.
27. **Judge cost control**: judge is opt-in per run (--judge anthropic);
    mock runners make the whole loop testable offline (verified: a
    hallucinating mock model fails the gate, a clean one passes).
28. **Apple FM runner protocol** = JSON-lines subprocess (Swift CLI
    scaffold in evals/applefm-runner/, ⚠️ untested off-Mac). Mac runs
    are the loop; on-iPhone runs are spot checks.

## Phase 4/5 — iOS shell scaffold

29. **Swift scaffold shipped untested** (7 files under ios/Maestro/ +
    the Apple FM eval runner) — written against the UniFFI-generated API
    and documented iOS 26 surfaces. Judgment call: a complete, coherent
    starting point you compile-fix in one sitting beats either writing
    nothing or pretending it's verified. Every file carries an UNTESTED
    banner; ios/README.md is the ordered Mac checklist.
30. **Cloud backends are never eval-gated, on-device ones always are**
    (LLMBackend.Gates): the cloud reference defines quality, the gate
    protects against the small model degrading it silently.
31. **Pack updates swap atomically after sha256 verification**; learner
    events reference stable item ids + pack_version so history survives
    swaps (tombstones cover removed items).

## Final status matrix (end of autonomous run, 2026-07-17)

Verified = built AND tested in this environment. Scaffold = written,
labeled untested, needs your Mac. Deferred = intentionally not done.

| Plan phase | Status | Evidence |
| --- | --- | --- |
| 0 — spec conversion | **Verified** | spec/it/ 351 GP / 465 CF / 37 scenarios, 0 unresolved refs; tests/unit/test_spec.py |
| 0 — Rust/UniFFI toolchain | **Verified (Linux half)** | cargo tests green; Swift bindings generate; on-device embed = Mac Spike A |
| 0 — SpeechAnalyzer spike | **Blocked on Mac** | protocol + view ready (Spike B) |
| 1 — can-do inventory | **Verified** | 68 descriptors, all refs resolve, coverage invariants tested |
| 1 — vocab list | **Verified (v0)** | 393 lemmas; expansion to ~1,500 = Phase 7 leftover |
| 2 — authoring pipeline | **Verified** | CLI validate/build/generate(file-mode-tested)/review(TestClient-tested)/release |
| 3 — learner model + composer | **Verified** | fold unit tests, simulated-learner test, 3 conformance vectors, compat test |
| 4 — iOS learning loop | **Scaffold** | ios/Maestro/*, compile fixes expected |
| 5 — speaking/writing | **Core verified, shell scaffold** | align.rs tested; SpeakingPracticeView untested; writing capture UI not built |
| 6 — LLM layer + eval loop | **Harness verified, backends scaffold** | mock-model e2e test incl. gate flip; no live API calls made |
| 7 — content fill | **Slice only** | 14 drills + 2 readings + 1 listening (24 bundle items); audio render not wired |
| 8 — hardening/cleanup | **Partially done** | legacy app retired on user instruction (decision 32); backup/export API exists in core (list_events), no UI |

Biggest remaining risks, in order: (1) the two Mac spikes — everything
Swift is unverified; (2) content volume — the pipeline is proven but the
bank is a seed, and TTS rendering (`generate-audio`) is not yet
implemented; (3) eval thresholds are provisional until the first real
Apple FM scorecard.

Suggested order when you pick this up: Mac Spike A → Spike B → build the
Apple FM eval runner and get the first real scorecard → then content
fill can proceed in parallel with app polish.

## Legacy retirement (2026-07-17, on user instruction)

32. **Legacy web app fully retired.** Explicit user instruction after
    the autonomous run ("fully retire the web app and delete all
    relevant code") overrides the earlier keep-until-verified caution.
    Everything is recoverable from git history; last commit containing
    the legacy app is `4ba88ad`. Deleted:
    - `src/maestro/` (the FastAPI + MongoDB app) and `templates/`
    - `tests/integration/`, `tests/eval/`, `tests/fixtures/`, and all
      legacy unit tests — the four new-stack test files remain
      (`test_spec`, `test_pack_build`, `test_authoring_tools`,
      `test_eval_harness`; still 14 green)
    - `data/` — including `data/it/`, the conversion *source*. Judgment
      call: `spec/it/` is canonical and `spec/it/CONVERSION.md` is the
      permanent record; keeping a second, diverging copy of the
      inventories invites confusion. `authoring/convert_spec.py` (the
      one-shot converter) went with it. German content (`data/de/`) was
      already out of scope (Italian-only decision).
    - `scripts/` except `pre-commit` + `install-hooks.sh` (ruff hooks,
      still useful); `Dockerfile`, `docker-compose.yaml` (Mongo-era
      deployment); legacy env vars in `.env.example` (only
      `ANTHROPIC_API_KEY` remains, and even that is optional).
    - `pyproject.toml` rewritten for the authoring/eval stack only
      (pydantic, pyyaml, fastapi + multipart + uvicorn for the review
      UI, httpx, anthropic; dev = pytest + ruff). `uv.lock`
      regenerated. Side effect: with spaCy's model downloads gone,
      `uv sync` now works even behind this environment's proxy — the
      scratch-venv workaround is obsolete.
    - CI rewritten: python job (ruff, unit tests, spec validate, pack
      build, uploads the bundle) → core job (cargo test, pack_compat
      against the python-built bundle, clippy `-D warnings`). The old
      Mongo-based integration-test job is gone.
    - `.claude/CLAUDE.md` and `README.md` rewritten to describe only
      the new stack (the personal README intro was preserved).
    Docs under `docs/plans/` intentionally still mention legacy paths —
    they are historical records of how the port was derived.

33. **Second cleanup sweep (same day, on user instruction):** removed
    everything else not directly part of the mobile-first rewrite —
    the legacy web app's prompt library (`prompts/*.yaml` +
    `versions.lock`; `prompts/runtime/` is untouched and remains the
    only prompt source), the superseded web+PWA plan draft
    (`docs/plans/01-content-pack-architecture.md`; 02/03 keep their
    numbers), and `.dockerignore` / `.gitattributes` (Docker and
    Git-LFS config whose targets were deleted with the app).
