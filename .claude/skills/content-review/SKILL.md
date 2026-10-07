---
name: content-review
description: Bring the content lead's review back into the course. Use when the owner hands you a review file (review-*.json from a review page or the app), asks you to apply the teacher's comments, or asks for the next review page for a unit.
---

# Applying the content lead's review

The content lead (an Italian teacher) reviews on the review pages and in the app's review mode; both produce a review file (`docs/04` § Content review loop). You turn each comment into a fix, an answer or a question for the owner, and you leave a record of what you did. The teacher's words are evidence: you never edit them.

## Never

- Edit anything in `reviews/inbox/` (a hook blocks it). Those files are the teacher's own record.
- Touch `review:` blocks, or run `content approve` / `content reopen`. Approval is the owner's step, after the teacher's sign-off.
- Edit approved files. A comment on an approved file gets `status: owner` with the note "needs content reopen".
- Change a model answer to make a comment go away. Answer-key comments add accepted alternatives or near-misses.
- Delete or merge comments in the ledger. Every comment keeps its own resolution.

## Procedure

1. **Import.** `uv run content review-import <file>` copies the file into `reviews/inbox/`, appends its comments to `reviews/<scope>.yaml` and prints the worklist. If it reports unknown targets, tell the owner; don't guess the target.
2. **Triage** each `open` comment:
   - **stale** (made on an older version): compare the quote with the current text. If the problem is already gone, resolve it as `answered` and say which change fixed it.
   - **question** verdicts: answer in `resolution.note` in plain English the teacher can read; change content only if the answer shows a real problem.
   - **decisions that aren't yours** (story facts, register choices, scope, anything in `docs/13`): `status: owner`, with the options.
3. **Fix**, following the `italian-content` skill (load it) for every content change:
   - **Italian error / unnatural:** use the teacher's suggestion when it passes the gates; otherwise write the closest version that does, and explain.
   - **Level:** rephrase with known items, or move the item to the preview; never add `allow:` to dodge a level problem.
   - **Answer key** (incl. "This should be accepted" with a `response`): add the answer as an accepted alternative, or as a `near` with a hint if it's almost right. Keep the first expansion (the model answer) unless the teacher says the model itself is wrong.
   - **Hint or rule:** hints point at the problem without giving the answer away; rules must not overgeneralise.
   - **English:** American English; one rendering per item across the unit.
   - **Culture or facts:** fix the text and add the fact to `story-bible.yaml` → `facts_to_check` if it's new.
   - **Audio:** an IPA override in `pronunciation.yaml` or the line's `say:`; re-render with `content tts` (ask the owner, it costs money).
4. **Record** each comment's resolution in the ledger: `resolution: {status: fixed | answered | declined | owner, note: "<what you did or why not>", commit: <sha after you commit>}`. Declines always give the reason (usually the level gate) and an alternative.
5. **Check:** `make annotate`, `make check-content`, then the content-critic on the files you changed. Fix what they find.
6. **Return:** `uv run content review-export --unit <uNN> --since` writes the next page with the resolutions and the changed elements marked. Tell the owner where it is, and give a summary: how many comments were fixed, answered, declined, and which need the owner.
7. **Sign-off:** when a review file with a `signoff` block comes back and the ledger has no open comments for its files, tell the owner the exact command: `uv run content approve <file> --by "<teacher>" --signoff reviews/inbox/<file>.json`. Don't run it.

## Writing for the teacher

Resolution notes are read by an Italian teacher, not an engineer. Write short, plain sentences, quote the Italian you changed, and don't use internal jargon ("level gate" becomes "this word comes in Unit 4, so I used … instead").
