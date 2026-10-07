---
name: italian-content
description: Draft, revise or fix Italian course content (items, stories, notes, exercises, conversations, checks) in content/ so it passes the checker and the content lead. Use for any work on content/*.yaml, for the item graph, and for fixing `make check-content` failures.
---

# Writing Italiano course content

You draft; people decide. Everything you write is a **draft** until the content lead approves it. Approved files are read-only (a hook blocks edits).

## Read before writing

1. The unit spec `content/units/<NN-slug>/unit.yaml`: can-dos, grammar with status, word budget, texts, tasks. It is the contract.
2. `content/story-bible.yaml`: cast, places, timeline and the **register matrix** (who says tu or Lei to whom, by unit).
3. Items: `content/items/u00…uNN.yaml` (what's known so far and what this unit introduces), and `content/grammar/points.yaml`.
4. The golden sample `content/units/02-al-bar/lesson-1.yaml`. Copy its shape.
5. `rules.md` (the 12 content rules and the 10 cohesion rules), `style-guide.md` and `exercise-cookbook.md` in this folder.
6. The formats: `docs/03-content-model.md` (YAML, IDs, answer patterns) and `docs/06-lesson-types.md` (every step kind and format).

## Procedure for a lesson

1. **Plan backward.** List the lesson's can-dos, the grammar point(s) its note teaches, and the 10–25 new items (in the items file with `lesson: <this lesson>`). Decide which go in the preview (6–12, batches of ≤ 6) and which are met glossed in the story (≤ 5% of story tokens).
2. **Story:** one scene with the recurring cast, inside the unit's word range. Prices, times and facts must match the unit's other files (the task's menu is the price list) and `story-bible.yaml`. Use known words plus this lesson's items. Recycle earlier units (≥ 30% of content words). Write voiced numbers in words. Every dialogue line has `speaker`, and `to` + `register` when someone is addressed. 2–4 comprehension questions in English, about meaning, not form.
3. **Note:** built from the story's own sentences (≥ 2 `examples` from this story). Short paragraphs, one table, one tip. No overgeneralisation.
4. **Practice:** a block of 8–14 items on the new material that reuses story sentences first (cloze, recall, sentence building, dictation, repeat), then a mix of 4–8 items that interleave it with confusable earlier items (essere/avere, un/una, tu/Lei…). Every new P item gets at least 4 retrievals in the lesson, counting the preview (about 5 is the aim).
5. **Sounds:** 2–3 sound-pair items on the unit's sound focus, using words from the scene where possible.
6. **Use:** a 2–3-turn conversation (or a spoken recall) in the story's situation.
7. **Tag everything:** each exercise gets ≥ 1 `cd:` or `sy:` tag and its primary `targets`.
8. **Check:** run `make annotate` (refreshes the lock files under `content/.annotations/`; never edit those by hand), then `make check-content`, and fix every error (table below). Then run the **content-critic** subagent on the file and fix what it finds.
9. **Report:** what you drafted, the checker summary, the critic verdict, open questions for the content lead (facts, register choices, missing items), and any `allow:` lines you used, with reasons.

## Fixing checker errors

| Error | Usually means | Fix |
|---|---|---|
| untaught lemma *x* | a word from a later unit, or not in the item graph | rephrase with known words; or, if the unit spec allows it, add the item to this unit's items file (with gloss, gender, status, lesson) and preview it or gloss it as new |
| morphology gate | a verb form not unlocked yet (a plural person, passato prossimo, future, imperfetto, conditional) | rephrase in the present singular, or use the existing chunk (`vorrei`, `sono nato/a`); never add `allow:` to dodge a real level problem |
| construction gate | an articulated preposition, clitic or construction taught later | rephrase (`in un bar` instead of `al bar` before Unit 6), or use a chunk the unit spec lists (`c:al-bar`). Articles before their own unit are fine only directly before a noun item, or before an adjective and a noun item (the lexical-article rule, docs/04) |
| new-token budget | too many new tokens in a text | move items to the preview, cut, or replace with known words |
| production gate | a model answer uses an item or grammar point not introduced for production | change the first expansion; keep correct alternatives later in the pattern |
| later form in a text | a form the learner should only recognise here | list it in the line's `recognise: [form]` with a `gloss:`; it counts toward the new-token budget and never appears in answers |
| ambiguous token | the form matches two items | add `lemmas: {form: item-id}` on the line |
| register mismatch | a line's `register` disagrees with the story bible | fix the line, not the bible; ask if the bible looks wrong |
| alignment | an exercise without tags, or a can-do without practice or check items | add tags or items |
| recycling warnings | too few encounters | reuse the item in later practice, stories and checks |

## Never

- Edit a file whose `review.status` is `approved`.
- Copy wording, tasks or examples from CILS, CELI, PLIDA, the joint syllabus, the Profilo, textbooks or any other source. Write everything fresh.
- Invent story facts the bible doesn't contain (ages, jobs, relationships, places). Ask, or list them as proposals.
- Use non-commercial resources (Kelly, spaCy Italian models, UD ISDT…) even for ideas lists.
- Highlight grammar in stories (no bold or colours on first reading); highlighting belongs in notes.
- Use digits in voiced lines, or forms beyond the unit "because they're common".
