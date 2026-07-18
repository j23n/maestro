# 03 — Implementation plan: native iOS + portable core

Status: draft
Owner: solo
Scope: Italian only, A0–A2, personal distribution (TestFlight)
Prerequisite reading: `02-greenfield-architecture.md` (the four-layer
conceptual architecture this plan implements)

Decisions this plan assumes (made 2026-07):

- **Native iOS first**, SwiftUI, targeting **iOS 26+** (SpeechAnalyzer is
  the speech foundation; personal/TestFlight distribution means we can
  require the current OS and skip legacy fallbacks).
- **A portable core**: everything platform-neutral — tutor loop, learner
  model, pack reader, scoring — lives in one shared library so a future
  Android (or desktop) app is a new UI shell, not a rewrite.
- **Speaking exercises are core scope**, built on on-device speech
  recognition. Conversation practice (open-ended LLM dialogue) is
  explicitly *not* v1.
- The existing **grammar points, communicative functions, and scenarios
  inventories are kept** (content preserved, format converted). Everything
  else in the current repo may be rewritten or deleted.

---

## 1. Target shape of the repo

Monorepo, current web app frozen on day one and deleted in the final
phase:

```
maestro/
├── spec/it/                  # Layer 1 — curriculum spec (schema-validated)
│   ├── grammar_points.yaml   #   converted from data/it/ (IDs preserved)
│   ├── comm_functions.yaml   #   converted from data/it/
│   ├── scenarios.yaml        #   converted from data/it/
│   ├── vocab.yaml            #   consolidated leveled lemma list
│   └── can_do.yaml           #   NEW — A0–A2 can-do inventory
├── packs/it/                 # Layer 2 — authored content (YAML sources)
│   ├── drills/  readings/  listenings/  dialogues/
│   ├── grammar_refs/  writing_prompts/  speaking_prompts/
│   └── pack.yaml             #   manifest: version, coverage, item index
├── audio/it/                 # pre-rendered audio (git LFS)
├── authoring/                # Python — maestro-pack CLI
│   ├── generate/  validate/  review/  build/  release/
│   └── prompts/              #   Claude drafting + adversarial-check prompts
├── core/                     # Rust — the portable core (Layers 3 + 4)
│   ├── src/{pack,events,folds,session,scoring}/
│   └── uniffi/               #   generated Swift (later Kotlin) bindings
├── conformance/              # golden test vectors for core behavior
├── prompts/runtime/          # runtime LLM prompts, shared by app + evals (§11)
├── evals/                    # LLM eval loop: golden sets, runners, scorecards (§11)
├── ios/                      # SwiftUI app (the shell)
└── src/maestro/              # legacy FastAPI app — frozen, deleted Phase 8
```

---

## 2. The portable core

### 2.1 Boundary rule

One sentence decides every placement question: **if it would behave
identically on Android, it goes in the core; if it touches a platform
API, it goes in the shell.**

**In the core (Rust):**

- Pack reader — open/verify a pack SQLite bundle, query items, manifest
  and tombstone handling, pack-update compatibility checks.
- Learner record — append-only evidence event log in a local SQLite DB;
  export/import (backup) as a serialized log.
- Derived-state folds — grammar mastery (weighted, decayed), function
  demonstration counts, FSRS vocab scheduling, scenario depth, can-do
  rollup, per-modality CEFR profile.
- Session composer — unlock DAG, archetype choice, time-budget shaping,
  weakness-weighted selection, anti-repetition window.
- Deterministic scoring — answer normalization (case, accents,
  punctuation, article/clitic tolerance), acceptable-answer matching,
  distractor-feedback lookup, and the **transcript alignment scorer**
  for speaking (word-level alignment + edit distance against target;
  pure computation on text produced by platform STT).
