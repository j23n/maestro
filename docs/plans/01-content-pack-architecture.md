# 01 — Content-pack architecture

Status: draft
Owner: solo
Target: ~13–17 weeks to a v1.0 covering Italian + German, A0–A2, web + PWA

Maestro is built around **content packs**: hand-curated, Claude-authored
banks of drills, passages, dialogues, and prompts that are produced at
authoring time and consumed at runtime. Lessons are **selected and
composed** from those banks based on the learner's state; they are not
generated on demand by a language model. The runtime keeps an LLM in the
loop only for **grading and explanations** when the learner makes a
mistake or submits writing.

The same content packs power the web app and any future client (PWA,
native iOS, native Android). The web app is the first runtime; the PWA
follows in the same v1.0.

---

## 1. Concepts & vocabulary

The plan uses a small vocabulary throughout. Definitions live here so
later sections stay compact.

**Content pack**. A versioned, hand-reviewed YAML directory under
`packs/<lang>/...` containing all the artifacts (skills, functions,
topics, drills, readings, listenings, writing prompts, grammar refs,
vocab) for one language. Packs are committed to git and built into a
runtime bundle.

**Bundle**. A single sealed SQLite file produced by
`maestro-pack build`. It contains every artifact in a content pack in a
form optimized for read-only lookup. It is what the web app, the PWA,
and (later) native apps actually read at runtime.

**Skill** (a.k.a. skill card). A single grammar competence — e.g.
`passato_prossimo`, `articoli`, `gender_agreement`. Skills are the
backbone of the curriculum. A skill card declares its CEFR level,
prerequisites, sub-skills, and a lesson template.

**Sub-skill**. A finer-grained slice of a skill that mastery is tracked
against — e.g. `passato_prossimo` has sub-skills `aux_avere`,
`aux_essere`, `irregular_participles`. Drill banks tag each item with
a sub-skill so weakness-weighted selection can target the right slice.

**Communicative function** (CF, or "function pack"). A real-world thing
a learner needs to *do* with the language — e.g. `ordering_food`,
`asking_directions`, `introducing_oneself`. Mapped to the CEFR
functional inventory. Each function pack lists the grammar skills it
draws on, useful phrases, dialogues, and practice scenarios.

**Topic pack**. A semantic theme — e.g. `food`, `italian_history`,
`travel`. Topic packs supply vocab, entities, events, reading passages,
listening dialogues, and cultural notes that get pulled into lessons.
Topic packs are language-tied; the same theme exists separately for IT
and DE.

**Lesson**. A user-facing learning session, ~10–12 activities, ~12–15
minutes. A lesson is composed at lesson start by the lesson selector:
it picks a skill (or function), picks a topic, and assembles activities
from the relevant banks following the skill's lesson template.

**Activity**. The atomic unit inside a lesson. Activity types: `drill`,
`reading`, `listening`, `speaking`, `writing`, `vocab_review`, `grammar`
(card), `info`. Each activity type has its own renderer and scorer.

**Drill**. A short objective item with one correct answer. Drill
variants:

- `cloze` — fill the blank in a sentence (`Ieri ___ (mangiare) la pizza`).
- `fill_blank` — fill the blank with a free-form answer.
- `multiple_choice` — pick one of N options.
- `match` — match terms to translations or definitions.
- `transform` — rewrite a sentence applying a rule (singular → plural).

**Drill bank**. A YAML collection of drill items belonging to one
skill, tagged with sub-skill, topic, and difficulty. Banks are the
source pool the selector draws from. Target size: ~30 items per skill.

**Reading passage**. A short prose passage (50–200 words) leveled at
A1 or A2, tied to a topic pack, with comprehension questions and an
inline glossary. Banks of ~5 per topic per level.

**Listening dialogue**. A scripted dialogue with pre-rendered audio,
leveled at A1 or A2, tied to a topic pack, with comprehension
questions. Banks of ~5 per topic per level.

**Writing prompt**. A short instruction inviting a 40–80 word written
response, tied to a skill (so it exercises that grammar) and a topic
(so it has something to be about). Banks of ~3 per skill.

**Vocab entry**. A single word in the base vocab list with metadata:
lemma, POS, gloss in English, CEFR level, frequency rank. The base
vocab list is the canonical source for which words can appear in
generated content; anything outside the list must be glossed in place.

