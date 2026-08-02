# 07 — The lesson object, and closing the content loop

Status: design proposal
Scope: make a lesson a first-class authored object, and make every A0–A2
grammar point, communicative function, can-do and lemma **introduced by
exactly one lesson and revisited by at least two more, at rising
demand**. Supersedes nothing; extends `02-greenfield-architecture.md`
§2–3 (spec + packs) and §5 (tutor loop). Findings behind it are in §1.

---

## 1. The problem in one line

**There is no lesson object anywhere in the system.** A lesson is an
emergent side effect of `pick_scenario() × archetype slot table ×
weighted sampling over the whole pack` ([session.rs:39](../../core/src/session.rs)).
Nothing authors a lesson, nothing validates that one is coherent or
complete, nothing names it, and nothing records that the learner *did*
it beyond a bare completion counter. The scenario is the closest thing
to a lesson, but `scenario_ids` is a **preference tag on items**
(decision #34), not a container — a lesson has no manifest, so it has no
boundary, no required set, and no end.

Six consequences, all observed by walking a simulated perfect learner
through 14 sessions against the real pack:

1. **No can-do can ever be achieved.** `folds.rs` gates achievement on
   `applied` — at least one correctly-answered item carrying
   `axis: cando`. No authored item carries that axis. After 14 flawless
   sessions: 33 can-dos `in_progress`, **0 achieved**, `applied=false`
   on every one, including `a0.ask_where` at grammar 3/3, functions 1/1.
   The Progress tab is structurally incapable of ever saying "you can do
   this now."
2. **The teach step gets stolen by another lesson.** Any `attempt` marks
   its grammar `introduced` ([folds.rs:98](../../core/src/folds.rs)), and
   passage questions inherit their parent's grammar evidence at half
   weight. Session 2 ("In albergo") had no listening of its own, fell
   through to `reading.al_bar.002`, and answering *"Quanto costa?"*
   marked `vorrei` introduced. Session 3 — "Al bar", whose own
   description calls `vorrei` *"the one phrase that gets you anything"* —
   arrived as `consolidation` with **no grammar card at all**. The
   learner is never taught `vorrei`.
3. **The frame leaks.** Session 1 is "In aereo"; its listening slot
   played `listening.al_bar.001`. Tier fallthrough is working as coded,
   but there is no rule that a lesson stays in its own world and no
   signal when it doesn't.
4. **Promises outrun content, silently.** 37 scenarios in the spec, 5
   with authored content. From session 6 the app keeps announcing named
   lessons — "A pranzo · You'll practise: che cos'è, vocabolario del
   cibo" — and delivers three recycled off-scenario items plus three
   flashcards, teaching neither. `next_lesson_brief` never consults item
   availability, so it cannot know.
5. **Practice and progress are indistinguishable.** "Quick drills ·
   5 min" carries a `scenario_id`, has no teach step, and its recap
   fires `scenario_completed` — a new user's first tap permanently
   consumes "In aereo", the app's opening scene.
6. **Depth is unrepresentable, so nothing is ever revisited.** All 13 A0
   scenarios have one depth and retire after a single visit — at the
   level where repetition matters most, there is no second pass at all.
   The 24 A1 scenarios have three depths, but no item carries a depth
   tag and `scenario_completed` never sends one, so `max_depth_completed`
   is pinned at 1: they never deepen and never retire. A learner meets
   `vorrei` in one lesson, at one difficulty, once — and that lesson is
   the only place the language will ever put it.

Everything above is a symptom of the missing object. This document
proposes the object, and then uses it to close the coverage loop.

---

## 2. The lesson, and the spiral

**A lesson is a scenario at a depth.** It is authored, named, has a
stable id, declares what it introduces *and what it comes back to*, and
ships with a required set of items or it is not offered at all.

Nothing is taught once. **Every grammar point, function, can-do and
lemma is met at least three times, in at least three different lessons,
at strictly rising demand.** One pass introduces it; the rest come back
to it harder. That is the difference between a syllabus and a checklist,
and it is what "covered" has to mean (§3).

### The demand ladder

The core already has the ladder and has had it since the mastery fold was
ported — `Receptive 0.5 → Targeted 1.0 → Productive 1.5`
([model.rs:63](../../core/src/model.rs)). What is missing is that **no
authored item declares one**: `evidence_class` is guessed by the iOS
shell from which view happens to be rendering, which is why comprehension
questions are recorded as targeted production (§1, finding in §7). Make
it an authored property and the ladder becomes the spine of the spiral:

| Pass | Author name | `evidence_class` | What the learner does |
| --- | --- | --- | --- |
| 1 | `meet` | `receptive` | recognises it — in a passage, a dialogue, a comprehension question |
| 2 | `use` | `targeted` | produces it with scaffolding — cloze, transform, guided speaking |
| 3 | `perform` | `productive` | produces it without — open task, role-play, free writing |

Every pack item gains `demand: meet | use | perform`. It is the item's
own property, not the slot's, so the same ladder governs authoring,
selection, mastery weighting and the UI's framing at once.

```yaml
# spec/it/scenarios.yaml — depths become objects
- id: al-bar
  cefr_level: A1          # the scenario's floor; each depth may raise it
  phase: 1
  sequence: 2
  label: Al bar
  depths:              # today: list[str]. becomes list[Lesson].
    - id: al-bar.d1
      cefr_level: A1
      label: Al banco
      goal: Order at the counter and pay without switching to English.
      introduces:                        # first pass — this lesson owns the teaching
        grammar:   [art_un_una, vorrei]
        functions: [a1_ordinare]
        vocab:     [caffè, cappuccino, cornetto, banco, scontrino]
      revisits: []                       # nothing behind it yet
      capstones:
        - { cando: a0.order_something, demand: use }
      scene_setting: |
        Giulia is already at the counter...
      outro: You ordered, you paid, you said grazie. That is the whole bar.

    - id: al-bar.d2
      cefr_level: A1
      label: Un tavolo fuori
      introduces:
        grammar:   [prep_art]
        functions: [a1_chiedere_prezzo]
        vocab:     [tavolo, terrazza, coperto]
      revisits:                          # second pass — one rung up
        grammar:   [{ id: art_un_una, demand: use }, { id: vorrei, demand: perform }]
        functions: [{ id: a1_ordinare, demand: perform }]
      capstones:
        - { cando: a0.order_something, demand: perform }

    - id: al-bar.d3
      cefr_level: A2       # depth 3 is where A2 lives — see §4
      ...
```

Four properties do the work:

- **`introduces` is an exclusive assignment.** Every A0–A2 grammar point,
  function and lemma is introduced by **exactly one** lesson — its
  *home*, the lesson that owes it a `grammar_ref` and a first bank of
  items. This is what makes `introduced` mean something (§6) and what
  makes finding #2 impossible.
- **`revisits` is the spiral, and it is declared, not emergent.** Each
  entry names an id and the rung it is being taken to. A revisit must be
  ≥ the demand of the last pass, and every item must reach `perform` at
  least once across its passes. Nothing gets three receptive encounters
  and a tick.
- **`capstones` are the lesson's ending, and there are three of them per
  can-do across a scenario's depths** — `meet`/`use` early, `perform`
  last. A can-do is *achieved* only on passing its `perform` capstone
  (§6). This is the missing `axis: cando` item and the missing UX beat:
  the moment the app can say *"you can now order a coffee"* — earned, not
  handed over on the first attempt.
- **The lesson id is forever**, like every other spec id. `<scenario>.d<n>`
  by convention, but a string, not a computed key — depth counts can grow
  without renaming what came before.

Scenario-level `grammar_ids` / `function_ids` stay, demoted to a derived
union of their depths, asserted at build time rather than authored.

### The required set — and what a revisit does *not* cost

A lesson **builds** only if the pack supplies these, tagged to that
`lesson_id`:

| Slot | Required |
| --- | --- |
| `grammar_ref` | one per entry in `introduces.grammar` |
| drills | ≥6 at `demand: use` per introduced grammar point |
| `reading` | ≥1 of its own, questions at `demand: meet` |
| `listening` | ≥1 of its own, questions at `demand: meet` |
| `speaking_prompt` | ≥1 per entry in `introduces.functions` |
| `writing_prompt` | ≥1 |
| `vocab_card` | one per entry in `introduces.vocab` |
| **`task`** | one per entry in `capstones`, carrying `axis: cando` |

**Revisit slots are filled pack-wide, not lesson-locally** — by
`(axis id × demand tier)`, wherever the item lives. That is the economy
that keeps the spiral from tripling the content bill: coming back to
`vorrei` at `perform` in `al-bar.d2` costs one authored task, and every
later lesson that revisits `vorrei` at `perform` can draw the same pool.
Revisit supply is therefore validated **globally** (§3), not per lesson.

`build` writes `complete: 0|1` per lesson and the composer offers only
complete ones. A half-authored lesson is invisible rather than
disappointing — finding #4, fixed at the root.

### The capstone item type

New item type `task` (`authoring/pack_schemas.py`), the only one carrying
`axis: cando`:

```yaml
# al-bar.d1 — the scaffolded pass: the target is on screen.
- status: reviewed
  lesson_id: al-bar.d1
  id: task.al_bar.d1
  item_type: task
  demand: use
  cefr_level: A1
  mode: speaking            # speaking | writing — the can-do's own skill
  prompt: |
    You are at the counter. Order a cappuccino and a cornetto,
    then ask what it costs.
  target_text: "Vorrei un cappuccino e un cornetto, per favore. Quant'è?"
  rubric: [orders both items, uses vorrei or equivalent, asks the price]
  evidence:
    - { axis: cando,    id: a0.order_something, weight: 1.0 }
    - { axis: function, id: a1_ordinare,        weight: 1.0 }
    - { axis: grammar,  id: vorrei,             weight: 1.0 }

# al-bar.d2 — the free pass: no target text, and this is the one that
# flips the can-do to achieved.
- status: reviewed
  lesson_id: al-bar.d2
  id: task.al_bar.d2
  item_type: task
  demand: perform
  mode: speaking
  prompt: |
    Sei al bar con Giulia. Ordina per tutti e due e chiedi quanto costa.
  rubric: [orders for two, asks the price, no English]
  evidence:
    - { axis: cando, id: a0.order_something, weight: 1.0 }
```

`demand` decides the scaffolding as well as the evidence weight: a `use`
task shows its `target_text`, a `perform` task does not, which is why the
`perform` variant can omit it entirely and lean on the rubric. Both reuse
the existing scorers — `align.rs` for `mode: speaking`, the offline
writing rubric plus optional LLM grading for `mode: writing` — so this is
a schema and an authoring obligation, not a new runtime.

---

## 3. What "covered" means, per axis

The closure contract, checkable by `maestro-pack validate --coverage`,
which **fails** (not warns) when any of these is unmet for A0–A2.

Four rules apply to every axis:

1. **Introduced once** — exactly one lesson lists it under `introduces`.
   Zero is an orphan; two is an ambiguous home. Both are errors.
2. **Passed ≥3 times** — it appears in ≥3 distinct lessons, counting its
   home, across `introduces` + `revisits` + `capstones`.
3. **Rising, never falling** — ordered by the lessons' phase/sequence/
   depth, the demand tiers are non-decreasing.
4. **Reaches `perform`** — the last pass is `perform`, and the pack
   actually supplies a `perform`-tier item carrying it.

Then, per axis:

| Axis | Additionally covered when |
| --- | --- |
| Grammar point | its home ships a `grammar_ref` and ≥6 `use` drills; ≥1 `perform` item carries it |
| Communicative function | its home ships ≥1 `speaking_prompt`; across its passes there are ≥3 productive opportunities, so `FUNCTION_DEMONSTRATED_AT` (3) is reachable by doing the lessons rather than by luck |
| Can-do | it is capstoned in ≥3 lessons at rising demand, ending in `perform`; ≥80% of its `grammar_ids` and `function_ids` are introduced by that lesson or an earlier one in phase/sequence order |
| Lemma | its home ships a `vocab_card`, it appears in ≥1 non-card item of that lesson (met in context before it is ever drilled cold), and it appears in ≥1 `perform` item somewhere |

Rule 2 is the one that changes the shape of the work. Today the spec
*already* demands three productive uses of a function
(`FUNCTION_DEMONSTRATED_AT = 3`) but nothing guarantees three
opportunities exist — the counter is fed by whatever the sampler
happened to pick. Rule 2 makes the opportunity a build-time obligation
rather than a statistical hope.

The lemma clause also fixes a live wart: vocab review currently weights
never-seen lemmas at 0.75 ([session.rs:339](../../core/src/session.rs)),
so a "review" slot can present a word the learner has never met,
front-side first, with a self-grade and no teaching.

---

## 4. The arithmetic — does it close?

Current inventory and where it stands:

| Axis | A0–A2 total | In a scenario | In a can-do | **Orphaned** |
| --- | --- | --- | --- | --- |
| Grammar points | 163 | 81 | 80 | **56** (all A2) |
| Comm. functions | 199 | 101 | 144 | **40** (all A2) |
| Can-dos | 68 | 66 | — | **2** (both A2) |
| Lemmas | 412 | — | — | **412** (no mechanism) |

Lesson slots available **today**: 85 — 13 A0 scenarios × 1 depth, plus
24 A1 scenarios × 3 depths. That is not enough, for two independent
reasons: the ≥3-passes rule needs somewhere to put the passes, and the
13 A0 scenarios have **one depth each**, so at the level where
repetition matters most there is currently no second pass at all.

**Proposal: every scenario gets ≥3 depths, and A1 scenarios get 4.**

| | scenarios | depths | lessons |
| --- | --- | --- | --- |
| A0 | 13 | 3 (bands A0 · A0 · A1) | 39 |
| A1 | 24 | 4 (bands A1 · A1 · A2 · A2) | 96 |
| | **37** | | **135** |

The fourth depth on A1 is not padding — it is what the A2 band costs.
With three depths, the 24 depth-3 lessons would have to introduce all 82
A2 grammar points at 3.4 each, more than double the target load. A
fourth depth halves it:

| Band | Lessons | Grammar to introduce | Per lesson |
| --- | --- | --- | --- |
| A0 | 26 | 22 | 0.8 |
| A1 | 61 | 59 | 1.0 |
| A2 | 48 | 82 | 1.7 |

And the passes fit:

```
grammar   163 × 3 = 489 passes / 135 = 3.6 per lesson  (1.2 new, 2.4 revisited)
functions 199 × 3 = 597 passes / 135 = 4.4 per lesson  (1.5 new, 2.9 revisited)
lemmas    412 × 3 = 1236 passes / 135 = 9.2 per lesson (3.1 new, 6.1 revisited)
can-dos    68 × 3 = 204 capstones / 135 = 1.5 per lesson
```

**The budget closes at the shape a lesson should have anyway** — one or
two new grammar points, a couple of new speech acts, three new words,
half a dozen things coming back harder, and one or two can-dos to prove.
The can-do fit is the neatest: 68 can-dos over 37 scenarios is 1.8 per
scenario, each capstoned once per depth, which is exactly the 1.5–1.8
capstones per lesson the arithmetic asks for. Three assignments have to
be made:

**(a) A2 needs a home.** All 24 non-A0 scenarios are labelled A1, so 56
A2 grammar points, 40 A2 functions and 2 A2 can-dos belong to nothing.
`can_do.yaml`'s own header already states the intent — *"A2 rows
reference A1 scenarios where the scenario's depth 2–3 framing covers
them"*. Make that literal: **`cefr_level` moves onto the depth**, and a
scenario's band rises by at most one across its depths (A0 → A0 → A1;
A1 → A1 → A2 → A2). No new scenario inventory, and no relabelling that
hides a level from the learner. The alternative — a dedicated A2
scenario tier of ~10 scenarios × 3 depths in phases 4–5 — gives the same
48 A2 lessons with better narrative variety, at the cost of ~10 new
scenarios of spec authoring. **Recommend the depth-band move** to close
the loop now; the A2 tier stays available later as content variety
rather than as coverage.

