# 09 — Generating a band

*Written after finishing A0 by hand-driving eleven agents. This is what
that cost, what the generator could not do, and what it would take for
A1 and A2 to be a command rather than a project.*

Related: `07-lessons-and-coverage.md` (the lesson object and the closure
contract), `archive/08-completing-a0.md` (what A0 needed and what it
exposed).

---

## 1. The question, answered

**Yes — this belongs in `generate`, and the distance is larger than it
looks.** `authoring/generate.py` predates the lesson object entirely. It
has no notion of `lesson_id`, no notion of `demand`, and no notion of the
`task` item type — the three things the closure contract is built on. It
generates *for a grammar point*, and the unit of obligation is now
*lesson × depth*.

The blunt version: the generator can draft a drill bank. It cannot draft
a lesson, cannot tell whether what it drafted is correct beyond schema
shape, and cannot fix anything it got wrong.

---

## 2. What `generate` does today

```bash
uv run python -m authoring.cli generate --type drill --gp vorrei --count 10
```

| | today |
| --- | --- |
| **scopes** | `--gp`, `--scenario`, `--cando`, `--theme` |
| **types** | drill, reading, listening, vocab, speaking, writing, grammar_ref |
| **prompt carries** | scope context, allowed lemma list, existing prompts to avoid |
| **output** | `<slug>.draft.yaml`, appended |
| **validation** | `validate_pack` on the batch — schema + referential integrity |
| **on failure** | raises; the whole batch is discarded |
| **rounds** | one |

What it does well is worth keeping: the scope abstraction is right, the
allowed-vocabulary list is in the prompt, existing prompts are shown to
suppress near-duplicates, and ids are allocated by the tool rather than
asked of the model.

Missing from the type list: **`task`**. That is the only item family
carrying `axis: cando`, and therefore the only thing that can move a
can-do to *achieved*. The generator cannot produce the item the whole
lesson design exists for.

---

## 3. What A0 actually cost

Eleven agents, one or two scenarios each, all with the same hand-written
brief and a per-scenario gap list I generated for them:

| | |
| --- | --- |
| subagent tokens | **~1.71 M** |
| tool calls | **694** |
| wall clock | ~20 min per agent, run in two waves |
| items produced | **680** |
| | **≈ 2.5 k tokens per item** |

Most of those 694 tool calls were not authoring. They were the loop:
run `validate --quality`, read the warnings, find which are mine, rewrite,
re-run. Every agent built that loop by hand, from prose instructions, and
each one rebuilt it independently.

Applying the same shape to what remains:

| | A0 (done) | A1 | A2 |
| --- | --- | --- | --- |
| scenarios | 13 | 24 | **0 — none designed yet** |
| grammar points | 22 | 59 | 82 |
| functions | 17 | 84 | 98 |
| can-dos | 13 | 29 | 26 |
| cardable lemmas | 247 | 163 | 34 |

A1 and A2 together want ~846 drills alone at six per grammar point, and
something on the order of **1,900 items**. At A0's observed rate that is
**~4.8 M tokens** — affordable, but only if it runs unattended. It cannot
run unattended today.

**A2 has no scenarios at all.** Designing 20-odd A2 situations is a
separate, human-shaped job that must happen before any generation.

---

## 4. Three classes of gap

### a. It cannot express the lesson

`generate` has never heard of the lesson object. Concretely:

- No `--lesson` scope. The natural invocation — *"fill everything
  `a1-04-al-mercato.d2` owes"* — cannot be written.
- No `task` kind, so no capstones.
- `lesson_id` and `demand` appear nowhere in `generate.py`: not in the
  shapes shown to the model, not stamped from the scope. Every item it
  drafts today lands unhomed at the default rung.
- No concept of **perform supply** — that the ids a `d3` revisits at
  `perform` must be carried by some `perform`-tier item's evidence.
  Distributing ~19 lemmas per scenario across the d3 task, writing prompt
  and speaking prompts was hand work in every one of the thirteen
  scenarios.

### b. It cannot check its own work

Three tiers of check exist. `generate` runs the first, on its own batch:

| tier | what it catches | runs in `generate`? |
| --- | --- | --- |
| `validate_pack` | schema, unknown ids, duplicates | **yes** (batch only) |
| `quality.py` | above-level vocabulary, unsolvable cloze, distractors colliding with the key, near-duplicate prompts, elision errors | **no** |
| `coverage.py` | the closure contract, home obligations, perform supply, **`unlinked-word`** | **no** |

