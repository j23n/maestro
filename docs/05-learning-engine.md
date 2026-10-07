# 05 · Learning engine

Everything in this document lives in `Packages/LearningCore` and is pure, deterministic Swift: the same events and pack always give the same state on every device. Storage persists the results, and the App shows them.

**Determinism helpers.** Time comes from `Clock`, IDs from `UUIDSource`. Every seeded shuffle or pick uses **SplitMix64** seeded with **FNV-1a 64** (offset basis `0xcbf29ce484222325`, prime `0x100000001b3`) over the UTF-8 bytes of a seed string. Never use Swift's `hashValue`, which changes per process. **Local days** start at **04:00** in the event's own `tz_offset_min`: daily activity, the week dots, the planner's "today" and day-based seeds all use this.

## Skills and what gets scheduled

Memory state exists per (item, skill) for the four skills `read`, `listen`, `recall` and `speak`, whenever review events exist. Only some pairs get **scheduled review cards**, to keep daily load near 30–60 cards. The pack marks them with `item_skills.scheduled = 1`:

| Item kind | Status | Scheduled skill |
|---|---|---|
| word or chunk | P | `recall` (English → Italian). A recall success also shows the learner recognises the item, so `read` isn't scheduled separately |
| word or chunk | R | `read` (Italian, with audio → meaning) |
| grammar point | P | `recall` (cloze or sentence building from the exercise bank) |
| grammar point | R or chunk | `read` (recognition items) |
| sound | P (listen) | `listen` (minimal-pair discrimination) |

`listen` (for words) and `speak` are practised and tracked (Words screen bars) but not scheduled in the MVP.

## Events

Every learner action is an immutable event (`docs/03` § Learner database). The payload is camelCase JSON; `schema` is 1 for all types at launch. Event IDs are random UUIDs; the order is `(at, id)`.

| `type` | Payload | Written when |
|---|---|---|
| `introduced` | `{items: [{itemId, skills: [..]}], via: preview\|story\|note\|sounds\|placement\|catchup\|debug, stepId?}` | a step starts that introduces items not yet introduced; placement; an eligibility mini-preview (`catchup`) |
| `attempt` | `{exerciseId, turnId?, format, context: lesson\|review\|check\|placement\|final, stepId?, sessionId, attemptIndex: 1\|2, outcome: correct\|correctWithNote\|almost\|wrong\|revealed\|skipped, targets: [{itemId, skill, outcome}], response?, mode: typed\|spoken\|tapped, latencyMs, feedbackShown: none\|hint\|answer}` | each graded answer |
| `stepStarted` / `stepCompleted` | `{stepId, sessionId, durationMs?}` | entering a step that has no open start (none since its last `stepCompleted`), so reopening a half-done step writes nothing; finishing a step |
| `glossTapped` | `{textId, line, token, itemId?}` | the learner taps a word for English |
| `audioPlayed` | `{audioId, textId?, rate, playedMs, context: story\|fluency\|exercise\|item}` | playback stops or ends (fluency replay time is logged this way) |
| `session` | `{sessionId, kind: lesson\|review\|check\|placement\|final, platform: iPhone\|iPad\|Mac, startedAt, endedAt, activeSeconds}` | a session ends |
| `checkCompleted` | `{checkId, kind: unit\|final, sections: [{id, earned, possible, excluded}], overall, passed, canDosReached: [..]}` | the last check item is answered |
| `placementCompleted` | `{startUnit, blocks: [{unit, correct, total}]}` | placement ends, or the learner picks "Start from the beginning" (`startUnit: u00`, no introductions) |
| `onboardingCompleted` | `{reason, forms: m\|f\|both, country, beginner: Bool}` | onboarding ends (the same values are also stored as synced settings) |