**Base vocab list**. The frequency-ranked list of words a learner is
expected to know by a given level. Per language, ~1500 entries for
A0+A1+A2.

**Grammar reference**. A short markdown page per skill, hand-edited
from a Claude draft, that explains the grammar point. Rendered as the
`grammar_card` activity inside lessons.

**Mastery**. A per-(user, skill) and per-(user, sub-skill) score in
[0, 1] that reflects how reliably the user gets that skill correct.
Updated on every activity submission. Drives weakness-weighted
selection.

**SRS** (spaced repetition system). The SM-2 algorithm applied to vocab
items: each user has an SRS card per vocab entry that tracks ease,
interval, and next-review date. `vocab_review` activities are scheduled
by the SRS.

**Lesson selector**. The runtime component that, given a user's state,
picks the next lesson: which skill (or function), which topic, which
specific drill IDs from the bank, which reading passage, which
listening, which writing prompt. Deterministic; no LLM involved.

**LLMGrader**. The runtime interface for the one place an LLM still
runs: explaining mistakes and grading free-form writing. The v1.0
implementation calls Claude via the existing `src/maestro/llm.py`
wrapper through a server endpoint.

**Authoring CLI** (`maestro-pack`). The Python CLI that uses Claude to
draft new artifacts, validate existing ones, render audio, and build
the runtime bundle.

**CEFR level**. Common European Framework reference level. Maestro
covers A0 (pre-A1, true beginner) through A2.

---

## 2. Goals & non-goals

**Goals**

- Author a complete A0–A2 content library for Italian and German.
- Web app reads content from a sealed bundle, not from a runtime LLM.
- Web app installs as a PWA with offline support.
- `maestro-pack` CLI uses Claude to draft and refresh content, with
  git as the canonical store and YAML as the authoring format.
- LLM in the loop for grading and explanations at submission time,
  served via your server calling Claude, behind an interface that
  can be swapped for on-device models later.
- Personalize via selection: weakness-weighted drills, topic and
  function preference, SRS resurfacing, anti-repetition, name
  interpolation.

**Non-goals (v1.0)**

- B1 and above.
- Native iOS / Android apps. PWA installable on iOS Safari and Chrome
  Android is the v1.0 mobile path.
- Lesson generation at runtime. Lessons are picked, not invented.
- Conversation mode / free-form chat with the tutor.
- On-device LLM at launch. The interface supports it; switching it
  on is a later phase.

---

## 3. Architecture

### 3.1 Authoring time

```
maestro/
├── packs/
│   ├── it/{skills,functions,topics,grammar,base_vocab}/   # YAML, git-versioned
│   └── de/{skills,functions,topics,grammar,base_vocab}/
├── audio/                                        # pre-rendered AAC, git LFS
├── maestro_pack/                                 # Python package
│   ├── cli.py                                    # entry point
│   ├── schemas/                                  # Pydantic models
│   ├── generate/                                 # Claude prompts per artifact
│   │   ├── skill.py
│   │   ├── topic.py
│   │   ├── function.py
│   │   ├── drill_bank.py
│   │   ├── reading_passage.py
│   │   └── listening_dialogue.py
│   ├── validate/                                 # schema + linguistic checks
│   ├── build/                                    # YAML → SQLite bundle
│   └── audio/                                    # Azure/ElevenLabs render
└── src/maestro/                                  # web app
```

`maestro-pack` CLI surface:

| Command | What it does |
| --- | --- |
| `new --skill X --lang it` | Claude drafts a skill card YAML |
| `new --function X --lang it` | Claude drafts a function pack YAML |
| `new --topic X --lang it` | Claude drafts a topic pack YAML |
| `generate-drills --skill X --topic Y --count 30` | Claude generates a drill bank |
| `generate-reading --topic X --level a2 --count 5` | Claude generates reading passages + comp Qs |
| `generate-listening --topic X --level a2 --count 5` | Claude generates listening dialogues + comp Qs |
| `generate-audio --pack X` | Renders audio assets via Azure/ElevenLabs |
| `validate [pack...]` | Schema + linguistic sanity (vocab realness, agreement, register) |
| `build --target sqlite --out build/maestro.db` | Produces sealed bundle |
| `diff <old> <new>` | Compares two bundles for review |

### 3.2 Runtime

