# 08 — Completing A0

Status: execution plan
Scope: take the A0 band from one covered scenario to thirteen, and make
the word chain — lesson text → vocabulary entry → dictionary — complete
and enforced. Design is `07-lessons-and-coverage.md`; this is the work
breakdown for one band, plus the two design refinements A0 forces.

---

## 1. Why A0 first, and why it closes cleanly

A0 is the app's crash course: thirteen linearly-sequenced scenarios from
the plane to the last day. It is also, arithmetically, the neatest band
in the spec.

| | count |
| --- | --- |
| A0 scenarios | 13 |
| × 3 depths | **39 lessons** |
| A0 grammar points | 22 |
| A0 communicative functions | 17 |
| A0 can-dos | **13** |
| A0 lemmas | 210 (+ ~40, see §2) |

**13 can-dos × 3 rising capstones = 39 = exactly one capstone per
lesson.** Every A0 can-do already maps to one or two A0 scenarios, so the
assignment is nearly forced rather than invented:

```
a0.greet_take_leave  -> a0-01, a0-03      a0.tell_time_days -> a0-08
a0.say_who_i_am      -> a0-02, a0-10      a0.ask_where      -> a0-04
a0.order_something   -> a0-03, a0-06      a0.identify_things-> a0-04
a0.yes_no_answers    -> a0-10             a0.say_likes      -> a0-07
a0.numbers_prices    -> a0-02, a0-08      a0.ask_for_help   -> a0-05, a0-11
a0.buy_ticket        -> a0-09             a0.read_signs     -> a0-04, a0-09
a0.catch_courtesy    -> a0-01, a0-12
```

`a0-13-ripasso` carries none, and shouldn't: it lists all 22 grammar
points and all 17 functions because it is the review. Under the spiral it
becomes the one lesson that **introduces nothing and revisits everything
at `perform`** — the last pass for anything that hasn't had one.

### One deviation from 07 §4a, deliberate

07 proposes a scenario's band rising by at most one across its depths
(A0 → A0 → A1). For the A0 band specifically, **all three depths stay
A0.** A0 has 22 grammar points across 13 scenarios — under two per
scenario, all comfortably introduced by depth 2 — so depth 3 has nothing
new to carry and is better spent as the free-performance pass that closes
each can-do. Bridging into A1 belongs to the A1 scenarios, which have
their own depth ladder. Revisit if A0 turns out to need a runway into A1
that the A1 depth-1 lessons don't provide.

---

## 2. The word chain, and the two things wrong with it

> every Italian word in a lesson is linked back to vocabulary, which in
> turn is linked back to the dictionary

The machinery for this already exists and is well-designed:
`vocab_link.build_index` generates surface forms *forward* from each spec
lemma and matches them literally, so it can never invent a headword (the
module docstring records why: the legacy app guessed lemmas backwards and
filled learner vocabularies with non-words like "capiscare"). The build
reports its work — *"655 word links across 198 items, 8 ambiguous forms
skipped"* — and `Encountered` events add linked words to the learner's
vocabulary the moment a lesson shows them.

The chain is: **lesson text → surface form → spec lemma → dictionary
entry** (`spec/it/vocab.yaml`: `id`, `cefr_level`, `pos`, `gloss`) **→
vocab card**, when one is authored.

Auditing the current pack against the linker's own rules — Italian spans
only, multi-word forms matched first — **99 distinct tokens across 807
occurrences resolve to nothing.** Four causes, two of them real bugs:

| cause | examples | count |
| --- | --- | --- |
| **Function words are not in the vocabulary at all** | `un la il una di a in e con non che mi ti si io tu lui lei` | ~40 lemmas, ~600 occurrences |
| **Elision splits a token and orphans both halves** | `dov'è` → `dov` + `è`; `l'acqua` → `l` + `acqua`; `c'è`, `quant'è` | 4 forms, ~65 occurrences |
| Proper nouns | `anna marco roma milano londra italia francia` | ~12, legitimately not vocabulary |
| Genuinely missing content words | `ecco`, `quindici`, `alle`, `dalle` | ~10 |

The first is the significant one. A0 lemmas break down as 108 nouns, 34
verbs, 21 adverbs, 21 adjectives, 12 numerals, 10 interjections, 2
phrases and **2 pronouns — with no articles, prepositions or
conjunctions at all.** The learner meets `il` in the very first reading
and the app has nothing to say about it: it is not in their vocabulary,
it has no gloss, and tapping it could only ever do nothing.

### The refinement A0 forces: not every lemma wants a flashcard

07 §3 says a lemma's home lesson must ship it a `vocab_card`. Applied to
`il`, that is a flashcard whose front is "il" and whose back is "the" —
worse than useless, and it would put forty function words into the SM-2
rotation to compete with real words.

**Split the obligation by part of speech.** Every lemma needs a
*dictionary* entry and must be linkable. Only content words need a
*card*:

- **Cardable** (`noun, verb, adj, adv, num, inter, phrase`) — SRS
  material; the home lesson owes a `vocab_card` and the lemma follows the
  three-rising-passes rule.
- **Grammatical** (`art, prep, pron, conj`) — carried by the grammar
  point that teaches them. The home lesson owes them nothing extra; they
  need a gloss so a learner can look them up, and they must resolve so
  they are never an unlinked word on screen.

`art` is a new `pos` value; the existing set has no article category.

---

## 3. Plan

### Phase A — close the word chain (blocks everything else)

1. **Add the missing function words** to `spec/it/vocab.yaml` as A0
   entries with the new/existing grammatical POS: articles (`il la lo i
   le gli un una`), prepositions (`di a da in con su per tra fra`),
   pronouns (`io tu lui lei noi voi loro mi ti ci si`), conjunctions (`e
   o ma che`), negation (`non`). ~40 entries, each with a gloss.
2. **Teach the linker elision.** `dov'è`, `c'è`, `quant'è`, `un'`, `l'`,
   `dell'` currently split into an orphan fragment plus a word. The
   apostrophe should attach to the *left* fragment as an elided form of
   its lemma (`l'` → `il/la`, `un'` → `una`, `dov'` → `dove`, `c'` →
   `ci`, `quant'` → `quanto`) rather than being dropped.
3. **Register proper nouns.** A small `spec/it/proper_nouns.yaml` (people,
   cities, countries) so `Roma` reads as a known name rather than an
   unlinked word — and so the check in step 5 can be strict.
4. **POS-driven card rule** in `coverage.py`: `home-missing-card` applies
   to cardable POS only; grammatical lemmas need a dictionary entry and
   nothing more.
5. **Enforce it.** A new coverage rule — `unlinked-word` — failing when
   any Italian token in a shipped item resolves to no lemma and is not a
   registered proper noun. This is the guarantee, made checkable: after
   this, a word cannot reach the learner without a dictionary entry
   behind it.

Phase A is where the "8 ambiguous forms skipped" line gets revisited too
(`saluti`, `stato`, `uscite`, `lavori` — noun/verb collisions the index
drops rather than guessing). Dropping them is the right default; the fix
is to let a lemma declare a disambiguating form, not to guess.

### Phase B — the 13 scenario manifests (spec only)

Each A0 scenario grows from one depth to three, with authored `label`,
`goal`, `summary`, `scene_setting` and `outro` per depth, and:

- **d1** introduces the scenario's grammar, functions and content lemmas;
  capstones its can-do at `use`.
- **d2** revisits all of it at `use`, introduces any second grammar
  point, adds writing; capstones at `use`.
- **d3** introduces nothing, revisits at `perform`; capstones at
  `perform` — the pass that closes the can-do.
- `a0-13-ripasso` is d1–d3 of pure `perform` revisits across the whole
  band, and carries the can-dos that need a third pass.

Done when `validate --coverage` reports zero findings for every A0
grammar point, function, can-do and lemma.

### Phase C — content, scenario by scenario in sequence order

Per scenario, the required set across its three lessons:

| | per scenario | A0 total | exists |
| --- | --- | --- | --- |
| capstone tasks | 3 | 39 | 3 |
| grammar refs | ~2 | 22 | 11 |
| drills (6 per introduced GP) | ~12 | 132 | ~137 (re-homing needed) |
| readings | 3 | 39 | 6 |
| listenings | 3 | 39 | 4 |
| speaking prompts | ~4 | 52 | 21 |
| writing prompts | 2 | 26 | 7 |
| vocab cards (content words) | ~16 | 210 | 37 |

**≈ 560 items for the band, of which ≈ 360 are new.** Vocab cards and
listenings are the two big holes; listenings are the expensive ones,
since each needs a dialogue and eventually audio.

Order: `a0-01` → `a0-13` by `sequence`, because a lesson's revisits can
only point at material an earlier lesson has already introduced, and
`validate --coverage` checks exactly that ordering.

### Phase D — prove it

- `validate --coverage` clean for the A0 band.
- `core/tests/closes_a0.rs`: walk all 39 lessons in composer order as a
  learner, and assert all 13 A0 can-dos reach `achieved`, no slot ever
  falls short, and no lesson re-teaches material an earlier one taught.
- Re-run the walkthrough from 07 §1 — the one that found six defects —
  and confirm the session it now produces is the lesson it advertises.

---

## 4. What this does not cover

- **A1/A2** — 24 scenarios, 141 grammar points, 182 functions, 55
  can-dos, and the depth-band question 07 §4a leaves open. A0 closing is
  what makes that work mechanical rather than exploratory.
- **Audio** for the 39 listenings. The shell falls back to system TTS
  (`DialogueSpeaker`), so lessons play without it, but a listening
  activity read by a synthesiser is a placeholder and should be labelled
  one until `generate-audio` runs against a real provider.
- **Images.** `generate-images` exists and the scenarios name their art;
  nothing here depends on it.