`unlinked-word` is the one that mattered most in practice. Every Italian
word in a shipped item must resolve, through `vocab_link`'s forward
surface generation, to a spec lemma. That single constraint dominated the
A0 authoring: agents rewrote whole dialogues around it, and four separate
tooling bugs surfaced only because humans-in-the-loop noticed the
generated text failing:

- compound numerals (`quarantacinque`) resolved to nothing — in the
  lesson about the rule that builds them;
- `cos'` and `anch'` were not in the elision map, so *«Che cos'è?»* failed
  in the lesson whose entire subject is *«Che cos'è?»*;
- `questo`/`quello` were in `quality.py`'s function-word list but in no
  dictionary;
- the possessive plurals `miei`/`tuoi`/`suoi`.

A generator that ran the check would have found all four on its first
batch.

### c. It cannot recover from a mistake

`parse_response` raises on the first bad entry and the batch is lost —
including the nine good items next to the bad one. There is no retry, no
repair, no partial accept. When a model writes `back: no` and YAML 1.1
reads it as boolean `false`, the run dies with a type error pointing at
the schema rather than at the line. (That trap is fixed for the *build*
path — `build_pack.ContentLoader` — but **`generate.py` still calls
`yaml.safe_load` at lines 444 and 513**, so generated content can still be
silently coerced and written back corrupted. One-line fix, worth doing
now.)

Also live, and a release blocker: **`review.py`'s `FAMILIES` map has no
`task` entry.** The 42 A0 capstones cannot be opened in the review UI, so
they can never move from `draft` to `reviewed`, so they can never ship.
The pack builds only `reviewed` items.

---

## 5. The lever: most of this was scheduling, not authoring

The single most useful thing I learned: **of the work A0 took, only the
Italian needed a model.** Everything else was derivable.

| what I did by hand | actually |
| --- | --- |
| homed 145 existing items at a lesson | a join on evidence vs the manifests |
| gave 239 lemmas a home and a `meet→use→perform` ladder | one uniform rule, ~80 lines |
| worked out what each lesson still owed | `coverage.py` already computes exactly this |
| spread perform evidence across d3 items | bin-packing |
| resolved 10 duplicate `vocab.<lemma>` ids | one card per lemma, prefer reviewed |
| placed capstones so each can-do closes where it is taught | a comparison of two orderings |

None of that should ever reach a prompt. It is deterministic, testable,
and cheap. The model should be asked for one thing: **Italian that fits a
slot whose every constraint is already decided.**

This also fixes the worst failure mode of the parallel run — eleven agents
independently choosing ids, discovering the same constraints, and
colliding. If placement is computed centrally, agents receive a filled-in
slot and return prose.

---

## 6. The design

### 6a. `plan-band` — deterministic, no API

```bash
uv run python -m authoring.cli plan-band --band A1
```

Writes the spec-side scheduling and prints what it decided:

1. Home every grammar point, function and lemma at a lesson; build the
   `meet → use → perform` ladder across the scenario's three depths.
2. Place each can-do's capstones at the scenario that teaches the last
   piece of its decomposition — and **report** any descriptor that cannot
   close where it is taught, which is exactly the `say_likes` /
   `ask_where` / `ask_for_help` finding, surfaced instead of discovered.
3. Backfill `lesson_id` on any existing item from its evidence.
4. Emit, per lesson, the **required set**: the items it owes, each with
   its `lesson_id`, `demand`, and the evidence it must carry.

Output is a plan file the next step consumes. Everything here is already
prototyped — the scripts that did it for A0 are in this session's
scratchpad and should be promoted into `authoring/`.

### 6b. `generate --lesson` — the required set, one slot at a time

```bash
uv run python -m authoring.cli generate --lesson a1-04-al-mercato.d2
uv run python -m authoring.cli generate --band A1 --jobs 8
```

The scope resolver gains a `lesson` kind whose context is the manifest
the human already wrote — `label`, `goal`, `scene_setting`, `outro`,
`introduces`, `revisits`, `capstones` — plus the required set from
`plan-band`. The prompt asks for exactly the missing items, with
`lesson_id` and `demand` stamped by the tool.

New `Kind`: `task`, with the `a0-03-al-bar` capstones as the shape
example. The rung is the point — `use` shows a model, `perform` does not.

### 6c. The fix loop