- The LLM-layer *contract* — request/response types for feedback jobs,
  the pending-feedback queue, and folding feedback results back into
  evidence. (Making the network call is the shell's job.)

**In the shell (Swift):**

- All UI (SwiftUI), navigation, rendering of activity types.
- Speech: SpeechAnalyzer/SpeechTranscriber session management, mic
  capture, audio playback of pack assets, AVSpeechSynthesizer fallback
  TTS.
- LLM backend implementations: cloud (user's Anthropic key), Apple
  Foundation Models where available, self-hosted endpoint.
- Pack downloads, file management, notifications, backup file handling
  (core produces the bytes; shell picks where they go).

### 2.2 Technology: Rust + UniFFI

Rust with UniFFI-generated Swift bindings (Kotlin comes free later).
Rationale: mature FFI story on both mobile platforms, `rusqlite` for
storage, and `fsrs-rs` gives us the modern FSRS scheduler as a crate
instead of hand-porting SM-2. The API surface stays **coarse-grained** —
a handful of calls exchanging serde-serialized value types
(`compose_session`, `score_attempt`, `record_event`, `progress_summary`,
`export_log`, `pack_status`) — so the FFI boundary never becomes the
place where iteration goes to die.

**Off-ramp (decided at the end of Phase 0):** if the Rust/UniFFI spike
shows unacceptable friction for solo iteration, the fallback is a pure
Swift core package with the same API, plus the conformance suite (§2.3)
as the portability guarantee — behavior stays specified and re-implementable
on Android later. The plan proceeds identically either way; only `core/`'s
language changes.

### 2.3 Conformance suite

`conformance/` holds golden test vectors: (pack fixture + event log) →
expected derived state, session plan, and scores, as JSON. The Rust core
must pass them; any future second implementation must too. Mastery-decay
and SRS edge cases get ported here from the existing Python tests, which
encode real behavioral decisions worth keeping.

---

## 3. Speech stack (pinned)

Per the July 2026 research pass:

| Concern | Choice |
| --- | --- |
| Speaking-exercise STT | **SpeechAnalyzer / SpeechTranscriber**, on-device, it-IT, iOS 26+. No SFSpeechRecognizer fallback (we control the install base). |
| Speaking scoring (offline) | Core's transcript-alignment scorer: normalized word-level alignment against the target, per-word match/miss surfaced in UI. Measures *what you said*, not how it sounded. |
| Pronunciation scoring (optional online tier) | **Azure Pronunciation Assessment** (only production API with it-IT phoneme-level + fluency/prosody; ≈$0.003 per utterance). Behind a `PronunciationScorer` interface; a future on-device wav2vec2-GOP scorer slots in behind the same interface. |
| Pack audio | Pre-rendered at authoring time: Azure neural it-IT for bulk, ElevenLabs for hero dialogue voices if quality warrants. One-time cost, tens of dollars for the course. |
| Fallback TTS (arbitrary text) | AVSpeechSynthesizer enhanced/premium it-IT voices. |
| On-device LLM (optional) | Apple Foundation Models on Apple-Intelligence devices, behind the LLM backend interface. Never assumed. |

**Speaking ≠ conversation.** Speaking exercises — read-aloud,
listen-and-repeat, prompted response ("Order a coffee and ask for the
bill") with authored target answers — are closed tasks, scored offline by
alignment, and are v1 core scope. Conversation (open-ended dialogue with
a tutor persona) is an LLM-tier feature deferred past v1; the
architecture leaves it a clean slot.

---

## 4. Data contracts (locked early, everything hangs off them)

- **Spec IDs are forever.** `grammar.passato_prossimo.aux_avere`,
  `function.ordering_food`, `cando.a1.order_meal`, `vocab.mangiare`.
  Conversion from `data/it/` preserves existing grammar/CF/scenario codes.
- **Pack bundle** = one read-only SQLite file + audio directory, built
  from `packs/it/` YAML. Tables: `items` (typed payload JSON, evidence
  tags, CEFR level, modality, difficulty), `acceptable_answers`,
  `distractor_feedback`, `explanations`, `media`, `tombstones`,
  `manifest`. Semver + item-count coverage report per spec cell.
- **Evidence event** (from doc 02 §4): `{when, item_id, pack_version,
  modality, outcome, evidence[], response, feedback_source}` — stored
  append-only; all learner state is a fold.
- **Session plan**: ordered activity list with item refs + composition
  rationale (which axis each pick serves), so the UI can explain "why am
  I seeing this".

---

## 5. Phases

Solo-dev sequencing with two tracks that overlap heavily: the **product
track** (core + iOS) and the **content track** (spec + authoring +
content fill). Rough total: ~5 months of focused part-time work
(Phase 6 grew a week when the eval loop moved into it, §11).

### Phase 0 — Derisking spikes (~2 weeks)

Goal: retire the three riskiest assumptions before committing.

- **Core spike**: Rust crate + UniFFI + SwiftUI walking skeleton on a
  real device — open a fixture pack SQLite, fetch one drill, score one
  answer, append one event, read it back. Measure build/iterate loop.
- **Speech spike**: SpeechAnalyzer it-IT — read-aloud transcription of
  accented non-native speech, alignment against target text; judge
  whether word-level scoring feels fair on imperfect pronunciation.
- **Spec conversion spike**: script that converts `data/it/`
  grammar/CF/scenario YAML+JSON into `spec/it/` schema-validated form,
  IDs preserved; hand-fix pass for whatever doesn't map cleanly.

Exit: skeleton app runs the fixture drill end-to-end on device; speech
spike verdict written up; converted spec validates. **Decide Rust vs
Swift-core off-ramp here.**

Risks: UniFFI friction (→ off-ramp); SpeechAnalyzer too strict on
learner accents (→ looser alignment scoring, per-word confidence
thresholds tuned in Phase 5).

### Phase 1 — Curriculum spec + can-do inventory (~2–3 weeks, overlaps 0/2)

Goal: Layer 1 complete for Italian A0–A2. This is curriculum work, not
code.

- Finalize spec schemas (Pydantic, in `authoring/`); CI validation.
- Write the **can-do inventory**: ~60–80 original descriptors across
  A0–A2, RLD-inspired (*Profilo della lingua italiana* as checklist, our
  own text), each decomposed into required grammar points, functions,
  and vocab domains, each mapped to scenarios.
- Consolidate the leveled vocab list (~1,500 lemmas through A2) from
  existing seed data + frequency lists; make the gloss-constraint list
  the validators will enforce.
- Define pack manifest + ID-stability + tombstone rules.

Exit: `spec/it/` validates; every can-do resolves all its references;
every grammar point reachable through the prerequisite DAG.

### Phase 2 — Authoring pipeline (~3 weeks)

Goal: `maestro-pack` CLI produces a valid, reviewed, built pack.

- `generate`: Claude drafts item batches per spec cell (drills with
  acceptable answers + per-distractor feedback + explanation; readings;
  listening dialogues; speaking prompts with target answers; writing
  prompts with rubrics). Reuses the existing `llm.py` wrapper and prompt
  externalization pattern.
- `validate`: schema; vocab-level constraint (out-of-level lemma ⇒ gloss
  or reject); answer-key solvability; **adversarial answer pass** (second
  model tries to find defensible alternative answers; hits go to review);
  duplicate detection; morphology/agreement heuristics (spaCy it).
- `review`: the pack review tool — a local web UI over the working tree
  (queue, in-place editing, coverage dashboard, release diff). Full
  design in §10; the Phase 2 slice is queue + editing + coverage.
- `build`: YAML → SQLite bundle + audio render (Azure neural it-IT);
  reproducible; coverage report per spec cell.
- `release`: signed manifest + bundle to static hosting (a GitHub
  release or any dumb HTTPS host).
- Seed content to feed Phase 3–4 development: one scenario arc, ~5
  grammar points, ~150 drills, a few readings/listenings, speaking +
  writing prompts.

Exit: `generate → validate → review → build` produces a pack the Phase 0
skeleton can open; authoring throughput measured (target: a reviewed
30-item drill bank in <30 min of human time).

### Phase 3 — Core: learner model + tutor loop (~3–4 weeks)

Goal: the portable core is functionally complete against real packs.

- Event log storage + export/import.
- Folds: mastery (port the weighted/decayed model — weights and decay
  constants carried over from `learning/mastery.py`), FSRS vocab
  scheduling, function counts, scenario depth, can-do rollup,
  per-modality CEFR profile with production-confidence caps.
- Session composer: unlock DAG (port `lessons/curriculum.py` semantics),
  archetypes (introduce/consolidate/apply), 5-min vs 15-min budgets,
  weakness-weighted sampling, anti-repetition.
- Deterministic scoring incl. Italian-aware normalization and the
  transcript-alignment scorer.
- Conformance suite seeded from ported Python test cases.

Exit: conformance green; a scripted "simulated learner" run (N sessions
against the seed pack) produces sane progression curves — mastery rises,
SRS intervals spread, unlocks fire in DAG order.

### Phase 4 — iOS app: the learning loop (~3–4 weeks)

Goal: daily-usable app for receptive + drill work.

- Session player: drill (cloze/MC/match/transform), grammar card,
  reading, listening, vocab review; pre-authored feedback surfaced on
  errors; session summary.
- Progress: can-do tree (the learner-facing spine), CEFR per-modality
  profile, grammar DAG view.
- Pack manager: download/update from release manifest, version pinning,
  update-safety via tombstones.
- Settings: backup/export (core-produced log), privacy ledger screen
  (static for now — nothing leaves the device yet).

Exit: I do real Italian sessions daily on my own phone from a TestFlight
build; no network permission even requested by the app at this point.

### Phase 5 — Speaking + writing (~2–3 weeks)

Goal: the productive-skill activities, offline-first.

- Read-aloud + listen-and-repeat + prompted-response activities:
  SpeechAnalyzer capture → core alignment scoring → per-word feedback
  UI; retry loop; evidence events with speaking modality.
- Writing: capture + deterministic checklist feedback (length, target
  structures attempted, vocab level); submission queued as a pending
  feedback job.
- Optional Azure pronunciation tier behind `PronunciationScorer`,
  off by default, clearly labeled online.

Exit: full session including speaking + writing works in airplane mode;
pronunciation tier works when enabled and degrades silently when not.

### Phase 6 — LLM layer + eval loop (~3 weeks)

Goal: the optional tutor, with the privacy ledger real — and every
on-device capability decided by measurement, not optimism.

- **Eval harness first** (§11): golden set for `writing_feedback`
  (~50 seeded-error cases), runners for the Anthropic reference backend
  and Apple Foundation Models (macOS CLI), deterministic checks + judge
  scoring, first scorecard. Built *before* the backends are wired into
  the app, so wiring decisions are informed by numbers.
- Backend interface + two implementations: Anthropic API (user-supplied
  key) and Apple Foundation Models (gated by the eval scorecard, not
  just device capability). Self-hosted endpoint is config, not code.
- Writing/speaking rubric feedback (tier 1) consuming the pending-job
  queue; results fold back as evidence; UI labels feedback source.
- Personalized explanation ("explain differently, knowing my history")
  with minimal-context prompts (item + response + relevant weakness
  tags only); `mistake_explanation` golden set added, gates applied.
- Runtime prompts move to `prompts/runtime/` (shared by app and
  harness) and get versioned; prompt changes go through the eval loop.
- Privacy ledger: every outbound payload summarized and listed.

Exit: queued writing from an offline day gets feedback when a backend
appears; ledger shows exactly what left the device; app remains fully
functional with no backend configured; the scorecard states, per
feature, whether Apple FM is enabled and why.

### Phase 7 — Content fill: Italian A0–A2 (~3–4 weeks, overlaps 4–6)

Goal: the course is deep enough to live in.

- Full inventories per the spec: all A0–A2 grammar points, functions,
  scenario arcs (depth 1–3 with recurring characters), ~750+ drills,
  ~50 readings, ~50 listenings, speaking/writing prompts per can-do,
  grammar reference pages.
- Every L1-review finding that can become a validator, becomes one.
- L1 speaker review pass (booked at Phase 2 exit); audio rendered.
- Review tool gains audio preview and the L1-reviewer mode (§10);
  the `speaking_feedback` golden set joins the eval loop (§11).

Exit: an A0→A2 journey has no "out of content" moments; validator
error rate on newly generated batches trending down.

### Phase 8 — Hardening + cleanup (~1–2 weeks)

Goal: v1 to TestFlight testers; repo tells the truth.

- Pack update end-to-end (new release → in-app update → history intact).
- Backup/restore drill on a second device.
- TestFlight to friends; feedback triage.
- **Delete `src/maestro/`** (web app, Mongo models, routes, TTS/STT
  server code) and dead seed formats; README rewritten around
  spec/packs/authoring/core/ios.

---

## 6. Current repo: kept / mined / deleted

| Asset | Fate |
| --- | --- |
| `data/it/grammar_points.yaml`, `comm_functions.json`, `scenarios_*.yaml` | **Kept** — converted to `spec/it/` (Phase 0), IDs preserved, content refined in a later pass |
| `data/it/vocab_a0.yaml` + dictionary ingests | **Mined** — starting material for the consolidated vocab list |
| `learning/mastery.py`, `vocab/srs.py`, `lessons/curriculum.py` | **Mined** — semantics and test cases ported into the core + conformance suite, then deleted |
| `llm.py`, `prompts/` | **Mined** — patterns reused in `authoring/` |
| A0 static lessons (`a0_lessons.yaml`) | **Mined** — content recycled into pack items where it fits |
| Everything else (`routes/`, `models.py`, `main.py`, templates, Mongo, Azure TTS/STT runtime, tests for the above) | **Deleted** (Phase 8; frozen from day one) |

| German data (`data/de/`) | **Parked** — untouched until Italian v1 ships |

---

## 7. Running costs

- Authoring-time Claude usage: the only meaningful recurring cost, and
  it's bursty (content-fill phases), not per-learner.
- Audio pre-render: one-time, tens of dollars for the course.
- Runtime: zero by default (static pack hosting only). Optional tiers
  billed to the learner's own keys (Anthropic API, Azure pronunciation
  at ≈$0.003/utterance).

## 8. Top risks

1. **Solo-dev toolchain spread** (Python + Rust + Swift). Mitigated by
   the coarse FFI boundary, the Phase 0 off-ramp, and Python staying
   confined to authoring.
2. **Speech scoring feels unfair** on learner accents — the make-or-break
   for speaking exercises. Spiked in Phase 0, tuned in Phase 5
   (alignment tolerance, per-word confidence, generous retry UX).
3. **Content quality at volume.** The adversarial-answer validator and
   the "every review finding becomes a check" loop are the defense;
   L1 review is booked, not hoped for.
4. **Can-do inventory scope creep.** Timebox Phase 1; descriptors can be
   refined in content passes, but the *set* must be frozen early since
   packs and progress views hang off it.
5. **On-device LLM quality is unknown per task.** A ~3B model may handle
   explanation upgrades but botch rubric feedback, and quality will
   shift with OS/model updates. The eval loop (§11) turns this from a
   launch-time surprise into a measured, re-checkable gate.

## 9. Open decisions (deliberately deferred)

| Decision | When |
| --- | --- |
| Rust core vs Swift-core off-ramp | End of Phase 0 |
| FSRS parameters (defaults vs per-learner optimization) | Phase 3 |
| Review tool stack (FastAPI+htmx recommended — familiar) | Phase 2 |
| Azure vs ElevenLabs mix for dialogue audio | Phase 7 |
| Eval judge model pin + per-feature gate thresholds | Phase 6 |
| Android shell (Kotlin + same core) timing | Post-v1 |
| Conversation practice design | Post-v1 |

---

## 10. Design: the pack review tool

The recurring human job in this architecture is reviewing LLM-drafted
content, so the review tool is the maintainer's primary interface —
worth designing properly, not bolting on.

**Principle: git is the database.** The tool is a local web app
(`maestro-pack review`, FastAPI + htmx — the stack already in hand) over
the *working tree*. Every action it takes is an edit to the YAML sources;
item state lives in the items themselves (`status: draft | reviewed |
flagged` plus an optional `review_note`). Nothing is stored anywhere
else, so the ordinary git diff/commit/revert flow *is* the audit trail,
and the tool can be thrown away or rewritten without losing anything.

**Workflows:**

1. **Review queue.** LLM-drafted items land as `status: draft`. The queue
   shows one item at a time, rendered as the learner will see it (prompt,
   choices, acceptable answers, distractor feedback, explanation),
   alongside its provenance: the spec cell it was generated for, the
   generation batch, and any validator warnings. Keyboard-first triage:
   accept / edit / reject / defer. Edits are validated live against the
   item schema and spec references before they can be saved.
2. **Context panel.** The spec cell's own material — the grammar point's
   examples and explanation, the function's patterns — sits beside the
   item, so correctness judgments don't require leaving the page.
3. **Coverage dashboard.** A matrix of spec cells (grammar point × level
   × item type) showing item counts against Phase 7 targets. Thin cells
   are the authoring backlog, with the `generate` invocation for each
   cell one copy-paste away.
4. **Release diff.** Item-level diff between the working tree and the
   last released pack version (added / changed / removed / tombstoned) —
   the "what am I about to ship" check that backs `maestro-pack release`.
5. **L1-reviewer mode** (Phase 7). A read-only pass over `reviewed`
   items with flag + comment; flags flip items back to `flagged` in the
   YAML and reopen them in the maintainer's queue.
6. **Audio preview** (Phase 7). Rendered TTS playable next to its
   script; flagging an audio file marks it for re-render in the next
   `generate-audio` run.

**Build order:** queue + editing + coverage in Phase 2 (it must exist
before content fill starts, or Phase 7 becomes YAML-editing drudgery);
release diff with the first `release`; L1 mode and audio preview in
Phase 7. The Phase 2 exit criterion — a 30-item batch triaged in under
30 minutes of human time — is measured *through this tool*.

---

## 11. Design: the LLM eval loop

The runtime LLM layer spans backends from Claude down to a ~3B on-device
model. Whether Apple Foundation Models is good enough for a given
feature — and which prompt gets the most out of it — must be measured,
re-measurable after every prompt tweak and OS update, and encoded as a
gate the app respects. That is this loop's job: fine-tune the prompts
against fixed targets, and find the limits of the on-device models.

**Components (`evals/`):**

1. **Golden sets** (`evals/cases/<task>/*.yaml`). Tasks in order of
   arrival: `writing_feedback` and `mistake_explanation` (Phase 6),
   `speaking_feedback` (Phase 7+). A case holds the input (item context,
   learner submission, weakness tags) and its expectations: error tags
   that MUST be identified (by grammar-point id), claims that MUST NOT
   appear (hallucinated errors — the cardinal sin for a small model),
   required elements (a correct model answer, mention of the violated
   rule), and tone/length bounds. ~50 cases per task to start.
2. **Seeded-error construction.** Cases are built by taking correct
   sentences from the packs and injecting *known* error types (auxiliary
   choice, gender/number agreement, article misuse, tense) — so ground
   truth is known by construction and tagged with the violated grammar
   point. Hand-check once, then freeze; real learner submissions can be
   added later only from the maintainer's own exported data.
3. **Runners**, one per backend behind a common interface:
   - `anthropic` — the cloud reference; also the regression baseline.
   - `apple_fm` — a small Swift CLI (Foundation Models runs on macOS 26
     on Apple silicon) that reads case inputs as JSON on stdin and emits
     outputs; the Python harness shells out to it. On-device iPhone
     runs are a spot-check, not the loop — the Mac is close enough.
   Crucially, all runners consume the *same* versioned prompt templates
   from `prompts/runtime/` that the iOS app bundles — the eval measures
   exactly what ships, or it measures nothing.
4. **Scoring = checks, then judge.** Deterministic checks first (output
   parses, length bounds, examples are in the right language, the
   violated grammar tag is referenced). Then a pinned judge model
   (Claude) grades the case's expectations as a weighted checklist —
   named error found? hallucinated error asserted? model answer correct?
   The score is the checklist total, not a vibe rating; judge prompts
   are versioned beside the case sets.
5. **Scorecard + promotion gates.** Each run emits a per-task ×
   backend × prompt-version scorecard (JSON + markdown) committed under
   `evals/results/`. A feature is enabled on-device only while its
   `apple_fm` score clears both an absolute floor and a fraction of the
   cloud reference (thresholds decided in Phase 6, e.g. ≥ 0.80 absolute
   and ≥ 85% of reference). The gates live in a config file the app
   build reads — the scorecard, not optimism, decides what the
   on-device model is allowed to do, and the UI's "explained locally"
   labeling follows the same config.
6. **The loop itself.** Change a prompt (or bump an OS/model version) →
   run the matrix → diff scorecards → accept or revert. Prompt tuning
   becomes ordinary red-green iteration; on-device regressions after an
   iOS update show up as a scorecard diff, not as user-visible quality
   rot.

**Cost:** judge calls are bursty authoring-time Anthropic usage — ~100
cases × a few cents per judged output per matrix run. Negligible next to
content generation.