**(b) `vocab_domains` has no join.** Can-dos reference 24 domains
(`food_drink`, `personal_details`, …); **zero of the 412 entries in
`vocab.yaml` carry a `domain` field**. Add it — one field, 412 rows,
mechanical — so lemmas can be assigned to lessons by domain and the
can-do decomposition's fourth axis stops being decorative.

**(c) Rebalance the outliers.** `a0-13-ripasso` claims 22 grammar points
and 0 can-dos; `la-giornata` claims 17. Under the spiral these become the
natural home of the *last* pass rather than a dumping ground for the
first: `introduces` empty, `revisits` broad and all at `perform`,
`capstones` set. That is what a ripasso is.

### The content bill, stated honestly

Roughly **3,000 items** — ~30 for a depth-1 lesson (2 grammar refs, 12
drills, a reading and a listening with their questions, 2 speaking
prompts, a writing prompt, 4 vocab cards, 1–2 tasks) and ~18 for a later
depth, across 135 lessons. The pack today has 252, of which 186 are
draft.

The spiral is what keeps that number from being ~3× worse. Because
**revisit slots draw pack-wide by `(axis id × demand tier)`** (§2), a
second and third pass over `vorrei` cost nothing beyond the `perform`
items that have to exist anyway — the ≥3-passes rule is satisfied by
*scheduling*, and only the `introduces` obligations and the capstones are
per-lesson authoring. The proposal does not make the authoring smaller;
it makes the target countable, the gap a number in CI, and every item
attributable to a lesson that will actually ship it.
`generate --lesson <id>` (§5) is the lever.

