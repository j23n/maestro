# Plan: Italian Vocabulary / Spaced Repetition

## Architecture Overview

```
Ingest (one-off script)
  └─ Scrape A1 list → Wiktionary API → vocabulary_words table

Chat (existing flow, extended)
  └─ AI response generated → vocab discovery scan
      ├─ new words → user_vocabulary_cards table
      └─ annotated HTML stored on Message → rendered with popovers

/vocab page (new)
  ├─ list all tracked words + SRS status
  └─ /vocab/practice → flashcard UI (HTMX-driven)
```

---

## 1. Database Schema (new tables + one column)

**`vocabulary_words`** — master word list from the scraped source:

| column | type | notes |
|--------|------|-------|
| `word` | str | e.g. `"mangiare"` |
| `part_of_speech` | str | e.g. `"v. tr."` |
| `cefr_level` | str | `"A1"`, `"A2"`, … |
| `definition` | str | from Wiktionary (Italian or English) |
| `translation` | str | English gloss |

**`user_vocabulary_cards`** — SRS state per discovered word:

| column | type | notes |
|--------|------|-------|
| `word_id` | FK → vocabulary_words | |
| `discovered_at` | datetime | |
| `discovered_in_message_id` | FK → message | for context |
| `ease_factor` | float | SM-2, starts at 2.5 |
| `interval` | int | days until next review |
| `repetitions` | int | count of successful reviews |
| `next_review` | datetime | |

**`Message.annotated_html`** — nullable column; stores the post-processed HTML with popover spans injected (computed once at response time, avoids per-render DB lookups in templates).

---

## 2. Ingest (`src/maestro/vocab/ingest.py`)

A runnable script (not an endpoint):

1. **Scrape** the A1 page with `beautifulsoup4` (already a dep) — extract word + part-of-speech from the list structure
2. **Wiktionary REST API** — `https://en.wiktionary.org/api/rest_v1/page/definition/{word}` — free, no auth, returns JSON with definitions; extract the Italian section → English translation
3. Upsert into `vocabulary_words`. Rate-limit requests to be polite to Wiktionary.

> Note: The schema supports multiple CEFR levels, so ingest can be extended if A2+ pages appear.

---

## 3. Discovery & Annotation (`src/maestro/vocab/discover.py`)

Called in the `get_response` route in `main.py` after saving the AI reply:

1. **Tokenize** the response text (simple word-boundary regex, lowercased + lemma-matched)
2. **Set lookup** against all `vocabulary_words` (cached in memory on startup, invalidated on ingest)
3. For each matched word:
   - If not yet in `user_vocabulary_cards` → insert (with `discovered_in_message_id`)
   - Mark as "new discovery" vs. "already tracked"
4. **Annotate HTML**: run the text through the markdown filter, then find matching words in text nodes and wrap with:
   ```html
   <span class="vocab-word"
         popover-target="vocab-{{ word_id }}">mangiare<sup>*</sup></span>
   <div popover id="vocab-{{ word_id }}">
     <strong>mangiare</strong> — v. tr. [A1]<br>
     to eat<br>
     <small>✓ Now tracking in your vocabulary</small>
   </div>
   ```
5. Store as `Message.annotated_html`

---

## 4. Vocabulary Page (`/vocab/`)

Two views, both HTMX-driven:

**`/vocab/`** — word list
- Cards showing all discovered words with SRS status: due today, learned, new
- Links to practice

**`/vocab/practice`** — flashcard loop

1. Query words where `next_review <= now()`, ordered by due date
2. Show Italian word (front)
3. User clicks "Reveal" → HTMX swap shows definition + rating buttons
4. `POST /vocab/{card_id}/review` with rating (1–5)
5. SM-2 algorithm updates `ease_factor`, `interval`, `next_review`
6. HTMX loads next card

**SM-2 algorithm** (`src/maestro/vocab/srs.py`) — standard implementation:

```
if rating < 3: interval = 1, reps = 0
else:          interval = 1 (reps=0) | 6 (reps=1) | prev*ease (reps>1)
ease = max(1.3, ease + 0.1 - (5-rating) * (0.08 + (5-rating)*0.02))
```

---

## 5. File Changes

```
src/maestro/
  vocab/
    __init__.py
    ingest.py       # scrape + wiktionary
    discover.py     # word detection + HTML annotation
    srs.py          # SM-2 algorithm
  models.py         # + VocabularyWord, UserVocabularyCard, Message.annotated_html
  main.py           # + /vocab routes
  migrations/       # new Alembic migration

templates/
  vocab.html        # word list page
  vocab-practice.html
  vocab-card.html   # HTMX partial (front + back of card)
```

---

## Open Questions

1. **Annotation scope**: Should all previously-tracked vocab words be annotated on every AI response (so you always see the popover), or only on first discovery? First-discovery-only is simpler; always-annotate is more useful for learning.

2. **Wiktionary fallback**: Some Italian words won't have a clean Wiktionary entry (dialectal forms, proper nouns). Should we store them with a null definition and allow manual edits later, or skip them during ingest?

3. **Practice rating scale**: SM-2 uses 0–5. A simpler UX is three buttons: **Again** / **Hard** / **Easy** (maps to 1 / 3 / 5). Prefer that, or the full 5-point scale?
