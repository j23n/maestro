# 04 — Product-readiness audit (2026-07-18)

Status: findings report
Scope: what stands between the current repo and a polished TestFlight v1.
Method: full code audit of `authoring/`, `spec/` + `packs/`, `core/`,
`ios/`, `evals/` + `prompts/runtime/`, cross-checked against
`03-implementation-plan.md` and `decisions.md`, plus an end-to-end
walkthrough of one concrete flow (shipping a themed "Ferragosto" pack).

The one-paragraph verdict: **the deterministic middle of the machine is
real and well-tested — the two ends are missing.** Pack build → core
folds/composer/scoring → conformance vectors is genuinely solid. But the
*input* end (content at volume, audio, images, non-drill item types,
quality validators) and the *output* end (a buildable iOS app, pack
distribution, backup, onboarding) are absent or scaffold-only. The eval
loop is a working skeleton that has never measured anything real.

---

## 1. The Ferragosto walkthrough — where a themed pack breaks today

Suppose you want to ship a small cultural pack for Ferragosto (Aug 15):
a reading about the holiday, a beach-vocabulary drill set, a listening
dialogue at the station, a photo of a chiusa-per-ferie sign. Step by
step:

1. **Author it.** `generate` only accepts `--gp <grammar_point>`
   (`authoring/cli.py:29`, `generate.py:69-84`) and only drafts
   *drills*. There is no theme-, scenario-, or vocab-scoped generation,
   and no generator at all for readings, listenings, dialogues,
   speaking prompts, writing prompts, or grammar refs. A themed pack is
   100% hand-written YAML. Adding a `ferragosto` scenario also means
   editing `spec/it/scenarios.yaml` (IDs are forever — fine, but there
   is no "seasonal/optional" concept in the spec; a holiday scenario
   permanently enters the unlock DAG the composer draws from).
2. **New vocab.** *ferragosto, spiaggia, ombrellone* aren't in the
   393-lemma list. You add them to `spec/it/vocab.yaml` by hand; no
   tooling checks your drill text against the leveled list anyway (the
   vocab-level validator is unimplemented; `build_pack.py:11-12` says
   vocab is unchecked).
3. **Validate.** Only schema shape, duplicate IDs, and evidence-ref
   resolution run. Nothing checks that the Italian is correct, the
   answer key is solvable, the cloze has no defensible second answer,
   or the vocab is level-appropriate — all four planned quality gates
   (adversarial pass, solvability, vocab constraint, morphology
   heuristics) are unbuilt.
4. **Review.** `maestro-pack review` loads **drills only**
   (`review.py:81`); your Ferragosto reading and listening never appear
   in the queue. No context panel, no release diff, no audio or image
   preview, no keyboard triage.
5. **Media.** The pack SQLite has **no `media` table**
   (`build_pack.py:34-72`) even though the plan (§4) requires one. The
   listening ships `audio: null`. Your photo has nowhere to go: no
   `images/` directory exists (two `image:` fields in
   `scenarios.yaml` already dangle), no schema field on any item
   references an image, the core exposes no media lookup, and no iOS
   view renders one. Audio is the same story one layer earlier: there
   is no `generate-audio` command, no TTS code anywhere, and the iOS
   listening view has a `TODO` where playback should be
   (`SessionView.swift:140`).
6. **Release.** `release` writes `build/release/<version>/` with the
   bundle + `release.json` (sha256 only — integrity, not a signature).
   Upload is manual; nothing creates a GitHub release or maintains a
   version index.
7. **Deliver to the user.** `PackManager.swift` can fetch + verify +
   atomic-swap — but it is never instantiated by any view; there is no
   pack UI at all. Today the only way a user gets new content is a new
   TestFlight build with the pack re-bundled. Also note: there is
   **one monolithic pack per language**. "A Ferragosto pack" as an
   add-on doesn't exist as a concept — it's just the next version of
   the whole Italian pack.
8. **Experience it.** The learner cannot choose it. The composer alone
   decides what a session contains (weakness-weighted, phase-gated);
   there is no lesson browser, no "featured/seasonal" surfacing, no
   way to say "do the Ferragosto lesson today". Time-sensitive content
   has no discovery mechanism.

So a Ferragosto pack today = hand-written YAML, reviewed partly outside
the tool, silent on quality, silent (no audio), invisible (no images),
manually uploaded, unreachable in-app, and unselectable by the learner.
Every step needs a piece that doesn't exist yet.

---

## 2. Findings by area

### A. Ship-blockers for any TestFlight build (P0)

1. **The iOS app cannot build.** No `.xcodeproj`/`Package.swift`, no
   Info.plist (mic + speech-recognition usage strings missing → crash /
   rejection), no asset catalog, icons, or launch screen. UniFFI
   bindings and the xcframework are generated only by macOS-only
   scripts; nothing is checked in. `CoreBridge` force-unwraps the
   bundled pack path. All 7 Swift files carry ⚠️ UNTESTED banners and
   have never been compiled. The two Mac spikes (core embed,
   SpeechAnalyzer fairness) are still the gating unknowns.
