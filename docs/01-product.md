# 01 · Product and MVP scope

## The product in one paragraph

Italiano teaches complete A1 Italian to English-speaking adults on iPhone, iPad and Mac. Each unit is one episode of a story set in Bologna and is built backward from what the learner should be able to do. Learners read and listen to short graded stories, tap any word for English, study short grammar notes built from the story, practise with stepped feedback, and finish each unit with a conversation and a unit check. Reviews are scheduled by FSRS and mix all earlier units. Everything works offline, and progress syncs through iCloud with no account.

## Who it is for

- **Primary:** absolute beginners whose first language is English, studying about 5 hours a week, motivated by travel, family, roots, work or study, or by Italian for its own sake.
- **Secondary:** returners who know some Italian; a placement test starts them at the right unit.
- **The study cohort:** 40–60 beginners who use the frozen MVP through TestFlight (`docs/12`).

## What the MVP is

1. **Full A1 content:** Unit 0, Units 1–12 and a final review (`content/units/*/unit.yaml`). About 800 taught words, about 150 chunks and 76 grammar points; 60–70 hours of learner time. Every A1 syllabus item is traced to where it is introduced, practised and assessed, and the build fails below 100%.
2. **All 20 lesson types:** 17 learning types and 3 assessments (`docs/06`).
3. **iPhone, iPad and native Mac** from one SwiftUI codebase. Layouts adapt; nothing is phone-only (`docs/07`).
4. **Offline-first, with iCloud sync** of an immutable event log (`docs/08`).
5. **Study support:** opt-in telemetry, an in-app final check, and an export of final-check responses for examiner rating (`docs/12`).

"Full A1" has a testable definition: every CEFR A1 scale is taught and assessed; every item in the CILS A1, CELI Impatto, joint-syllabus and PLIDA inventories is covered at the more demanding status; and finishers pass an official-format A1 exam. The syllabus data in `content/syllabus/a1-syllabus.yaml` encodes the first two conditions; the study tests the third.

## Non-goals (cut list, fixed until the study ends)

Pronunciation scoring · cloud or third-party LLMs · accounts or logins · levels beyond A1 · social features, leaderboards, chat · Apple Pencil handwriting · Android, web or Windows · video · group collaboration and live mediation · an exam-practice mode · payments and paywalls · human voice recordings · story illustrations (layouts leave room for them) · per-user FSRS optimisation · push notifications from a server (local reminders only).

If a task seems to need something on this list, stop and ask.

## Principles that shape every feature

1. **Never show untaught material.** Every text, exercise and review card passes the runtime eligibility rule (`docs/05`): every item in it has been introduced to this learner. The build-time checker enforces the same rule on the course order.
2. **Meaning first, form after.** Learners read and listen before the grammar note; highlighting appears only on a second pass.
3. **Retrieval with feedback.** Practice asks learners to recall, not just recognise. Errors get a pointer and a hint first, then the answer with a one-line rule.
4. **Spaced and mixed.** FSRS schedules reviews, and review mixes all earlier units.
5. **Honest progress.** Progress is shown as can-dos reached and words known, never as points. Weekly goals rather than streaks; nothing punishes a missed day. No hearts, lives or timers.
6. **Correct Italian above all.** Nothing reaches learners until the content lead has approved it. Agents draft; people decide.
7. **Privacy by default.** No account. Data stays on the learner's devices and their iCloud. The study upload is opt-in and pseudonymous.

## Success criteria for the MVP (engineering view)

The MVP is complete at the **week-20 gate** (`docs/11`) when:

- All 20 lesson types work on iPhone, iPad and Mac, including keyboard use on Mac and VoiceOver on all three.
- Units 0–12 and the final review pass all ten content checks (`docs/04`), and syllabus coverage is 100%.
- Placement and the final A1 check are built.
- Sync has been tested on three devices signed into one iCloud account, including offline edits and an account switch.
- A TestFlight build is out, and study telemetry works end to end against the endpoint.

The product's success (did people learn and keep coming back?) is measured by the study, not by this build: CILS A1 past paper ≥ 70% pass among finishers, CELI Impatto sample ≥ 60% pass at 30 days, taught-word recall ≥ 70% with untaught < 15%, 40% of activated learners reaching Unit 4, 25% active at day 30, and 30% finishing Unit 12 within 14 weeks.

## Glossary

| Term | Meaning |
|---|---|
| **Item** | Anything a learner learns and is scheduled on: a **word** (`w:`), a **chunk** (`c:`, a fixed phrase such as *vorrei* or *come si dice…?*), a **grammar point** (`g:`), or a **sound** contrast (`s:`). |
| **Skill** | `read` (understand written), `listen` (understand spoken), `recall` (produce in writing), `speak` (produce orally). Memory state is kept per (item, skill). |
| **Status** | Per item and skill: **P** (produce) or **R** (recognise only). Grammar points may also be taught as a **chunk** (used as a whole; never counts as knowing the rule). |
| **Introduction** | The moment an item becomes known to a learner for a skill (preview, story, note, sounds, placement, or a catch-up mini-preview). It drives eligibility. |
| **Eligibility** | Content may be shown only if every item in it has been introduced to this learner for the skill it needs. |
| **Can-do** | A unit goal in learner terms ("order food and drink"). **Stretch** can-dos are A2 in the CEFR but A1 in the Italian syllabi; they pass on intelligibility. |
| **Syllabus item** | One line of the A1 inventory (grammar, function, topic, sound or register, CEFR scale, exam task type) with an ID such as `sy:gr.articles`. |
| **Unit / lesson / step** | A unit has an opener, three lessons, a unit task, a unit check and fluency replay. A lesson's steps, by `kind`: `preview`, `story` (or `listening`, `reading`), `note`, `practice`, `sounds`, `use` — in plain words: preview, read and listen, notice, practise, hear, use. |
| **Exercise** | One atomic graded question in a given **format** (cloze, recall, choice…). Steps contain exercises; reviews reuse them. |
| **Strand** | Nation's four strands: input, output, language focus, fluency. Each unit keeps every strand within a band of its estimated time (`docs/04` § Check 3): language focus may take up to 60% in Units 0–2 and 50% after, the meaning-focused strands keep a floor. |
| **Event** | An immutable record of something the learner did (attempt, introduction, completion). The event log is the only learner data that syncs. |
| **Content pack** | The compiled read-only SQLite file plus audio that ships in the app. |
| **Content lead** | The qualified Italian L2 teacher who signs off the syllabus and approves every unit. |
