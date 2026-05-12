# 01 — iOS Re-architecture

Status: draft
Owner: solo
Target: ~14–16 weeks to App Store submission

This plan replaces the self-hostable FastAPI web app with a fully offline,
on-device iOS app. The current repo becomes the content-authoring toolchain;
the production runtime is a SwiftUI app powered by Apple Foundation Models.

---

## 1. Context & motivation

The current Maestro stack (FastAPI + MongoDB + Claude API) works but carries
costs that don't fit a personal language-learning tool:

- Every lesson is a paid Claude API call. Cost scales with usage.
- The user must trust a self-hosted server with their data, or trust me to host one.
- A web app is the worst form factor for daily mobile use (no offline, no notifications, no audio polish).
- Operationally, hosting MongoDB + an API for a small user base is overhead with no upside.

Apple Foundation Models (iOS 18.1+, on-device ~3B model with guided generation)
makes it possible to do the lesson-generation step locally on a phone, for
free, with no network. Combined with `SFSpeechRecognizer` (on-device IT/DE),
`NLTagger` (lemmatization/POS), and CloudKit (silent sync without accounts),
the entire runtime collapses to the device.

The trade-off: Foundation Models needs an Apple Intelligence-capable device
(iPhone 15 Pro and newer). That's a ~30% installed base today, ~50% by mid-2026.
Accepted as a constraint — fits a "premium offline tutor" positioning.

---

## 2. Goals & non-goals

**Goals**

- Ship a credible v1.0 to the App Store covering Italian + German at A0–A1.
- Fully offline after install. No accounts, no servers, no network required.
- CloudKit sync for cross-device continuity.
- Freemium: A0 + 2 topic packs per language free; IAP unlocks A1 + remaining packs.
- Content authoring workflow that scales to one solo dev with Claude assistance.

**Non-goals (v1.0)**

- A2+ content (v1.1).
- LLM critique on speaking activities (v1.x).
- Migration from the web app — clean reboot, no data import.
- Android, web, or non-Apple-Intelligence iPhone support.
- Conversation mode / free-form chat (v2.0 idea).

---

## 3. Target architecture

### Runtime (the iOS app)

```
SwiftUI shell
├── Bundle reader            SQLite (read-only, mmap'd) + AAC audio files
├── Lesson engine            schedules activities from skill templates + topic packs
├── Generation               Apple Foundation Models, guided generation via @Generable
├── Scoring                  ported drill scoring + writing rubric + speaking match
├── SRS                      SM-2 ported from src/maestro/vocab/srs.py
├── Vocab discovery          NLTagger + Foundation Models for semantic role
├── Speech                   SFSpeechRecognizer (on-device IT/DE)
├── Sync                     CloudKit private DB, ~4 record types
└── IAP                      StoreKit 2, two non-consumables (it.full, de.full)
```

### Content (this repo, post-refactor)

```
maestro/
├── packs/
│   ├── it/{skills,topics,grammar,base_vocab}/   # YAML sources
│   └── de/{skills,topics,grammar,base_vocab}/
├── audio/                                        # pre-rendered AAC (git LFS)
├── maestro-pack/                                 # Python CLI
│   ├── cli.py                                    # new, top, generate, validate, build
│   ├── generate/                                 # Claude prompts for each artifact type
│   ├── validate/                                 # schema + linguistic sanity
│   └── build/                                    # YAML → SQLite + audio bundle
└── src/maestro/                                  # legacy FastAPI, deleted at end of Phase 5
```

### CloudKit record types

| Type             | Purpose                                                                  |
| ---------------- | ------------------------------------------------------------------------ |
| `UserProfile`    | Level per language, UI prefs, learned-at dates                           |
| `SkillMastery`   | Per-skill confidence, attempts, last seen (one record per skill_id)      |
| `SRSCard`        | Vocab item state: ease, interval, next review, last reviews              |
| `WritingSample`  | Most recent N writing submissions + rubric scores (bounded list)         |

All in the private DB. No public/shared zones. No CloudKit JS / server access.

---

## 4. Phases

Each phase has a goal, scope, deliverables, exit criteria, and risks. Phases
overlap where dependencies allow (Phase 1 app and Phase 1 content run in
parallel; Phase 3 content fill overlaps Phase 4 speaking).

### Phase 0 — Foundations & derisking (weeks 1–2)

**Goal**: prove the three load-bearing assumptions before committing.

**Scope (in)**