```
Browser / PWA / future native shell
├── HTML/CSS UI                     htmx + Jinja templates
├── Bundle reader                   server-side Python sqlite3 (web);
│                                   wa-sqlite or sql.js (offline PWA)
├── Lesson selector                 picks next lesson + activity variants
├── Activity renderer               per-activity templates
├── Activity scorer                 rule-based for objective answers
├── LLMGrader interface             explanations + writing rubric
│   └── ClaudeAPIGrader             POST → server → Claude
├── SRS                             SM-2 (src/maestro/vocab/srs.py)
└── User state                      Mongo (server) for web
```

### 3.3 Data flow

```
authoring:
  Claude API + maestro-pack CLI → packs/*.yaml → git
  packs/*.yaml + audio/ → maestro-pack build → bundle.sqlite (versioned)

runtime:
  bundle.sqlite (deployed alongside web app, served to PWA via Cache API)
    → lesson selector picks activity variants from banks
    → renderer produces page
    → user submits
    → rule-based scorer determines correctness
    → if explanation needed: LLMGrader.explain(mistake) → server → Claude
    → SRS + mastery update → Mongo
```

### 3.4 LLM grading contract

A single Python interface:

```python
class LLMGrader(Protocol):
    async def explain_mistake(
        self,
        activity: ActivityContext,
        user_answer: str,
        correct_answer: str,
        skill: SkillRef,
        lang: Lang,
    ) -> Explanation: ...

    async def grade_writing(
        self,
        prompt: str,
        submission: str,
        rubric: WritingRubric,
        lang: Lang,
    ) -> WritingFeedback: ...
```

The v1.0 implementation, `ClaudeAPIGrader`, calls Claude via the
existing `src/maestro/llm.py` wrapper. Future implementations (browser
`window.ai`, on-device native models) slot in behind the same
interface without UI changes.

### 3.5 Personalization

All selection-time, all deterministic:

- **Name + light interpolation**. Templates have `{name}` slots filled
  by the user's profile.
- **Weakness-weighted drill selection**. When the selector picks N
  drills from a bank of M, it weights candidates by
  `1 / (mastery_per_sub_skill + ε)`. Sub-skills the user is weak on
  are more likely to appear.
- **Topic + function preference**. Onboarding captures the user's
  topic and function preferences; the selector biases lesson
  composition toward chosen packs.
- **Avoid repetition + SRS resurfacing**. Drill IDs are logged on
  use; the selector excludes recent IDs within a window. SM-2
  schedules vocab resurfacing in `vocab_review` activities.

---

## 4. Content schema (sketch)

### Skill card

```yaml
id: passato_prossimo
lang: it
level: A2
title: { en: "Past tense — passato prossimo", it: "Il passato prossimo" }
prerequisites: [present_essere_avere, gender_agreement]
sub_skills:
  - { id: aux_avere,             weight: 0.5 }
  - { id: aux_essere,            weight: 0.3 }
  - { id: irregular_participles, weight: 0.2 }
lesson_template:
  - { kind: grammar_card, ref: grammar/passato_prossimo.md }
  - { kind: drill,        count: 6, source: drill_banks/passato_prossimo }
  - { kind: reading,      level: A2, source: topic_chosen }
  - { kind: listening,    level: A2, source: topic_chosen }
  - { kind: writing,      prompt_pool: writing_prompts/passato_prossimo }
  - { kind: vocab_review, count: 5 }
```

### Drill bank entry

```yaml
- id: pp_avere_001
  skill: passato_prossimo
  sub_skill: aux_avere
  topic_tags: [general, food]
  difficulty: 1
  type: cloze
  prompt: "Ieri ___ (mangiare) la pizza con i miei amici."
  answer: "ho mangiato"
  distractors: ["sono mangiato", "ho mangiare", "mangiavo"]
  hint: "verb: mangiare (avere aux), 1st person singular"
```

### Function pack

```yaml
id: ordering_food
lang: it
level: A1
related_skills: [present_tense, polite_expressions, articles]
dialogues: [...]
useful_phrases: [...]
practice_scenarios: [...]
```

### Topic pack

```yaml
id: italian_history
lang: it
level_floor: A1
vocab: [...]
entities: [...]
events: [...]
dialogues: [...]
reading_passages: [...]
listening_dialogues: [...]
cultural_notes: [...]
```

### Reading passage entry

```yaml
- id: hist_read_001
  topic: italian_history
  level: A2
  text_it: "Garibaldi sbarcò in Sicilia nel 1860..."
  glossary: [...]
  questions:
    - prompt: "In che anno Garibaldi sbarcò in Sicilia?"
      type: short_answer
      answer: "1860"
```

