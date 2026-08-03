> **Archived — done.** A0 closed on 2026-08-03: 13 scenarios, 39 lessons,
> 680 items, and `validate --coverage --band A0` reporting `contract
> satisfied`. `core/tests/closes_a0.rs` plays the whole arc and every A0
> can-do comes out *achieved*.
>
> Two things here outlived the plan and are still live:
> §4's list of words the A0 vocabulary lacks (three functions cannot say
> what their own `patterns` field claims), and the finding that most of
> this work was scheduling rather than authoring — which is what
> `09-generating-a-band.md` is built on.

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

### Phase A — close the word chain (blocks everything else) — **done**

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

### Phase B — the 13 scenario manifests (spec only) — **done**

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

Phase B closed the structure but not the placement, and three things
came out of finishing it that the plan above did not anticipate:

- **The can-dos had to be trimmed before the capstones could be
  placed.** Three descriptors listed a part they do not need, which
  pushed the achievement past the lesson that teaches the skill.
  Decision 36.
- **The lemma ladder is uniform**: every cardable A0 lemma is
  introduced at its scenario's `d1`, used at `d2`, produced at `d3`.
  Decision 37.
- **145 already-written A0 items had a scenario but no lesson.** They
  were re-homed mechanically, at the lesson that teaches what each one
  exercises — cheap, and it cleared a third of the `home-missing-*`
  findings before a line of new content was written.

### Phase C — content, scenario by scenario

Per scenario, the required set across its three lessons:

| | at the start of C | now |
| --- | --- | --- |
| capstone tasks | 3 | **42** |
| grammar refs | 12 | **22** |
| drills | 124 | **199** |
| readings | 4 | **40** |
| listenings | 2 | **39** |
| speaking prompts | 17 | **76** |
| writing prompts | 5 | **15** |
| vocab cards | 34 | **247** |
| | | **680 items across 39 lessons** |

Ordering: a lesson's revisits can only point at material an earlier
lesson has already introduced, and `validate --coverage` checks exactly
that. The manifests fix the ordering, so the scenarios themselves were
authored in parallel, one agent per scenario, against the frozen spec.

### Phase D — prove it — **done**

```
uv run python -m authoring.cli validate --quality --coverage \
    --include-draft --band A0
```
```
111 lessons; A0 coverage:
  cando       13 / 13   covered
  function    17 / 17   covered
  grammar     22 / 22   covered
  vocab      283 / 283  covered
  contract satisfied
0 errors, 0 warnings
```

`core/tests/closes_a0.rs` plays all 39 lessons in curriculum order
against the real bundle and asserts every A0 can-do comes out
`achieved` — not `in_progress`, which is what a capstone with an
untaught decomposition leaves behind. Its sibling checks the composer
walks the arc unpinned, offering the scenarios in order rather than
jumping around. Both pass.

The band is closed. What is left for A0 is polish, not structure: real
art in place of the mock renders, audio for the 39 listenings, and a
human review pass to move 659 items from `draft` to `reviewed` — the
build only ships `reviewed`, so nothing here is releasable yet.

---

## 4. What this does not cover

- **A1/A2** — 24 scenarios, 141 grammar points, 182 functions, 55
  can-dos, and the depth-band question 07 §4a leaves open. A0 closing is
  what makes that work mechanical rather than exploratory.
- **Audio** for the 39 listenings. The shell falls back to system TTS
  (`DialogueSpeaker`), so lessons play without it, but a listening
  activity read by a synthesiser is a placeholder and should be labelled
  one until `generate-audio` runs against a real provider.
- **Images.** Every one of the 39 lessons now has art, generated with
  the mock provider. Real generation is a keyed run.

### The gap Phase C found: A0 cannot say some of what A0 claims

Writing 39 lessons inside the closed A0 word list turned up something
the spec cannot see about itself — **three communicative functions use
words in their own `patterns` field that the A0 vocabulary does not
contain**:

| function | its own pattern | missing at A0 |
| --- | --- | --- |
| `a0_chiedere_aiuto` | «Può ripetere, per favore?» / «Più lentamente» | `ripetere`, `più`, `lentamente` |
| `a0_descrivere_problema` | «Ho perso…» / «Ho bisogno di…» | `perdere` (A2), `bisogno` |
| `vocab_viaggio` | *andata e ritorno* | `andata`, `ritorno` |

So the lesson labelled *Più lentamente* contains nothing that asks for
slower speech, and the one labelled *Andata e ritorno* cannot name a
return ticket. The content that shipped is honest Italian — «non ho
capito», «come?», «andiamo oggi e veniamo domani» — and arguably better
teaching, but it is not what the descriptor promises.

Also absent and repeatedly wanted: `mezzo`/`quarto`/`meno` (so clock
times are all "e trenta", never "e mezza"), `allora`, `troppo`, `quale`,
`volta`, `me`, `biglietteria`, `ritardo`, `partenza`/`arrivo` as nouns.

This is a curriculum decision, not a bug: adding a lemma at A0 obliges a
home lesson, a card and three rising passes. Left for a deliberate pass
over the A0 word list.

