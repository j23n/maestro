# Exercise cookbook

Formats and fields are in `docs/06`. Here: what good looks like.

| Format | Use it for | Good | Avoid |
|---|---|---|---|
| `cloze` | a form or word in a known sentence | blank the target form in a story sentence (`source:`), one gap, an English `prompt_en`, `near` for the 1–2 most likely errors, `rule` in one line | blanking a word the sentence doesn't force (several right answers); blanks in names |
| `recall` | producing a word or chunk from English | short prompts ("a croissant", "How much is it?"); the answer with its article for nouns; `audio_after: true` | long sentences early on; prompts with several valid Italian answers you don't list |
| `sentence-building` | word order, agreement | 4–7 tiles, at most one distractor, all valid orders accepted | punctuation tiles; tiles that only differ by capitals |
| `dictation` | listening and spelling | ≤ 8 known words; include a double consonant or an accent to notice | new words; numbers in digits |
| `sound-pair` | hearing contrasts | real minimal pairs with glosses (*eco/ecco*); `single-or-double` with story words | non-words, unless the content lead approves |
| `repeat` | rhythm, fluency | ≤ 10 words from the story, natural chunks | tongue-twisters; isolated function words |
| `choice` | recognition, comprehension | 3 options, one clearly right, plausible distractors of the same form | "all of the above"; options that differ in length or style |
| `match` | consolidating 4–6 pairs | one batch of related items | more than 6 pairs |
| `true-false` | reading real-world texts (CELI-style) | statements about facts in the text | statements answerable without reading |
| `conversation` | interaction, unit tasks, `use` steps | 3–5 nodes; 1–2 intents per node; `help` = model lines; `hint_en` says the goal; register `near` entries; `register` is the character's, plus `learner_register` when the learner's differs (Signora Rossi: `tu`, the learner: `lei`) | long Italian turns from the character; intents that need untaught words |
| `talk` | monologue | 2–4 content points shown as a checklist, `pass` below the number of points, a model answer | points that need exact wording |
| `writing` | forms, messages, postcards, descriptions | word ranges like the exams (15–30, 20–40, 25–50); points; a model | grading style or creativity |
| `relay` | mediation | a friend's question in English about a time, price, place or number in an Italian text | questions answerable without the Italian |
| comprehension (`choice`, role comprehension) | after each story | 2–4 questions on meaning (who, what, how much) | questions on grammar |

## Numbers per lesson (guide)

- Preview: 6–12 items.
- Practice block: 8–14.
- Mix: 4–8.
- Sounds: 2–3.
- Use: 1 short conversation.

New P items each get at least 4 retrievals in the lesson (≈ 5 is the aim; docs/04 § Check 3 counts them).