---

## 5. Authoring changes

- **Every item declares `demand: meet | use | perform`** — the authored
  counterpart of `EvidenceClass`, which the shell currently guesses.
  `quality.py` gets the obvious checks: a `perform` item may not ship
  `target_text` as a visible scaffold, a `meet` item may not be a cloze.
- **`--lesson` replaces `--gp`/`--scenario` as the primary generate
  scope.** `generate --lesson al-bar.d1` drafts the lesson's whole
  required set in one pass against its `introduces` block and narrative
  fields, so a lesson arrives complete or not at all. A second scope,
  `generate --perform <axis-id>`, fills the global higher-tier supply
  that revisits draw on.
- **`validate --coverage`** — the §3 contract: introduced exactly once
  (orphan and duplicate-home are both errors), ≥3 passes, non-decreasing
  demand, reaches `perform`, plus the per-axis clauses and a global
  supply check that every `perform` revisit has an item to draw. Every
  lesson's prerequisite grammar must be introduced by an earlier lesson
  in phase/sequence/depth order.
- **`build`** stamps `lesson_id` and `demand` on every item, writes a
  `lessons` table with `complete`, and refuses to mark complete a lesson
  whose capstones are missing.
- **`review`** gains a lesson view — the required set as a checklist, so
  the reviewer sees a lesson rather than a stream of items. The existing
  coverage matrix becomes per-lesson.