Four things that *were* tooling bugs were fixed rather than worked
around: compound numerals (`quarantacinque` resolved to nothing, in the
lesson about the rule that builds it), the `cos'` and `anch'` elisions,
the demonstratives `questo`/`quello` (in `quality.py`'s function-word
list but in no dictionary), and the possessive plurals `miei`/`tuoi`/
`suoi`.

---

## 5. The A0 assignment, resolved

Computed from what the scenarios already declare, so Phase B is
transcription plus prose rather than invention. Re-derivable from
`spec/it/scenarios.yaml` at any time; recorded here because the capstone
placement took two judgement calls.

### Grammar and functions: homes fall out cleanly

**All 22 A0 grammar points and all 17 A0 functions get a unique home**
with no orphans and no contested claims: the home is the earliest
scenario in `sequence` order that lists it, and `a0-13-ripasso` is
excluded because it lists the entire band.

| # | scenario | introduces |
| --- | --- | --- |
| 1 | in-aereo | `saluti` `polite_exp` `pronun_bas` · `a0_salutare` `a0_ringraziare` `a0_rispondere_si_no` |
| 2 | in-albergo | `mi_chiamo` `num_0_20` · `a0_presentarsi` `a0_dire_nome` `a0_contare` |
| 3 | al-bar | `art_un_una` `vorrei` `vocab_cibo` · `a0_ordinare` `a0_chiedere_cortesemente` † |
| 4 | in-giro | `art_il_la` `dove_e` · `a0_chiedere_dove` `a0_scusarsi` |
| 5 | chiedere-aiuto | `prep_place` · `a0_chiedere_aiuto` |
| 6 | a-pranzo | `che_cose` · `a0_identificare` |
| 7 | mi-piace | `mi_piace` `art_i_le` · `a0_esprimere_gusti` |
| 8 | i-numeri-grandi | `num_20_100` `ore_giorni` · `a0_dire_ora` |
| 9 | in-viaggio | `vocab_viaggio` · `a0_comprare_biglietto` |
| 10 | conoscere-qualcuno | `essere_pre` `subj_pron` `simp_sent` |
| 11 | un-problema | `avere_pre` `si_no_non` · `a0_descrivere_problema` |
| 12 | ultimo-giorno | `a0_congedarsi` |
| 13 | ripasso | — (introduces nothing; revisits the band at `perform`) |

† Already authored (docs/plans/07 step 4) and therefore frozen — which
settled a question the first draft of this table got wrong. That draft
moved `a0_chiedere_cortesemente` to lesson 1 on the reasoning that you
learn *per favore* on the plane. True, but al-bar already introduces it,
and two homes is an error the checker rejects outright: a lemma, point or
function is introduced once or the composer cannot know which lesson owes
it a reference page. The frozen lesson wins. `vocab_cibo` is likewise
homed at the bar rather than at lunch, because an A0 learner orders a
coffee before they ever sit down to a meal; `a0-06` revisits it.

`a0_congedarsi` stays at lesson 12, and the arc is better for it:
`ultimo-giorno` is where you actually learn to say goodbye.

Lesson 13 introduces nothing. That is correct: `ripasso` is the review,
and exists to be the last `perform` pass for material taught earlier.

**The rule that falls out of authoring these in parallel: a
cross-scenario revisit must be at `perform`.** By the time a scenario's
depth 3 has run, its own material is already at `perform`, so a later
lesson revisiting it at `use` is a fall and trips `falling-demand`. Only
material a scenario introduced itself can be revisited at `use`, at its
own depth 2.

### Can-dos: capstoned where the decomposition is finally taught

A can-do cannot be proved before ~80% of its grammar and functions have
been taught, or `folds.rs` will never move it to *achieved* however well
the learner performs. Placing each one at the earliest scenario it owns
that satisfies that gives:

| scenario | can-dos capstoned there (×3 depths, rising to `perform`) |
| --- | --- |
| in-aereo | `catch_courtesy` |
| al-bar | `order_something` ✓ done |
| chiedere-aiuto | `ask_where` |
| a-pranzo | `identify_things` |
| i-numeri-grandi | `numbers_prices`, `tell_time_days` |
| in-viaggio | `buy_ticket`, `read_signs` |
| conoscere-qualcuno | `say_who_i_am` |
| un-problema | `yes_no_answers`, `say_likes`, `ask_for_help` |
| ultimo-giorno | `greet_take_leave` |

**13 can-dos × 3 = 39 capstones across 39 lessons** — the totals match,
though the distribution is lumpy: five scenarios carry none and
`un-problema` carries three.

That lumpiness is a finding, not just an inconvenience. `say_likes` is
taught at lesson 7 but cannot be *proved* until lesson 11, because its
descriptor reaches for grammar that nothing teaches until then; the same
is true of `ask_where` (taught 4, provable 5) and `identify_things`
(taught 4, provable 6). Either the descriptors over-decompose, or the
scenario order should teach those pieces earlier. Worth a pass over
`can_do.yaml` before A1, where the same shape will recur at greater
scale — but not worth blocking A0 on: capstoning late is pedagogically
defensible (it is a delayed test of something already learned), and the
alternative is a can-do that never closes.