This is the piece that turns 694 hand-driven tool calls into a command.

```
draft ──► parse (per entry, not per batch)
            │
            ├── entries that parse ──► check ──► accept the clean ones
            │                            │
            │                            └── findings ──┐
            └── entries that don't ─────────────────────┤
                                                        ▼
                                          repair prompt: the failing
                                          entry + its findings verbatim
                                          + what a fix looks like
                                                        │
                                          ◄─────────────┘  (max N rounds)
```

Rules that make it work:

- **Per-entry, not per-batch.** Nine good items must survive the tenth.
- **Check means all three tiers**, scoped to the batch: schema, quality,
  and the coverage rules that are decidable per item — above all
  `unlinked-word`, which is the constraint the model will actually fight.
- **Findings go back verbatim.** `«ventidue» resolves to no lemma` is a
  better instruction than any prose about number formation.
- **Bounded.** Three rounds, then write what survived, and print what is
  still open as a work list. Never silently drop.
- **Idempotent.** Re-running fills only what is still missing, so the
  command can be run repeatedly until coverage is clean.

### 6d. What the prompt must carry that it does not

Learned the hard way, one line each:

- The **lesson manifest**, not just the scenario: a d2 that reuses d1's
  situation with less scaffolding is a different brief.
- `demand` explained as a rung, with the consequence spelled out.
- **The «guillemets» convention** — it is what tells the validators which
  half of a mixed-language string is Italian, and nothing in
  `generate.py` mentions it.
- The **perform-supply obligation** for a d3 batch, with the specific ids.
- **Surface forms, not just lemmas.** The allowed list today is lemma ids;
  the model writes inflected Italian and the linker decides. Passing
  `vocab_link.build_index()`'s surface set — or at least naming the
  generated classes (plurals, conjugations, elisions, articulated
  prepositions, compound numerals) — removes a whole class of retry.
- **Ids are allocated by the tool**; for vocab, one card per lemma, and
  the tool refuses a second rather than minting `.002`.

---

## 7. Checks to move, add, or fix

| check | today | should be |
| --- | --- | --- |
| schema + refs | in `generate`, batch-fatal | in the loop, per entry |
| `quality.py` (5 rules) | `validate --quality` only | in the loop |
| `unlinked-word` | `validate --coverage` only | in the loop, first-class |
| home obligations, perform supply | `validate --coverage` only | in `plan-band`, as the required set |
| `--band` gate | **exists** (added for A0) | wire A1 in as it closes |
| YAML `no`/`yes` coercion | fixed in `build_pack` | **`generate.py` still uses `yaml.safe_load`** |
| review UI | 7 families | **add `task`, or A0 cannot ship** |
| `review.COVERAGE_TARGETS` | per-GP item counts | superseded by the contract; retire |

---

## 8. Sequencing

| | | cost |
| --- | --- | --- |
| 0 | `generate.py` → `load_content_yaml`; `task` in `review.FAMILIES` | minutes; one is a release blocker |
| 1 | `plan-band`, promoted from the A0 scripts | ~a day, no API |
| 2 | `task` Kind + `--lesson` scope + `lesson_id`/`demand` in the shapes | ~a day |
| 3 | the fix loop (per-entry parse, three-tier check, bounded repair) | the real work |
| 4 | `--band A1 --jobs N` and run it | tokens, not time |
| 5 | human review pass | unavoidable, see §9 |

Steps 1–3 are worth doing before A1 even if A1 were the last band: they
are what makes the result checkable rather than merely produced.

---

## 9. What stays human

- **A2's scenarios.** There are none. Inventing 20 situations that carry
  82 grammar points is curriculum design, not generation.
- **Lesson manifests.** The A0 ones — *"The drinks trolley reaches your
  row… you have about four seconds"* — are the best writing in the pack,
  and they are what makes the generated content coherent. Generate *from*
  them, never *of* them.
- **The can-do decompositions.** Trimming `say_likes` changed when the app
  congratulates a learner. `plan-band` should surface the mistiming; a
  person decides.
- **The word list.** A0 exposed three functions whose own `patterns` field
  uses words the band does not contain (`ripetere`, `più`, `bisogno`,
  `andata`/`ritorno`). Adding a lemma obliges a home, a card and three
  passes. A tool can find these; it should not fix them.
- **Review.** The build ships only `reviewed`, and 659 A0 items are still
  `draft`. Nothing above changes that.