- **Session:** one continuous visit to an activity (a lesson step sequence, a review session, a check, placement or the final check). It starts when the activity opens, gets a new `sessionId` (UUID), and ends when the learner leaves or finishes the activity, or the app has been in the background for more than 5 minutes. `platform` feeds the sync status line (`docs/08`).
- **`response`:** the learner's text, at most 200 characters for closed formats and 2,000 for writing and talk transcripts. It syncs with the event (the learner's own work on their own devices). Telemetry keeps only typed answers in closed formats (`docs/12`): `response` is stripped from talk, writing and every spoken answer, and `onboardingCompleted` loses `country`. Speaking recordings are files, not events (`docs/09`).
- **Targets:** every target of a non-match exercise gets the exercise's outcome; a `match` gives each pair's outcome to that pair's target. Conversation turns carry no targets.
- The reducer ignores unknown event types, so newer clients can add types without breaking older ones.

## Rating policy (events → FSRS ratings)

Only `attemptIndex == 1` attempts update FSRS. Second attempts and revealed answers are learning, not retrieval. Per target:

| Format family | Outcome on first attempt → FSRS rating |
|---|---|
| typed: cloze, recall, dictation, sentence-building | `correct` and `correctWithNote` → **Good (3)**; `almost` → **Hard (2)**; `wrong` and `revealed` → **Again (1)**; `skipped` → none |
| tapped: choice, match (per pair), true-false, sound-pair | `correct` → **Good**; `wrong` → **Again** |
| spoken: repeat, recall answered by voice | a pass is written as `correct` → **Good**; a fail is written as `wrong` but **makes no update** when `mode` is `spoken` (logged only; ADR-08); "Skip — can't speak now" is `skipped` → none |
| conversation turns (typed or spoken), talk, writing, relay, comprehension questions | no FSRS update (task-level evidence; counted for checks and analytics) |
| placement | no update (placement introduces items; see Placement) |

Easy (4) is not used in the MVP. Attempts in `check` and `final` contexts update FSRS like any other first attempt.

## FSRS-6

Implement exactly this; `fixtures/fsrs/fsrs6-reference.json` (generated from py-fsrs 6.3.2) must pass with relative tolerance 1e-9 for stability, difficulty and retrievability, and exact due dates. The fixture has no interval that lands on .5, so add a unit test for `roundHalfEven` itself.

Parameters `w[0…20]` = `0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542`. Desired retention `r = 0.9`, maximum interval 36,500 days. G is the rating (1 Again, 2 Hard, 3 Good, 4 Easy).

```
DECAY  = −w20
FACTOR = 0.9^(1/DECAY) − 1
R(t,S) = (1 + FACTOR · t / S)^DECAY            t = whole days elapsed = floor(seconds / 86400)

First review (no state):
  S = max(w[G−1], 0.001)
  D = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)

Later review at time T, previous state (S, D, lastReview):
  t = floor((T − lastReview) / 86400 s)
  if t < 1:                                    same-day (short-term)
     inc = e^(w17·(G − 3 + w18)) · S^(−w19);  if G ≥ 2: inc = max(inc, 1)
     S' = max(S · inc, 0.001)
  else:
     R = R(t, S)
     G = 1:  S' = max(min( w11 · D^(−w12) · ((S+1)^w13 − 1) · e^((1−R)·w14),  S / e^(w17·w18) ), 0.001)
     G ≥ 2:  S' = max(S · (1 + e^w8 · (11 − D) · S^(−w9) · (e^((1−R)·w10) − 1) · hard · easy), 0.001)
             hard = w15 if G = 2 else 1;  easy = w16 if G = 4 else 1
  D' = clamp( w7 · D0(4) + (1 − w7) · (D + ΔD · (10 − D)/9), 1, 10 )
       ΔD = −w6 · (G − 3);  D0(4) = w4 − e^(w5·3) + 1   (not clamped)
  (S' uses the old D; D is updated afterwards.)

Interval and due:
  I   = (S' / FACTOR) · (r^(1/DECAY) − 1)
  I   = clamp(roundHalfEven(I), 1, 36500)        ← Python round(); use .toNearestOrEven in Swift
  due = T + I · 86400 s
```

`reps` counts reviews and `lapses` counts Again ratings after the first review. These are not part of FSRS but are shown in analytics.

## Replay