- **Items keep `scenario_ids`** (decision #34) as the practice-preference
  tag. `lesson_id` is new and is the *home*: exactly one per item,
  `scenario_ids` may list several.

## 6. Core changes

- **`compose()` takes a lesson**, not a scenario. `SessionPlan` gains
  `lesson_id`. Slots come from the lesson's manifest: `introduces`
  entries are filled lesson-locally, `revisits` entries are filled
  pack-wide by `(axis id × demand tier)` — the spiral's scheduling half.
- **Archetypes collapse to lesson position.** `introduction` /
  `consolidation` / `application` stop being inferred from mastery and
  become: **first visit** (teach → practise → read → hear → speak →
  capstone), **deeper visit** (revisit at the declared rung → capstone at
  the next rung up), **ripasso** (a lesson that introduces nothing).
  Writing gets a slot in all three, not only in the unreachable one — 7
  authored writing banks currently surface about once in 14 sessions.
- **The mastery fold was already written for a spiral.**
  `EvidenceClass::weight` scores productive at 1.5, targeted at 1.0,
  receptive at 0.5, and `MIN_EVIDENCE_MASS` is 3.0 — so one pass per rung
  sums to exactly the floor (0.5 + 1.0 + 1.5 = 3.0) while three receptive
  encounters reach half of it. The thresholds have simply never had a
  spiral to score. One consequence worth pinning with a vector: mastery
  decays at `0.95^days`, so three passes spread over months fall *under*
  the floor — the composer must keep a grammar point's revisits within
  reach of each other, or a lesson's three passes are worth less than
  their nominal 3.0.
- **A can-do is achieved on its `perform` capstone**, not on any
  cando-tagged item — `applied` becomes `applied_at_perform`. The
  80%/80% grammar and function gates stay.
- **`introduced` is set by the `introduced` event only.** Drop the
  `introduced.insert` in the `Attempt` arm ([folds.rs:98](../../core/src/folds.rs)).
  With every taught GP owning a `grammar_ref`, the explicit event always
  fires, and finding #2 becomes impossible. Needs a new conformance
  vector and a decisions entry; pre-release, so no learner migration.
- **`scenario_completed` carries `depth`** (already in the event schema,
  never sent). Completion is per-lesson, so A0 lessons can repeat and A1
  lessons can actually deepen.
- **Practice ≠ progress.** A time-budget-only session composes from the
  review pool and emits **no** `scenario_completed`.
- New conformance vectors: `12_lesson_manifest.json` (a first visit
  contains its whole required set, in order), `13_capstone_closes_cando.json`
  (only the `perform` capstone flips a can-do to `achieved`),
  `14_introduced_requires_teaching.json` (an attempt alone does not
  introduce), `15_revisit_raises_demand.json` (a lesson's revisit slots
  draw items at or above the rung the learner last reached).

## 7. App changes

- **Splash leads with the goal, not the archetype.** "By the end: order a
  coffee and ask what it costs" — the lesson's `goal`, which is also the
  capstone. `navigationTitle(plan.archetype)` and the `weakness drill`
  badge are composer internals; take them out of the UI
  ([SessionView.swift:105](../../ios/Maestro/SessionView.swift),
  [:203](../../ios/Maestro/SessionView.swift)).
- **The capstone is its own screen** — the lesson's last beat, framed as
  a performance rather than another drill, and the recap opens on
  whether the can-do landed.
- **The spiral has to be legible or it reads as repetition.** A revisit
  needs to say it is one and say it got harder: *"Vorrei — third time,
  no help this time."* The demand tier is the copy. Without it the
  learner's experience of a spiral curriculum is "I've seen this
  already", which is the complaint that motivated the whole design.
- **"Quick drills" becomes "Practice"** — review pool, no lesson
  consumed, and it says so.
- **Comprehension questions send `evidence_class: "receptive"`.**
  `DrillView.submit` hardcodes `"targeted"` for every scored item
  ([SessionView.swift:340](../../ios/Maestro/SessionView.swift)), so
  answering *"what did the customer order?"* counts as a productive
  demonstration of *ordinare* on the axis that gates can-dos. The core
  already excludes receptive evidence; the shell never sends it.
- **Progress groups can-dos by lesson**, shows the next one and what it
  needs, and hides `locked` behind a disclosure. 35 of 68 currently
  render as a flat locked list.
- **Resume mid-lesson.** Position is `@State index` in memory; leaving
  loses it, and abandoning before the recap replays the lesson with its
  best items inside the 50-item anti-repetition window.
- Disambiguate the three duplicate labels — "Al bar", "In albergo" and
  "In viaggio" each name both an A0 and an A1 scenario.

## 8. Sequencing

Each step is separately shippable; 1–2 are the ones that unblock
everything else.

1. **`demand` + capstone + coverage contract** — `demand` on the item
   schema, `task` item type, spec `introduces`/`revisits`/`capstones`,
   `validate --coverage`. Can-dos become achievable and the gap becomes a
   number in CI. This is the step that makes the spiral expressible.
2. **`introduced` scoping + `evidence_class` from `demand` + depth on
   completion.** Small, high-leverage, four conformance vectors.
3. **Lesson-scoped composer** (`lesson_id` on plan and items, lesson-local
   `introduces` slots, pack-wide `revisits` slots, practice≠progress).
4. **Spec fill** — depths 1→3 on the 13 A0 scenarios and 3→4 on the 24 A1
   scenarios, `cefr_level` per depth, `domain` on 412 lemmas, then the
   assignment itself: one home and ≥3 rising passes for each of 163 GPs,
   199 CFs, 68 can-dos and 412 lemmas. The largest step, and the one
   `validate --coverage` turns into a checklist with a countdown.
5. **App**: capstone screen, goal-led splash, revisit framing, Practice,
   Progress by lesson, resume.
6. **Content fill** by lesson via `generate --lesson`, ordered by
   phase/sequence/depth, with `complete` gating what ships. Depth-1
   lessons across all 37 scenarios first — that is a whole coherent
   course on its own, and the depths spiral onto it.

## 9. Open questions

- **Depth-band A2 vs. a real A2 scenario tier** (§4a). Recommending the
  former; it closes the loop a phase earlier and costs one spec field.
- **Is 4 depths on A1 the right shape, or 3 depths + a wider A2 tier?**
  The fourth depth exists purely to halve the A2 introduction load. If
  the A2 scenario tier gets written anyway, A1 goes back to 3 and the
  arithmetic still closes.
- **Does `revisits` want authoring at all, or should it be derived?** A
  scheduler could pick revisits from mastery and decay, which is what
  the composer already half-does. Authored revisits are predictable and
  reviewable; derived ones adapt to the learner. The proposal authors
  them because coverage has to be *provable at build time* — but a
  derived layer on top, choosing *which* of the declared revisits a given
  session runs, is the obvious next move.
- **Should a capstone be blocking?** Failing it currently just leaves the
  can-do unachieved. Blocking the next lesson is more honest and more
  punishing; a retry offer in the recap is probably the middle.
- **Lemma homes vs. natural frequency.** Assigning every lemma to exactly
  one lesson is clean for coverage but may put a common word late.
  Frequency-order the assignment within each domain, and allow an
  `introduces.vocab` entry to be pulled earlier by any lesson that needs
  it.
- **Is 3 passes enough for grammar, and too many for vocab?** The rule is
  uniform across axes because a uniform rule is checkable, but the
  evidence is not: SM-2 already spaces lemmas properly and three
  *contextual* encounters may be generous, while a hard grammar point
  like `prep_art` plausibly wants five. Start uniform at 3, let
  `validate --coverage` report the distribution, and raise the minimum
  per axis once there is content to look at.