- Foundation Models spike: `@Generable` struct for one cloze drill, generate 10 IT A1 drills on `passato_prossimo`, eyeball quality and time on an iPhone 15 Pro.
- Skill template + topic pack YAML schemas, drafted as commented examples in `packs/it/`.
- Port one existing A0 lesson from `src/maestro/lessons/a0_static.py` into the new YAML shape to confirm it survives.
- Xcode project skeleton: SwiftUI app, embed a 2-table SQLite, query it from a screen on cold start.
- `maestro-pack` CLI skeleton: `validate` and `build` commands (no `new` or `generate` yet).

**Scope (out)**

- Any user-facing UI polish.
- Any actual content beyond the one ported A0 lesson.
- IAP, CloudKit, sync, audio.

**Deliverables**

- `packs/it/skills/passato_prossimo.yaml` (hand-authored draft)
- `packs/it/topics/italian_history.yaml` (hand-authored draft)
- `packs/it/a0/` ported A0 lesson(s) in new shape
- `maestro-pack` CLI runnable: `maestro-pack validate packs/`, `maestro-pack build --target ios --out build/maestro.sqlite`
- `maestro-ios/` Xcode project that opens, builds, and reads the bundle
- Foundation Models spike report (markdown): quality samples, latency numbers, gotchas

**Exit criteria**

- A real iPhone 15 Pro generates 10 valid IT cloze drills in <5s with guided generation, no crashes, output usable without manual correction.
- SQLite bundle loads on cold start in <200ms.
- YAML schemas can express one full A0 lesson without "TODO" gaps.

**Risks**

- Foundation Models IT/DE quality is worse than expected → fallback: bundle MLX-quantized open model (Qwen2.5 3B or similar). Costs battery, complicates guided generation.
- Guided generation schema limits hit (max field count, recursion) → fallback: split outputs into multiple smaller generations.
- SQLite bundle access pattern slow → fallback: split into per-skill JSON files lazy-loaded.

---

### Phase 1 — Lesson loop + initial content (weeks 3–6)

**Goal**: end-to-end loop on device for a small slice of Italian, with content authored via CLI.

**Scope (in) — app**