2. **Content is ~2% of target.** 17 items (14 drills, 2 readings,
   1 listening) covering 8 of 351 grammar points, A0/A1 only. No A2
   items and *zero A2 scenarios in the spec*. The plan's bar is ~750
   drills / ~50 readings / ~50 listenings before "no out-of-content
   moments".
3. **No audio anywhere.** No render pipeline (`generate-audio`
   unimplemented, no Azure/ElevenLabs code), no `media` table, no
   playback code, no AVSpeechSynthesizer fallback (a TODO). A language
   app whose listening exercises are silent text is not shippable.
4. **Three of the seven planned item types exist.** Missing entirely
   (no schema, no generator, no build path, no UI): vocab items,
   speaking prompts, writing prompts, grammar-reference pages
   (`pack_schemas.py` defines only Drill/Reading/Listening). Knock-on
   effects:
   - **The vocab/SRS loop is dead end-to-end**: SM-2 state is tracked
     in the core, but there are no vocab items in packs, no vocab
     table in the bundle (the 393 lemmas are never written by
     `_embed_spec`), no vocab slot in composed sessions
     (decisions.md #16), and no review UI. Flashcards — table stakes
     for a language app — don't exist.
   - **Speaking has a scorer but no content**: `align.rs` is done and
     `SpeakingPracticeView` exists (orphaned — nothing navigates to
     it), but there is no speaking-prompt item type to feed either.
   - **Writing feedback is prompts-only**: no writing-prompt items, no
     capture UI, no pending-feedback queue anywhere (see C3).
5. **Pack update safety is unimplemented on all three layers.**
   "tombstone" appears in zero lines of `authoring/` or `core/src/`:
   build writes no tombstones table, the core never reads one, and
   there are no schema-version compat checks (`read_manifest` reads
   `schema_version` and never compares it). The plan's Phase 8 exit —
   release → in-app update → history intact — cannot be exercised.
6. **No backup/restore.** `export_log`/import are absent from the core
   despite being in the planned API surface; no settings/backup UI. A
   tester who loses their phone loses everything, and the Phase 8
   two-device drill is impossible.
7. **First-run experience doesn't exist.** No onboarding, no placement
   (an A1-capable learner must grind from the A0 DAG root), no goal
   setup, no notifications/streak/daily-reminder mechanics. For a
   "polished v1" these are product-defining, not nice-to-haves.

### B. Authoring & review experience

1. **Generate is single-type, single-axis.** Drills only, one grammar
   point at a time, grammar evidence only (never function/vocab
   targeted). Scaling to 750+ drills means hundreds of manual
   invocations; readings/listenings/dialogues stay hand-written.
2. **The four quality validators are missing** (adversarial answer
   pass, answer-key solvability, vocab-level constraint, morphology
   heuristics). For an LLM-drafted bank these are the defense the plan
   leans on ("content quality at volume" is top-3 risk #3). Validate
   today ≈ schema + ID uniqueness + ref integrity.
3. **Review UI covers 3 of 6 planned workflows, drills only.**
   Readings/listenings are unreviewable in-tool. Missing: context
   panel (spec cell material beside the item — loaded but never
   rendered), release diff, L1-reviewer mode, audio preview, keyboard
   triage + defer. Coverage dashboard is reviewed-drills-per-GP only,
   not the grammar × level × item-type matrix, with no per-cell
   generate command.
4. **Release is unsigned and undistributed.** sha256 ≠ signature (no
   authenticity); publishing is a manual upload with no automation, no
   version index/catalog endpoint, and `release` will silently
   overwrite an existing version directory. `build` emits no per-cell
   coverage report (plan §Phase 2).
5. **Cross-language normalizer parity is convention, not test.**
   `build_pack._normalize` hand-mirrors `core/src/normalize.rs`;
   `pack_compat` in CI round-trips canonical answers (partial guard),
   but no direct parity test exists and drift on distractor keys would
   be silent.
6. **YAML comments are destroyed** by any tool-driven rewrite of a
   hand-authored file (known, decisions.md #20) — lossy once curated
   files carry rationale comments.

### C. LLM layer & eval loop

1. **The harness has never measured anything real.** No committed
   scorecards (`evals/results/` doesn't exist), no
   `build/gates_resolved.json` ever produced, the anthropic runner and
   judge have never been invoked live, and the Apple FM runner is an
   unbuilt, untested Swift scaffold. The entire "measured, not
   optimistic" premise is still a promise. Gate thresholds are
   placeholders by their own comment.
2. **"The eval measures exactly what ships" is currently false.** No
   Swift code loads `prompts/runtime/*.yaml`; `LLMBackend.complete`
   takes pre-rendered strings. Until the app bundles and renders the
   same templates, prompt/eval/app can silently diverge.
3. **The runtime LLM contract is missing from the core.** No
   feedback-job request/response types, no pending queue, no fold-back
   path (`feedback_source` is defined on events but nothing produces
   it). iOS has no key-entry/Settings/Keychain code (promised in a
   comment), no privacy-ledger store or UI (only a Codable struct),
   and the Anthropic backend ignores HTTP errors.
4. **Judge hygiene**: judge model = reference model (claude-sonnet-5
   hardcoded in both), judge prompt is an inline unversioned f-string,
   scorecards don't record judge metadata — contra plan §11.4.
5. **Case sets are 10 + 4 vs ~50/task**; `mistake_explanation` has no
   `must_not_claim` fields so its hallucination gate is structurally
   inert; no seeded-error generation tooling; `speaking_feedback` is
   0% (expected for Phase 7, but the speaking feature ships without
   any eval).
6. **Leftover second eval system.** `evals/compare.py` (808 lines) +
   `results.jsonl`/`items.jsonl` are pre-rewrite legacy (Mar-2026
   data, references a deleted `tests/eval/` path) that survived the
   cleanup sweeps and will confuse anyone asking "which harness is
   real". Delete or move to an archive.
7. **`--resolve-gates` exits 0 on an empty results dir**, emitting an
   all-disabled gates file with no warning that no run ever happened.

### D. Media & images (no concept exists)

1. **Images are a dangling gesture**: `scenarios.yaml` has 2 `image:`
   fields pointing at a nonexistent `images/` directory; no item
   schema, build table, core API, review preview, generation step, or
   SwiftUI view involves images. If lessons should have pictures
   (scene-setting art, vocab illustrations), the whole vertical needs
   designing: an authoring step (generation via an image model, or
   licensed/own photos — plus a human-review gate in the review UI), a
   `media` table (or sidecar asset dir + manifest hashes) in the
   bundle, size budgets, core/shell lookup, and rendering.
2. **Audio is the same vertical one step further along** (fields
   exist, everything else missing): needs `generate-audio` (Azure
   neural it-IT per plan), media storage, review-UI preview +
   re-render flagging, core/shell lookup, playback + system-TTS
   fallback, and cache/size policy.
3. **Bundle size policy undecided** — blobs in SQLite vs sidecar files,
   what a 50-listening pack weighs, whether images/audio download
   lazily. Decide before authoring media at volume.

### E. Core (smaller, real gaps)

1. Missing vs plan: `export_log`/import, tombstone handling,
   update-compat checks / `pack_status`, LLM job queue, media lookup.
2. **Per-modality CEFR profile is not per-modality** — one global
   estimate + raw attempt counts; no production-confidence caps.
3. **Conformance vectors pin only the folds** (3 vectors). No golden
   vectors for the composer, scoring/normalization, or the alignment
   scorer — the portability guarantee doesn't yet cover the parts a
   second implementation would most likely get wrong. README claims
   session-plan coverage that doesn't exist.
4. Time budget is binary (≤5 min vs else) with hardcoded slot counts —
   fine for v1, but "15-minute session" is item-count folklore.
5. Doc drift: `core/README.md` and `lib.rs` still say FSRS and
   "Phase 3 adds folds"; code is SM-2 (deliberate, decisions.md #5)
   and folds/composer already shipped.

### F. Product polish (the "polished" in polished v1)

1. Session player collapses every drill type into one view — no
   dedicated cloze/match/transform/grammar-card renderers (match items
   can't render at all; there's also no match item type authored).
2. Errors are swallowed (`try?` throughout); no retry/error surfaces;
   no empty states beyond pack-open failure; progress is a flat list,
   not the planned can-do tree.
3. No localization infrastructure — UI strings are hardcoded
   English/Italian literals.
4. No accessibility/Dynamic Type/dark-mode pass.
5. TestFlight logistics not in repo: privacy policy, App Privacy
   ("data not collected" — easy win given the architecture), support
   URL, screenshots.
6. CI has no macOS job — once an Xcode project exists, add at least a
   compile check so the Swift shell can't silently rot again.

---

## 3. Suggested order to a polished TestFlight v1

1. **Mac Spike A/B** (unchanged from decisions.md): Xcode project,
   xcframework, bundle seed pack, compile-fix, SpeechAnalyzer fairness
   verdict. Everything else stays speculative until this lands. Add
   Info.plist permission strings, icon, launch screen while there.
2. **Close the content-type gap in schemas first** (vocab items,
   speaking prompts, writing prompts, grammar refs + a media table with
   audio/image columns) — schema decisions gate authoring, core, and UI
   work alike, and IDs/tables are forever.
3. **Audio vertical** (`generate-audio` → media table → review preview
   → iOS playback + TTS fallback). Decide the image question at the
   same time since it shares the whole pipeline.
4. **Authoring at volume**: extend `generate` to all item types +
   scenario/theme scoping; add the four quality validators; extend the
   review UI to all types + context panel + release diff. Then run the
   Phase 7 content fill.
5. **Runtime completeness**: tombstones + compat checks + `export_log`
   in core; pack-update UI, settings/backup, onboarding + placement,
   vocab review loop, notifications in the app.
6. **First real eval run**: build the Apple FM runner on the Mac, run
   the matrix live, commit scorecards, pin thresholds and the judge,
   make the app actually load `prompts/runtime/` and the gates file.
7. **Hygiene**: delete `evals/compare.py` + jsonl leftovers, fix
   core/README drift, add composer/scoring/alignment conformance
   vectors, normalizer parity test, macOS CI job.