`Replay` is a pure reducer: `(LearnerState, Event, Pack) → LearnerState`. `LearnerState` holds memory, introductions, step progress, unit progress, can-do status, exercise history, focus items and daily activity.

- **Full rebuild (`rebuildAll()`):** start empty, apply all events ordered by `(at, id)`. Duplicate IDs are impossible (primary key), and replay is idempotent.
- **Incremental:** if a new event sorts after `last_applied`, apply it. If it sorts earlier (a late sync from another device), run `rebuildAll()`; it must fit the budget in `docs/02`. A per-key shortcut is an optional optimisation, allowed only behind a test that compares it with a full rebuild on randomised event orders.
- **Rebuild triggers:** a changed `derived_version` (reducer logic changed) or a changed pack `meta.content_hash` (content changed) also runs `rebuildAll()` at launch.
- **Resume cursor:** `step_progress.cursor` is derived, never written by an event: the number of exercises, in presentation order, that have a **final** attempt since the step's open `stepStarted` (the last one, which no `stepCompleted` follows). An attempt is final when its outcome is `correct`, `correctWithNote`, `almost`, `revealed` or `skipped`, or when `attemptIndex` is 2. The presentation order of a practice step is its block in file order, then its mix shuffled with SplitMix64 seeded by FNV-1a 64 of the step ID, so every device resumes at the same exercise.
- Events that reference IDs missing from the current pack (retired content) still count for memory if their `itemId` exists. Otherwise they are skipped and logged.

## Introductions and eligibility

A step introduces items at **step start** (`introduced` event) according to `step_introduces` in the pack:

| Step | Introduces |
|---|---|
| preview | each batch item: `read` and `listen`; plus `recall` and `speak` where that skill's status is P |
| story, listening, reading | items flagged new in the text: `read`, `listen` |
| note | every grammar point in the note's `grammar` list (`note_items`): `read`; plus `recall` if P |
| sounds | the sound item: `listen` |
| placement | every item in units before the start unit, per its status |
| mini-preview (`catchup`) | the missing (item, skill) pairs, see below |

**Grammar points** are introduced by their note. A point with status R or chunk may instead be introduced by the first preview **in its own unit** containing a chunk that `exemplifies` it (read only; no rule credit), or else by the first story or listening step of its unit where it is detected (read). A chunk from an earlier unit that exemplifies a later point (*scusi* in Unit 0, *sono nato* in Unit 1) never introduces it. A P point must have a note; check 4 fails a complete unit otherwise.

**Eligibility rule:** a text, exercise or review card is eligible for a learner if every `(item, skill)` in its `text_requires` or `exercise_requires` has an introduction. The lesson player checks eligibility on entering each step. If something is missing (possible after placement or a content update), it introduces it through an inline **mini-preview** (preview pairs for the missing items, one tap to continue; `docs/06` § Shared player behaviour) before continuing, never by silently showing it. Reviews, mixed practice, fluency replay and generated cards only ever use eligible content.

## Unit progression

- Unit states: `locked` → `available` → `in_progress` → `completed` (check finished) or `skipped` (placement).
- Unit 0 (or the placement unit) is available at start. Unit N+1 becomes available when Unit N is completed or skipped (ADR-16).
- Inside a unit, steps run in order: opener → lessons 1–3 → unit task → unit check → fluency replay (optional; it never blocks). A step may be revisited at any time; revisits create normal attempts.
- Resume: the derived cursor (§ Replay) lets a session stop anywhere.

## The Today planner

`Planner.today(now:)` returns:

- **Review:** the due count = scheduled pairs with `due ≤ end of today` (local day, 04:00 rollover) that have at least one eligible exercise or generated card, capped at the daily review limit (setting, default 60). Also an estimate in minutes (count × the learner's median seconds per card; default 18 s) and two example items.
- **New catch-up cards** (after placement): scheduled pairs introduced `via: placement` that have no memory yet, up to 15 a day.
- **Continue:** the first incomplete step in the earliest available unit.
- **This week:** active days this ISO week (a day counts with ≥ 1 completed step or ≥ 5 reviewed cards) against the weekly goal (default 5).
- **Stats:** words known (below) and units completed out of 13 (Units 0–12).
- **Recommendation:** if due > 40, the Review card is the primary action. Lessons are never blocked.

### Review session builder

1. Order cards: **focus items first** (including ones not yet due), then due date ascending, then lowest current retrievability, then `(itemId, skill)`. Size = min(due + focus, session target 20). The learner can continue with another 20.
2. Pick one exercise per card (`CardSelector`): candidates are exercises whose targets include the (item, skill), that are eligible, not shown in the last 2 days, and suitable for this device (speech availability and setting). Preferred formats by skill: recall → recall, cloze, sentence-building, dictation; read → choice (Italian → English), match; listen → sound-pair, choice with audio. Rotate to the format least recently used for this item. If there's no candidate, generate a card (exercise ID `gen:<skill>:<itemId>`):
   - **recall:** "Type the Italian for *croissant*". The prompt is the item's gloss up to the first `;`. The answer is the item's `recall_answer` if set. Otherwise: nouns accept the definite or indefinite article with the noun as focus (`{il|un} [cornetto]`; model answer = the display form without its gender mark); a bare noun is `correctWithNote` ("Say it with its article: il cornetto"); a wrong article with the right noun is a near-miss with outcome `almost` and the note "cornetto is masculine: il cornetto". Other words: the lemma, as focus. Chunks: `it` without trailing `… ? !` (a chunk whose `it` contains `/` must set `recall_answer`; lint enforces it). Grammar points get no generated recall: if no bank exercise is eligible, the card waits.
   - **read:** show the Italian (with audio) and pick the English gloss from 4 options. Distractors are glosses of eligible items with the same POS, preferring the same topic, drawn with the session RNG.
   - **listen (sounds):** play one word of a pair (session RNG) and choose between the two.
3. Interleave with the session RNG (SplitMix64 seeded by FNV-1a 64 of the `sessionId`): never the same item twice in a row, at most 2 consecutive cards of one format, and grammar cards spread evenly.
4. Each card answered Again first time is re-queued once at the end of the session, with a different exercise if one exists. This is a same-day review, handled by FSRS's short-term formula.
5. At most one skill per item per session. If two skills of an item are due, the other waits until tomorrow.

## Grading

### Normalisation (`Normalizer`)

1. Unicode NFC.
2. Map ’ ‘ ʼ ´ ` to `'`.
3. Lowercase with the `it_IT` locale.
4. Replace `. , ; : ! ? ¡ ¿ « » " “ ” „ ( ) [ ] – — …` with spaces, **except** `.` `,` `:` between two digits (`6,20`, `10:15`). A hyphen is kept only between two letters (`e-mail`); any other hyphen becomes a space.
5. Remove spaces next to apostrophes (`un' amica` → `un'amica`).
6. Collapse whitespace and trim.

Tokens are the space-separated parts. `stripAccents` removes combining marks after NFD. `fixtures/grading/normalizer.json` is the reference; where it is more specific than this list, the fixture wins.

**Accent-sensitive words** never get accent tolerance: e/è, si/sì, la/là, li/lì, da/dà, se/sé, ne/né, te/tè, di/dì.

### Typed answers (cloze, recall, generated cards, typed conversation turns)

1. If the normalised response equals a `near` pattern expansion, return that entry's outcome (default `wrong`) and hint.
2. For each expansion of the accepted pattern, align the response tokens with the expansion tokens (token-level edit distance). Costs: equal 0; **accent-only** difference 0.1 (not allowed for accent-sensitive words); **typo** 0.5 (Damerau-Levenshtein distance 1 between the accent-stripped tokens, expected token length ≥ 4 after stripping accents, *not* a focus token, and *not* another form of the same item); substitution, insertion or deletion 1. A slot takes its number of words (`docs/03`) at no cost, or is missing. Keep the cheapest expansion; on a tie, the one with fewer substitutions, insertions and deletions, then the earlier one.
   - **Inflection errors are never typos or accent slips:** if a mismatched response token is a known form (pack `forms`) of the same item as the expected token (*americana* for *americano*, *un* for *una*, *parlò* for *parlo*), it is a substitution with hint kind `ending`.
   - Focus tokens keep accent tolerance (*un [caffè]* answered *un caffe* is `correctWithNote`); only typos are refused.
3. Classify: cost 0 → `correct`; only accent-only differences → `correctWithNote` (show the accents); accent-only or typo differences only → `almost` (show the correction); anything else → `wrong`. Report the indices of mismatched tokens so the UI can underline them: indices into the best expansion (accents, typos, substitutions, missing tokens; what `fixtures/grading/typed-answers.json` checks) and indices into the response (accents, typos, substitutions, extra tokens). The hint kind is that of the first mismatch: `missing`, `extra`, `ending`, `realWord` (a known form of a different item) or `spelling` (anything else). A matched `near` entry still reports the mismatches against the accepted answer, for underlining.
4. Gendered alternatives: accept both forms unless the learner chose strict forms in Settings. The model answer shown in feedback uses the learner's form; with `both`, it shows the two forms joined (*nato/nata*). The model answer itself (audio, the production gate) stays masculine with `both` (`docs/03` § Personal slots).

### Other graders

- **Dictation:** compare word by word with the target; each word is marked `correct`, `accent`, `doubling`, `typo` or `wrong` (`fixtures/grading/dictation.json`). A difference that is only single versus double consonant (`corneto`/`cornetto`) is marked `doubling` with a note ("Listen again: cornetto has a double t"), even in a 3-letter word; other typos follow the typed rules (no tolerance below 4 letters). Words are aligned, so a missing word is marked `wrong` and the others keep their marks. Outcome: all `correct` → `correct`; only `accent`, `doubling` or `typo` marks → `almost`; any `wrong`, or any extra word, → `wrong`. (Unlike typed answers, an accent-only slip in dictation is `almost`: spelling is the point. The exceptions are the accent-sensitive words, where the accent makes a different word: *e* for *è* is `wrong`; and, as in typed answers, another form of the same item is `wrong`, never a typo or an accent slip.)
- **Sentence building:** the tile order must equal one accepted order → `correct`, else `wrong`. The hint highlights the first misplaced tile.
- **Choice, true-false, sound-pair:** the selected index equals the answer. **Match:** each pair is scored separately; per-pair outcomes go to that pair's target.
- **Speech transcripts (`TranscriptMatcher`):**
  1. Convert digits, prices and times in the raw transcript into Italian words with `ItalianNumbers` (`6,20 €` → `sei euro e venti`, `10:15` → `dieci e quindici`). This runs **before** normalising, which would split them.
  2. Normalise the transcript and every alternative.
  3. For each accepted expansion, align without regard to accents and with double consonants collapsed (ASR can't be trusted on length).
  4. Pass if every focus token matches and at least 80% of content tokens match. Content tokens are all tokens except the `functionWords` list in `fixtures/grading/transcripts.json`, which is normative (articles, simple and articulated prepositions, clitics, e/o/ma).
  5. Use the best result across transcript alternatives.
  6. Feedback says "I heard: …"; never call it pronunciation.
- **Content points (talk, writing):** each point lists patterns. A point is found if any expansion occurs as a contiguous token sequence in the normalised response, ignoring accents. Pass if found ≥ `pass`. Writing also checks the word count and flags tokens that aren't known forms (`forms` table) with edit distance 1 to a known form ("Did you mean famiglia?"); flags are advice and never fail the task.
- **English answers (relay):** `time` extracts `HH:MM`, `HH.MM` or `HH MM` and also accepts `HH ± 12`; `price` extracts a decimal with `,` or `.` (tolerance 0.001, currency words ignored); `number` extracts an integer; `text` matches any accepted English phrase as a token subsequence, case- and punctuation-insensitive.

### Fixtures

`fixtures/grading/typed-answers.json` holds the starting cases (pattern, response, learner forms → expected outcome and mismatched tokens). Every grader bug fixed in the beta adds a case. The pipeline uses the same normaliser rules in Python to validate patterns; `fixtures/grading/normalizer.json` keeps Swift and Python in agreement.

## Stepped feedback (`FeedbackMachine`)

```
awaitingFirst ──correct/correctWithNote──▶ done(success)        (show note if any)
      │         ──almost─────────────────▶ done(successWithCorrection)
      │         ──wrong──▶ hinted: underline mismatches; show near-miss hint ∥ exercise hint ∥ generic hint
      │                     └─▶ awaitingSecond ──correct/correctWithNote/almost──▶ done(successAfterHint)
      │                                        ──wrong──▶ answerShown: answer + one-line rule ──▶ done(failed)
      └── "Show answer" (any time) ──▶ answerShown (outcome revealed)
```

Generic hints, chosen by the first mismatch:

- "That's a real word, but not the one we need here." (`realWord`: the token is a known form of a different item)
- "Check the spelling."
- "Check the ending." (`ending`: another form of the expected item)
- "Something's missing." (deletion)
- "There's an extra word." (insertion)

For tapped formats, a wrong first choice is marked, the hint is shown and one more choice is allowed. Mixed-practice errors are never punished in the UI: no scores during practice, no lives. In check, final and placement contexts there is one attempt, no hint and no "Show answer".

## Unit check scoring

- Each check exercise has a `score` (default 1). In check, final and placement contexts, `correct` and `correctWithNote` earn the full score, `almost` earns half, and anything else earns zero. Talk and writing earn `score × found/required` (capped at `score`), and conversation earns `score × goals completed / goals`.
- Section score = earned / possible. Overall = total earned / total possible.
- **Passed** = overall ≥ 0.70 **and** every section ≥ 0.50 (Q11 default). A section is excluded, and flagged on the result screen, when the device can't do it (speaking with no speech recognition, or speaking switched off).
- **Can-do reached** when at least ⌈2/3 × n⌉ of its n tagged check exercises earned their full score.
- **Failed check:** the primary targets of wrong items become `focus_items` for 3 days (reviewed first, § Review session builder), and the result screen offers a retake from the next day. The next unit still unlocks (ADR-16).
- **Retakes:** `unit_progress.check_score` keeps the **best** score; `check_passed` is true once any attempt passed. Can-dos reached are the union over attempts.

## Placement

1. Offered in onboarding when the learner says they know some Italian.
2. Blocks for Units 1–8, five items each (`content/assessments/placement.yaml`, compiled into `assessments`): two vocabulary (recall or choice), two grammar (cloze) and one listening (choice).
3. Start with the Unit 1 block. If a block scores ≥ 4/5, go to the next; otherwise stop. The start unit is the first block that scored below 4, or Unit 9 if all eight blocks pass.
4. Write `placementCompleted` and one `introduced` event (via `placement`) for every item in units before the start unit. Those units become `skipped`. Their scheduled pairs enter the **new catch-up** queue (15 a day), so FSRS state is built from real reviews, never invented.
5. "Start from the beginning" (offered at any point) writes `placementCompleted` with `startUnit: u00` and no introductions.

## Final A1 check

Available once Unit 12 is completed; also in the final review unit. It has five sections modelled on CILS A1 — listening, reading, structures, writing and speaking — at 12 points each (`assessments`, id `final`). The indicative pass is ≥ 7/12 in every section, and the result screen says it is indicative. Final-check speaking items always record (`docs/09`), and writing answers and recordings can be exported for an examiner (`docs/12`).

## Progress metrics

- **Words known:** word and chunk items whose scheduled skill has `reps ≥ 2` and current retrievability ≥ 0.85.
- **Skill bars (Words screen):** 0–4 bars from current retrievability per skill (0: no memory; 1: R < 0.5; 2: < 0.7; 3: < 0.9; 4: ≥ 0.9).
- **Can-dos reached** per unit (from checks).
- **Weekly goal:** active days this ISO week against the goal. There is no streak counter in the MVP.