- Lesson lifecycle ported from `src/maestro/lessons/lifecycle.py` (state machine: queued → in-progress → scored → complete).
- Activity types implemented: cloze, multiple choice, writing, listening.
- Drill scoring ported from `src/maestro/lessons/drill_scoring.py`.
- Writing rubric scoring on-device via Foundation Models (structured output: 4–5 dimensions, 1–2 sentence comment).
- SM-2 SRS port from `src/maestro/vocab/srs.py`.
- Vocab discovery in rendered text: `NLTagger` lemmatize → look up in bundle → click for definition. (No semantic role pass yet — that's Phase 3.)
- Audio playback of pre-rendered prompts.

**Scope (in) — content (parallel track)**

- `maestro-pack new --skill ... --lang it`: Claude drafts a skill template YAML.
- `maestro-pack new --topic ... --lang it`: Claude drafts a topic pack YAML.
- `maestro-pack validate`: schema + linguistic sanity (vocab exists in base list, gender agreement check, no English bleed).
- 5 IT A0 skill templates hand-authored with Claude assist.
- 3 IT topic packs hand-authored with Claude assist.

**Scope (out)**

- Profile / progress UI (Phase 2).
- CloudKit (Phase 2).
- IAP (Phase 2).
- Speaking (Phase 4).
- German content (Phase 3).

**Deliverables**

- iOS app that, on a real device, plays a full lesson from the bundle and scores it.
- 5 IT skill templates + 3 IT topic packs in `packs/it/`.
- `maestro-pack new` and `maestro-pack validate` working with Claude integration.

**Exit criteria**

- A user can complete a 6-activity lesson on Italian `passato_prossimo` with `italian_history` as the topic context, get scored, and see their drill answers marked.
- Writing activity returns rubric + comment in <10s.
- Vocab words underline correctly in rendered text and show definitions on tap.

**Risks**

- Vocab discovery accuracy on inflected forms (IT verbs in particular) → mitigate with NLTagger lemma + manual override list in topic packs.
- Foundation Models rubric output drift → guided generation should prevent shape drift; quality drift caught by L1 review in Phase 3.
- Lesson lifecycle port is more invasive than expected → keep the Python version as reference, don't rewrite the state machine, just transcribe it.

---

### Phase 2 — Profile, sync, IAP, onboarding (weeks 7–9)

**Goal**: a first-time user can install, onboard, choose a language, do lessons, and have their progress survive a reinstall.

**Scope (in)**

- CloudKit container setup, private DB, record types listed in §3.
- Profile management: read on launch, write on each lesson completion, conflict resolution policy (last-write-wins on `SkillMastery`, server-merge on `SRSCard` next-review).
- Onboarding flow: language pick → quick placement (~5 questions → A0 or A1 entry point) → first lesson.
- Settings screen: language, UI language, audio voice, notification opt-in, delete-all-data (nukes private zone).
- IAP plumbing: StoreKit 2, two non-consumables (`it.full`, `de.full`), purchase + restore, paywall sheet when user hits A1 or pack 3.
- Family Sharing enabled on products.

**Scope (out)**

- Skill tree visualization (post-MVP).
- Push notifications (post-MVP, but capture opt-in for future).
- Speaking (Phase 4).
- Admin / debug screens.

**Deliverables**

- App boots, onboards, and tracks progress across launches.
- Reinstall on a second device → CloudKit pulls progress, user picks up where they left off.
- Buying an IAP unlocks A1 + remaining topic packs locally; restore works.

**Exit criteria**

- Cold install → first lesson in <60s of taps.
- Reinstall on a second device → progress visible within 10s of first launch.
- Paywall fires at the right moments, both IAPs purchasable and restorable in TestFlight sandbox.

**Risks**

- CloudKit schema migrations are painful → finalize schema at start of phase, version every record type from day one.
- IAP review can reject for "subscription confusion" — make non-consumable nature obvious in copy.
- App Store guidelines on freemium → check that A0 alone feels like a real product, not crippleware.

---

### Phase 3 — Content fill (weeks 10–12)

**Goal**: enough content to feel like a real course in both languages.

**Scope (in)**

- Skill templates: ~15 per language covering A0 + A1 grammar inventory. Inventory to be locked at start of phase as a checklist (articles, gender/number, present tense, basic prepositions, possessives, past participles, simple past, etc.).
- Topic packs: ~10 per language. Mix of practical (food, travel, family) and motivational (history, music, cinema).
- Base vocab lists: A0 + A1 frequency lists per language (~1500 words each).
- Grammar reference markdown: short page per skill, hand-edited from Claude drafts.
- Audio: pre-render every fixed prompt and dialogue line via Azure/ElevenLabs, store in `audio/`, reference by stable IDs in YAML.
- Vocab semantic-role pass: extend NLTagger discovery with a Foundation Models call that tags each new word with its role in the sentence (subject, object, adverb, etc.) for richer hover cards.
- L1 speaker review: hire (or convince) one IT and one DE native speaker to do a 4–6 hour review pass on the final content. Build a feedback ingest workflow (review YAML inline, file issues, batch-fix).

**Scope (out)**

- A2 grammar.
- Cultural deep-dives beyond what fits in a topic pack.
- Audio for dynamically generated content (writing prompt readbacks, etc.) — runtime AVSpeechSynthesizer is fine for those.

**Deliverables**

- `packs/{it,de}/skills/` full A0–A1 inventory complete.
- `packs/{it,de}/topics/` 10 packs each.
- `packs/{it,de}/grammar/` markdown reference per skill.
- `audio/` populated for both languages.
- Authoring cost tally (Claude tokens + Azure/ElevenLabs minutes) for next-time budgeting.

**Exit criteria**

- All skill templates pass `maestro-pack validate` with no warnings.
- L1 review pass complete, blocking issues fixed.
- Bundle builds to a single `maestro.sqlite` + `audio.zip` totaling <80 MB.

**Risks**

- L1 review uncovers systemic generation issues → Phase 3 may extend by 1–2 weeks; budget the slack.
- Audio pre-render cost runs over → ElevenLabs is the expensive option; Azure neural voices are 5–10× cheaper and good enough for A0–A1.
- Content quality varies by topic → adopt a per-pack QA checklist (vocab realness, gender, register consistency, cultural accuracy).

---

### Phase 4 — Speaking activity (weeks 13–14)

**Goal**: STT-driven speaking activity with confidence rendering, no LLM in the loop.

**Scope (in)**

- `SFSpeechRecognizer` on-device for IT and DE.
- Speaking activity type added to skill template `activity_plan` schema.
- Activity runtime: show target sentence (optionally with one word redacted as a prompt) → record → transcribe → token-level fuzzy match against target → render result with per-token confidence as a color gradient.
- Microphone permission flow, settings toggle to disable speaking activities.
- Pre-rendered "example pronunciation" audio for each speaking item (already covered by Phase 3 audio pipeline).

**Scope (out)**

- LLM critique of pronunciation.
- Free-form speaking (talk about a topic).
- Conversation mode.

**Deliverables**

- Speaking activity playable end-to-end in the app.
- 1–2 speaking items added to each existing skill template (regenerate bundle).

**Exit criteria**

- On a real device, speaking a target sentence transcribes correctly >90% of the time at clear native-like pace; mismatched words highlight correctly.
- No app freeze or crash on permission denial / no-microphone simulator.

**Risks**

- IT/DE on-device STT quality is uneven by accent → ship with a "tap to hear correct" fallback so user is never stuck.
- Permission flow is the worst part of any iOS app → put a friendly explainer screen before the system prompt.

---

### Phase 5 — TestFlight & launch (weeks 15–16)

**Goal**: ship to the App Store.

**Scope (in)**

- Internal TestFlight build, dogfood for 3–5 days.
- Friends-and-family external TestFlight cohort (~10 testers, 1 week).
- Crashlytics / MetricKit wiring (or just MetricKit if avoiding third-party).
- App Store assets: icon, screenshots (5 per language locale), preview videos optional, descriptions in EN/IT/DE.
- Privacy nutrition label (essentially: nothing collected, all on-device, CloudKit private DB).
- IAP review submission with screenshots of paywall.
- Retire `src/maestro/` FastAPI app from this repo (move to a `legacy/` branch or delete after confirming nothing depends on it).

**Scope (out)**

- Press / launch marketing (separate effort).
- Localizing the app UI beyond EN/IT/DE.

**Deliverables**

- App Store submission accepted.
- `legacy/` branch with old FastAPI code archived.
- This repo's `main` contains only authoring + iOS code.

**Exit criteria**

- Approved by App Store review.
- TestFlight feedback addressed (or filed as v1.1 issues).
- README updated to describe the new architecture.

**Risks**

- App Store rejection on freemium / IAP wording → resubmit, common.
- Foundation Models API changes between iOS minor versions → pin to a tested SDK level, monitor WWDC '26 for breaking changes.

---

## 5. Deferred / post-v1.0

| Item                                 | Target  |
| ------------------------------------ | ------- |
| A2 content (both languages)          | v1.1    |
| LLM critique on speaking             | v1.2    |
| Push notification reminders          | v1.1    |
| Skill tree visualization             | v1.1    |
| iPad / Mac Catalyst polish           | v1.1    |
| Conversation mode (free-form chat)   | v2.0    |
| Third language (Spanish? French?)    | v2.0    |
| Apple Watch vocab review             | v2.x    |

---

## 6. Cross-cutting risks

- **Apple Intelligence device floor** restricts addressable market. Accepted.
- **Foundation Models behavior changes** between iOS versions. Mitigation: keep a "golden lesson" test set the CLI can run against a connected device (XCTest) to catch regressions before App Store submission.
- **Solo dev bandwidth** — content fill (Phase 3) is the slowest part. The CLI must be sharp before Phase 3 starts; budget Phase 1 generously so Phase 3 doesn't blow up.
- **L1 reviewer availability** — find both reviewers before Phase 3 starts, not during.
- **Bundle size growth** — track per-phase; if approaching 200 MB, consider on-demand download for non-core topic packs (architectural deviation, hopefully avoidable).

---

## 7. Open decisions

These don't block starting Phase 0 but need answers before the phase they affect.

| Question                                                       | Decide by    |
| -------------------------------------------------------------- | ------------ |
| Exact A0+A1 grammar inventory per language (checklist)         | Start of Ph3 |
| Topic pack inventory for launch (which 10 per language?)       | Start of Ph3 |
| Bundle IAP product as third SKU, or just two language SKUs?    | Start of Ph2 |
| Placement test design (5 questions? adaptive?)                 | Start of Ph2 |
| Crash reporting tool (MetricKit-only vs Sentry)                | Start of Ph5 |
| L1 reviewers identified                                        | Mid Ph2      |

---

## 8. Next step

Break Phase 0 into work items (issues / TODOs) so the spike can start. The
three concrete starting actions are:

1. Foundation Models guided-generation spike on iPhone 15 Pro hardware.
2. Schema drafts for `SkillTemplate` and `TopicPack`, plus port one A0 lesson.
3. SQLite bundle reader spike in a bare Xcode project.

Phase 0 work items will live in a follow-up doc or issue tracker.