### Vocab entry

```yaml
- lemma: mangiare
  pos: verb
  gloss_en: "to eat"
  level: A1
  freq_rank: 312
  notes: "regular -are verb"
```

Schemas live in `maestro_pack/schemas/` as Pydantic models. The `build`
command translates YAML to SQLite tables that mirror these shapes.

---

## 5. Phases

### Phase 0 — Foundations & schema (1–2 weeks)

**Goal**: lock the content schema, prove the bundle pipeline.

**Scope**

- Finalize Pydantic schemas for all pack types (skill, function, topic,
  drill bank, reading, listening, vocab, grammar reference).
- Draft 2 IT skill cards (`saluti`, `passato_prossimo`) and 1 IT topic
  pack (`food`) by hand to validate the schema covers everything.
- Port one existing A0 lesson from `data/it/a0_lessons.yaml` into the
  new pack format; confirm round-trip via `maestro-pack build`.
- `maestro-pack` CLI skeleton: `validate` and `build --target sqlite`.
- Web app: prototype a "lesson from bundle" route alongside the
  existing one. Read a single drill activity from the bundle SQLite,
  render it. No replacement of existing routes yet.
- Decide bundle layout (table per artifact type vs single denormalized
  table); benchmark query time on a realistic bundle (~5000 drills).

**Exit criteria**

- One A0 lesson in new pack form renders correctly via the prototype.
- Bundle build is reproducible from YAML in <30s.
- Web prototype renders a single activity from the bundle in <50ms.

**Risks**

- Schema misses something existing activity types need. Mitigation:
  read every activity type in `src/maestro/routes/activities.py`
  before locking schemas.

---

### Phase 1 — Web refactor + authoring CLI MVP (3–4 weeks)

**Goal**: web app reads content from the bundle. CLI authors new
content with Claude assistance.

**Scope — web**

- Replace `src/maestro/lessons/planner.py` with a `LessonSelector`
  that picks activities from the bundle based on the curriculum graph
  and user state.
- Refactor `src/maestro/routes/lessons.py` to call the selector. The
  lifecycle (queued → in_progress → scored → complete) stays.
- `src/maestro/routes/activities.py`: keep per-activity rendering;
  teach it to pull variants from the bundle.
- Drill scoring (`drill_scoring.py`) keeps its rule-based path. No
  change needed.
- Add `LLMGrader` interface + `ClaudeAPIGrader` impl. Wire into the
  writing-submission and mistake-explanation paths.
- Remove `src/maestro/lessons/prompts.py` lesson-generation prompts;
  keep grading prompts (move them next to the grader).
- Onboarding flow updated to capture topic + function preferences.
- Mongo stays for user state (profile, SRS, mastery, recent-IDs
  window). Schema gains topic/function preference fields.

**Scope — CLI**

- `maestro-pack new --skill/--function/--topic --lang` with Claude
  integration via `src/maestro/llm.py`.
- `maestro-pack generate-drills --skill X --count N` producing a YAML
  drill bank.
- `maestro-pack generate-reading` and `generate-listening`.
- `maestro-pack validate` checking: schema, vocab realness (lemma
  exists in base_vocab or is glossed), agreement (gender/number)
  heuristics, register consistency, no English bleed.
- Audio not yet wired.

**Scope (out)**

- PWA install / offline (Phase 4).
- Content fill beyond what is needed to test the loop (Phase 2).

**Deliverables**

- Web app serves lessons end-to-end from the bundle for at least one
  IT skill in one topic.
- CLI authors a fresh skill + drill bank in <10 min of human review
  time.
- Old lesson-generation code paths gone; tests pass.

**Exit criteria**

- A user logs in, completes a lesson, submits answers, gets a
  rule-based score, and on mistake sees an LLM-generated explanation
  via the API path.
- Writing submission returns rubric + comment via Claude in <10s.
- Onboarding captures topic + function preferences and selector
  honors them.

**Risks**

- The current `routes/activities.py` may have generation-time
  assumptions baked in. Mitigation: discovery pass at the start of
  the phase.
- LLMGrader latency on writing can feel slow — stream the response if
  the deployed Claude model supports it.

---

### Phase 2 — Italian content fill, A0–A2 (3–4 weeks)

**Goal**: a complete IT learner can use the app from A0 through A2
without running out of content.

