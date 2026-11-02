# Level plans

One file per CEFR level says what that level's texts must contain together: the core vocabulary as a frequency band, how many new words a text may bring, how long texts are, and which persons, block types and registers the level must include. The grammar sequence is not repeated here: each topic in `content/grammar/` carries its `level` and `order`.

The pipeline reads these files for `make check-texts`, `make coverage` and `make brief` (`tools/maestro_content/curriculum.py`). Every number is a first guess, to be tuned on the first generated texts.

| Key | Meaning |
| --- | --- |
| `knownRank` | Lemmas up to this frequency rank count as known to a reader at this level (the core of the levels below). |
| `coreRank` | The level's core vocabulary: lemmas up to this rank. Briefs pick new words from between `knownRank` and `coreRank`. |
| `knownShare` | Share of a text's running words its reader must know, not counting the words the text sets out to teach. |
| `newWords` | New lemmas one text may introduce. |
| `words` | Text length in words. |
| `sentenceWords` | Highest mean words per sentence. |
| `persons` | Verb persons the level's texts must use, together. |
| `blocks` | Block types the level must have. |
| `registers` | Registers the level must have (`tu`, `Lei`), from each text's `register:` line. |
| `topicShare` | Largest share of the level's texts one topic may take. |
| `tenseShare` | Largest share of a collection's finite verbs any tense other than the present may take. |
| `recurrence`, `recurrenceWindow` | A new word should reappear in `recurrence` of the next `recurrenceWindow` texts at its level or the next. |

Ranks come from `content/frequency/`, mapped to lemmas by the content build (`lemma.freq_rank`).