**Scope**

- Skills inventory locked at start: ~25 skill cards covering A0
  (greetings, articles, gender/number, pronunciation, basic verbs,
  numbers, days, polite expressions), A1 (regular `-are/-ere/-ire`
  conjugation, possessives, prepositions, pronouns, modal verbs,
  basic negation, time expressions), A2 (passato prossimo, imperfetto,
  futuro semplice, comparatives, reflexive verbs, condizionale
  presente).
- Functions inventory: ~20 communicative functions (greeting,
  introducing, ordering, directions, time/dates, shopping, transport,
  asking for help, making plans, opinions, talking about routine,
  past events, descriptions, future plans).
- Topic packs: 10 IT packs (food, travel, work, family, daily life,
  shopping, transport, history, music, cinema).
- Drill banks: ~30 items per skill across sub-skills and topics.
  ~750 drills total.
- Reading passages: ~5 per topic pack, leveled A1 + A2. ~50 total.
- Listening dialogues: ~5 per topic pack, audio pre-rendered. ~50
  total.
- Writing prompts: ~3 per skill at the relevant level. ~75 total.
- Grammar reference markdown per skill. ~25 pages.
- Base vocab list: ~1500 IT words (A0 + A1 + A2 frequency).
- L1 speaker IT review pass (4–6 hours), bookable mid-phase.

**Exit criteria**

- All IT content passes `maestro-pack validate` with no errors and
  acceptable warning count.
- An end-to-end IT learner journey (A0 → A2) is playable without
  "no content available" gaps.
- L1 reviewer has signed off on ~80% of content; outstanding issues
  triaged.

**Risks**

- Claude generation quality varies by topic. Mitigation: per-pack QA
  checklist, hand-edit pass before L1 review.
- Authoring throughput is the bottleneck. Mitigation: batch generation
  calls (`generate-drills --count 30` in one Claude turn).

---

### Phase 3 — German content fill, A0–A2 (2–3 weeks)

**Goal**: feature-parity for German.

**Scope**

- DE skills: ~25 (greetings, articles + cases, gender/number, basic
  verbs, modal verbs, separable verbs, Perfekt, Präteritum, Futur,
  dative/accusative prepositions, Konjunktiv II for politeness,
  comparatives, reflexive verbs).
- DE functions: ~20 (parallel to IT).
- DE topic packs: 10 (food, travel, work, family, daily life,
  shopping, transport, history, music, cinema).
- DE drill banks (~750), reading (~50), listening (~50), writing
  (~75).
- DE base vocab list (~1500 words).
- L1 speaker DE review pass.

**Why faster than IT**: the authoring CLI, prompts, schemas, and
audio pipeline are now battle-tested. Only the content changes.

**Exit criteria**: same as Phase 2, for German.

---

### Phase 4 — PWA polish (2 weeks)

**Goal**: web app installs and works offline on phones and desktops.

**Scope**

- Service worker that caches the app shell + bundle + audio.
- Web app manifest, icons, splash screens, install prompt.
- Bundle versioning: bundle carries a build ID; the service worker
  checks the server for new builds and swaps with a "new content
  available" toast.
- Offline behavior: lessons fully playable without network. LLM
  grading queued and submitted when back online ("explanation pending
  — check back when online").
- Background sync to flush queued grading requests.
- Audio cached with a quota strategy (LRU eviction beyond N MB).

**Exit criteria**

- App installs on iOS Safari and Chrome Android with proper icon and
  launch.
- Going offline mid-lesson does not break the lesson.
- Coming back online flushes pending LLM grading requests and the
  user sees the explanations.

**Risks**

- iOS Safari PWA storage quotas and lifecycle quirks. Mitigation:
  test on real iPhone Safari early.
- Bundle size growth. Target <80 MB content + audio. Above that,
  defer some packs to lazy CDN download.

---

### Phase 5 — LLMGrader abstraction (2 weeks)

**Goal**: the grading runtime can swap between server API and
on-device behind one interface, no UI change.

**Scope**

- Move `LLMGrader` to a client-side interface as well as server-side.
  Two implementations:
  - `ServerAPIGrader`: POSTs to the existing endpoint (default).
  - `WindowAIGrader`: uses `window.ai.languageModel` (Chrome Prompt
    API) when available.
- Capability detection on app load. Per-user setting to force one
  backend or the other (debug-friendly).
- Prompt templates abstracted so both backends can run the same
  prompt; on-device prompts may need a shorter variant.
- Quality regression suite: a golden set of ~50 mistakes per language
  with expected explanation features (mentions the rule, identifies
  the wrong form, suggests the right one). Run against both backends,
  score with a meta-evaluator.

**Exit criteria**

- A Chrome user on a capable device gets explanations from Gemini
  Nano locally; same user on Firefox gets explanations from the
  server.
- Quality regression suite passes for the server backend; on-device
  acceptable for ≥70% of cases, with degradation flagged in the UI
  ("explained locally — limited detail").

**Risks**

- Chrome Prompt API surface is still maturing. Pin to a tested
  version range; fall back gracefully.
- Quality difference may be jarring. Mitigation: feature-flag the
  on-device path until quality is acceptable.

---

### Phase 6 — Launch (1–2 weeks)

**Goal**: ship v1.0.

**Scope**

- Friends-and-family beta (~10 users) for 1 week. Feedback triage.
- UI localization (EN + IT + DE) via `src/maestro/i18n/`.
- Marketing site / landing page.
- Public launch.
- README updated to describe the architecture; LICENSE confirmed;
  instructions for running locally.

**Exit criteria**

- Public URL live.
- v1.0 git tag.

---

## 6. Future / post-v1.0

| Item                                                              | Target  |
| ----------------------------------------------------------------- | ------- |
| B1 + B2 content (per language)                                    | v1.1+   |
| Third / fourth language (Spanish? French?)                        | v1.2    |
| Native iOS shell consuming the same bundle                        | v1.2    |
| Native Android shell                                              | v1.3    |
| On-device LLM via WebGPU/WebLLM bundled model                     | v1.x    |
| Conversation mode (free-form chat with grader as tutor persona)   | v2.0    |
| Push notifications                                                | v1.1    |
| Skill tree / progress visualization                               | v1.1    |
| Authoring web UI on top of `maestro-pack`                         | v1.x    |

---

## 7. Cross-cutting risks

- **Content authoring volume** is the dominant cost. ~1500 drills +
  ~100 passages + ~100 dialogues per language. Throughput depends on
  how well the CLI prompts are tuned in Phase 0–1; budget Phase 1
  generously.
- **L1 reviewers** for IT and DE: book before Phase 2 starts. Without
  an L1 pass, content quality will be uneven and silently wrong in
  ways that erode trust.
- **Grading API cost** is the recurring runtime cost. Estimate: ~1 LLM
  call per mistake + 1 per writing submission. ~3 mistakes per lesson
  + 1 writing = ~4 calls/lesson. At ~$0.01–0.03/call, a daily user
  costs ~$0.40–1.20/month. Plan pricing accordingly.
- **Bundle size** can balloon with audio. Track per-phase. Above
  100 MB, split into core + downloadable packs.
- **PWA on iOS Safari** is the riskiest platform combo. Test early.

---

## 8. Open decisions

| Question                                                        | Decide by    |
| --------------------------------------------------------------- | ------------ |
| Skill + function + topic inventory checklists per language      | Start of Ph2 |
| Bundle format: SQLite vs JSON-per-file. SQLite recommended.     | Start of Ph0 |
| User account model (email + magic link? OAuth? anonymous?)      | Start of Ph1 |
| Hosting target for the web app                                  | Start of Ph4 |
| Pricing model (free / one-time / subscription / freemium pack)  | Start of Ph6 |
| L1 reviewers identified for IT and DE                           | Mid Ph1      |

---

## 9. Next step

Break Phase 0 into work items. The three concrete starting actions:

1. **Lock the schemas.** Read every existing activity type in
   `src/maestro/routes/activities.py` and `src/maestro/lessons/schemas.py`,
   then write Pydantic models in `maestro_pack/schemas/` that cover
   them all with no TODOs.
2. **Port one A0 lesson.** Take `a0-01-in-aereo` from
   `data/it/a0_lessons.yaml`, restructure it into the new pack form
   (skill card, drill bank entries, reading entries, vocab entries),
   and confirm round-trip via `maestro-pack build`.
3. **Wire a single bundle-fed activity** into the web app behind a
   feature flag. Read one drill item from the bundle via Python
   `sqlite3` and render it through the existing activity template.
   No replacement of existing routes yet — just prove the read path.

Phase 0 work items go in a follow-up doc or issue tracker.
