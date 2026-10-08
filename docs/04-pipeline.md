# 04 · Content pipeline and quality checks

The pipeline turns `content/*.yaml` into the content pack and enforces the course's grounding: nothing untaught, enough recycling, full syllabus coverage. It is a Python 3.12 package `itcontent` in `pipeline/`, managed with `uv`, exposing one CLI: `content` (run it as `uv run content …`; the Makefile wraps the common calls).

YAML is loaded with **ruamel.yaml in safe mode (YAML 1.2)**, so Italian `no`, `sì`, `on` and `off` stay strings. Never use PyYAML's default loader on content.

## Commands

| Command | Does | Fails when |
|---|---|---|
| `content lint [--json]` | YAML parse, JSON Schema validation (`schemas/*.schema.json`, chosen by path), ID format and placement (`docs/03` § IDs), references resolve, no duplicates, homograph `~sense` suffixes, `ids.lock` stability and `retired.yaml`, exercise rules a schema can't express (a match's targets per pair, a choice's answer index, conversation graphs, sentence-building tiles), **approval hashes**, review ledgers (`reviews/*.yaml`: every comment has a known target and a valid resolution). References to units, lessons, steps, items, sounds or task conversations that don't exist yet are reported as *pending* (information) when they come from unit specs, the syllabus, the story bible (`switch_at`), `disambiguation.yaml`, `pronunciation.yaml` or an item's `lesson`; a lesson, task or check file referring to something missing is an error, and so is a unit spec naming a task conversation its written `task.yaml` lacks. A ledger comment with an unknown target is an error while it is `open` or `owner`, a warning once resolved (the fix may have removed the target). Output: one line per finding, `error\|warning\|pending: <file> › <path> (line N): <message>`, sorted, then a summary; pending references to the same target from one file are one line. `--json` prints `{summary, findings: [{level, file, path, keys, line, message}]}` | any error |
| `content annotate [--check]` | tokenise every Italian string; Morph-it! lookup; chunk matching; item resolution; grammar detection; write `content/.annotations/**.json`. `--check` regenerates and diffs | unknown or ambiguous tokens; with `--check`, stale locks |
| `content check [--unit uNN] [--json]` | automatic checks 1–5 (below); writes `build/reports/check.{json,md}` | any check error (warnings never fail) |
| `content tts [--unit uNN] [--dry-run]` | render missing audio with Azure, align word timings, assemble texts, encode, fill the cache | Azure errors, alignment failures |
| `content build [--release] [--allow-partial] [--mini]` | compile `App/Italiano/Resources/Content/content.sqlite` and copy referenced audio. Dev builds include drafts and warn on missing audio; `--release` includes only approved files; `--mini` builds `fixtures/packs/mini.sqlite` and `mini-payloads.json` | schema violations, over budget; with `--release`, missing audio |
| `content pack-hash [--pack <path>]` | print the canonical pack hash (§ Pack build) for CI freshness checks | — |
| `content review-export (--specs \| --unit uNN) [--since]` | the teacher's review page: one self-contained HTML file (`build/review/<scope>/index.html`) with comment boxes and sign-off (§ Content review loop); `--since` shows the resolutions of earlier comments and marks what changed | — |
| `content review-import <review.json>` | file a review (page or app) into `reviews/inbox/`, add its comments to the ledger `reviews/<scope>.yaml`, flag stale comments, print the worklist | unknown targets; malformed file |
| `content approve <file> --by "<name>" [--signoff <review.json>]` / `content reopen <file>` | set review status and hash (`approve`: `approved`, `by`, today's date, `hash`; `reopen`: `in-review`, the rest `null`), rewriting only the `review:` entry. With `--signoff`, refuses while the ledger has open comments on the file or when the file's hash differs from the hash the teacher signed. **Humans only:** the command refuses when stdin is not a TTY or the `CLAUDECODE` environment variable is set (Claude Code sets it in every shell it runs), and asks the person to type the file name (`lesson-1.yaml`, or its repo path) to confirm. A hook also blocks agents from running it | file fails lint or check; file already approved (reopen it first); open comments; hash mismatch; no TTY; run by an agent |
| `content report [--unit uNN]` | dashboard: new words, encounters, strand split, coverage, budgets, open review comments | — |
| `content freq <word…>` / `content suggest --topic <t> --unit <u>` | frequency ranks; high-frequency candidates not yet in items (helper for the item graph) | — |
| `content beta-import <events.jsonl>` | item statistics and rejected typed answers from study telemetry (`build/reports/beta/`) | — |

Makefile wrappers (`docs/10`): `make annotate` = `uv run content annotate`; `make check-content` = lint, `annotate --check`, check; `make pack` = those, then `build`; `make mini-pack` = `build --mini`; `make pack-release` = `build --release --allow-partial` into `build/release/` (never committed); `make data` downloads the reference data.

## Reference data (`make data`)

| File | Source | Licence | Pinned by |
|---|---|---|---|
| `pipeline/data/morph-it/morph-it.txt` | Morph-it! download on the Morph-it! page (docs.sslmit.unibo.it) | CC BY-SA 2.0 / LGPL | SHA-256 in `pipeline/data/SOURCES.md` |
| `pipeline/data/frequency/it_50k.txt` | hermitdave/FrequencyWords, `content/2018/it/it_50k.txt` | CC BY-SA 4.0 | SHA-256 |

The data files are downloaded on demand and cached in CI, never committed; each folder keeps its licence text. `.worktreeinclude` lists `pipeline/data/**`, so new worktrees get a copy. Morph-it! lines are `form<TAB>lemma<TAB>features`; for example `gattini	gattino	NOUN-M:p` or `fatto	fare	VER:part+past+s+m`.

- **Categories** include ADJ, ADV, ART, ARTPRE (articulated preposition), AUX, MOD, CAU, ASP (verbal categories), CE, CI, CON, DET-DEMO, DET-INDEF, DET-NUM-CARD, DET-POSS, DET-WH, INT, NOUN, PON, PRE, PRO-DEMO, PRO-INDEF, PRO-PERS, PRO-POSS, PRO-WH, SI, VER, WH and WH-CHE.
- **Verb features** are mood+tense+person+number (`ind+pres+3+s`, `cond+pres+1+s`, `impr+pres+2+s`, `inf`, `ger…`); clitics attached to verbs appear as extra features.
- **Encoding:** detect it (the file has historically been Latin-1) and convert to UTF-8 NFC on load. A unit test asserts that `caffè` and `perché` are found.
- Inspect the real tag strings before writing detection rules, and record any surprises in `pipeline/data/SOURCES.md`.

## Annotation

Every Italian string is annotated: text lines, exercise strings, accepted patterns (each expansion), conversation lines and titles. Which fields hold Italian is listed per format in `docs/06` (§ Which strings are Italian); the module docstring of `itcontent/annotate.py` keeps the same list. Near-miss `answer` patterns are annotated like an accepted pattern's other expansions (never as a model answer, never gated): they are often deliberately wrong Italian.

1. **Tokenise:**
   - Split on whitespace and punctuation.
   - Keep elided forms attached to the left token (`l'amica` → `l'` + `amica`; `c'è` → `c'` + `è`; `quant'è` → `quant'` + `è`; also `po'`). An apostrophe that opens a quotation, and the one that closes it, is punctuation.
   - Digits (with `.` `,` `:` between digits: `6,20`, `10:15`) become `number` tokens; text in a line's `foreign` list (one or more words, any case) becomes `foreign` tokens.
   - Allowlisted names become `name` tokens. Names match **case-sensitively** (`Rosa` is a name, `rosa` is pink). At the start of a sentence, a name that is also an item form resolves to the name unless the line's `lemmas:` says otherwise (`lemmas: {Rosa: w:rosa}`).
   - Every other character is a punctuation token. Each token keeps the text up to the next token (`trailing`), so a line re-renders exactly; the `*` markup of note fragments and table cells goes into `trailing`, never into a token.
2. **Chunks first:** match each chunk item's `match` sequences against consecutive word tokens (punctuation, names, numbers and foreign words break a match; scanning left to right, the longest match wins). Matching ignores case unless the chunk has `case_sensitive: true` (`e Lei`, `Le piace`, `Le presento`); a case-sensitive chunk still matches when its first word is capitalised at the start of a sentence (*No, sono canadese. E Lei?*). In a pattern, a personal slot is one `slot` token and may supply a chunk's last word: `abito {ME.home}` matches `c:abito` because the countries' home phrases start with *in, a, negli, nel, nei, nelle*. Tokens inside a chunk get the chunk ID, get no grammar detections, and are exempt from the morphology, construction and production-grammar checks.
3. **Lookup:** for each remaining token, find Morph-it! analyses for the surface form; a capitalised form (sentence start, formal *Lei*) also takes the lowercased form's analyses and then drops Morph-it!'s proper-noun (NPR) readings, which would otherwise win for words such as *Al* (NPR, as in Al Capone) or *Come*; allowlisted names never get here. Elided forms in a small table take the analyses of their full forms instead, because Morph-it! lists `c'` as ADV with lemma `c'`, gives `anch'` the lemma `anch'` and lacks `quant'` (`l'`→lo/la, `un'`→una (articles only), `dell'`→dello/della, `c'`→ci, `dov'`→dove, `com'`→come, `cos'`→cosa, `quant'`→quanto, `anch'`→anche, `d'`→di, `m' t' s' v'`→mi ti si vi); other elided and truncated forms (`all'`, `nell'`, `quell'`, `po'`) use Morph-it!'s own entries.
4. **Resolve items:**
   - **Item surface forms first:** a surface equal to an item's `it`, its `plural` (unless `invariable`) or one of its `forms` resolves to that item without a lemma lookup (`amica` → `w:amico`), case-insensitively. The token keeps only the Morph-it! analyses compatible with the item's POS (noun: NOUN; verb: VER, AUX, MOD, CAU, ASP; adj: ADJ; adv: ADV, WH; prep: PRE; conj: CON, WH, WH-CHE; pron: PRO, SI, CI, NE, CE, WH, WH-CHE; det: DET; num: DET-NUM-CARD, PRO-NUM; interj: INT). When none is compatible, an analysis is synthesised from the item and flagged `synthetic` (`spremuta` is only a participle of *spremere* in Morph-it!, so it gets `NOUN-F:s`).
   - Otherwise map each analysis lemma to items whose `it` equals the lemma with a compatible POS (`italiana` → lemma *italiano* → `w:italiano`).
   - **Articles** map to the grammar points `g:indefinite-article` / `g:definite-article`, and **articulated prepositions** (ARTPRE: *al, della, negli*) to `g:articulated-prepositions` / `g:articulated-prepositions-lo-gli`, not to word items; such a token's item is the point.
   - **The lexical-article rule:** an article directly before a noun item, or before an adjective and a noun item, is part of that noun until the article's own unit (*un/una*: Unit 2; *il/la/lo…*: Unit 3, the `unit` of the point in `points.yaml`, compared in `course.yaml` order): it is annotated with the noun's item and flag `lexical_article`, with no grammar detection and no requirement of its own. An allowlisted transparent noun counts as a noun item here (*il bar*, *un euro*), and the adjective may be any word Morph-it! knows only as an adjective (*un buon caffè*). From the article's unit on, normal rules apply. This is what lets Unit 0–1 texts say *la signora Rossi* and Unit 2 say *il bar*.
   - **Choosing:** the line's `lemmas` override comes first. Then `disambiguation.yaml`: a form with a context rule (`sei`, `uno`, `la le lo gli l'`) always goes through it, even with one candidate, because the rule may rule out a reading (clitic *la* before a verb is the pronoun, so it needs an item of its own). Its conditions are machine-readable (`when_any` with `prev`/`next` matchers on the nearest non-punctuation neighbour, matched on its Morph-it! analyses plus those synthesised from its items). Then its `defaults`. Exactly one candidate left: take it. Several: an error naming the line and the candidates.
   - None: allowlisted words pass; glossed and `recognise` tokens pass (new in this step); sound-pair words pass when their exercise's `glosses` explain them; tokens of a unit title whose unit has no items file yet are *pending* (information). In an accepted pattern's other expansions (not the model answer) the token keeps its Morph-it! lemma with no item, which is fine (a warning only when it has no Morph-it! analysis either: a likely typo); an ambiguous token there is a warning. Otherwise it's an error ("untaught lemma *x*: add an item, gloss it as new in this step, or rephrase").
5. **Detect grammar:** run the rules in `content/grammar/detection.yaml` over the chosen analyses and record (point, token span). A matcher matches a token only if **every** analysis left after disambiguation matches, so an invariable noun (`caffè`, singular and plural) never counts as a plural; a matcher with `any: true` needs only one, for verb forms Morph-it! also files under another mood or as an adjective (*parliamo* is indicative, imperative and subjunctive; *finito* is a participle and an adjective). Chunk tokens, lexical articles, names, numbers, foreign tokens and punctuation get no detections and break a sequence. `detection.yaml` is engineering-owned and outside the content lead's approval, so rules can be fixed without reopening `points.yaml`; every rule needs a passing and a failing test.
6. **Write the lock file** with tokens, spans, analyses, item IDs, chunk IDs, detections and flags (format in `docs/03` § Annotation lock files). Never edit lock files by hand; run `make annotate`. Nothing is written while there are errors; `--check` also fails on lock files that are missing, stale or left over, naming each.

**Line fields that change annotation:** `foreign: [form]` (excluded from the gates, shown in italics), `gloss: {form: en}` (context glosses; keys may be several words, matched case-insensitively; a glossed token whose item is not introduced before this step, or that has no item, is *new in this step*), `lemmas: {form: item-id}`, and `recognise: [form]` for a later form the learner should only recognise here. A `recognise` token must also have a `gloss`; it gets flag 2, is exempt from the lemma, morphology and construction gates, counts toward the new-token budget and may never appear in an answer. A `gloss`, `lemmas` or `recognise` key that doesn't occur in the line is an error.

## The ten quality checks

Checks 1–5 are automatic and run in `content check` on every build. Checks 6–10 are human or learner checks that the pipeline supports with tools. Thresholds live in `content/checker.yaml`.

**Partial content.** While the course is being written, most units are incomplete. A unit is **complete** when every `lesson-K.yaml` (K = 1…`lessons` in its spec), `task.yaml` and `check.yaml` exist. Checks 3 and 4 report incomplete units as `pending` (information, never an error), and item-level errors apply only to items whose introducing lesson file exists. An item whose `lesson` doesn't exist yet, or a grammar point whose note doesn't exist yet, counts as introduced at the start of its unit (a grammar point's `unit` in `points.yaml`), with a warning. For `u99`, final-check exercises count as unit-check exercises. With only the golden lesson written, `make check-content` must pass.

### Check 1 · Syllabus coverage (error below 100%)

For every entry in `syllabus/a1-syllabus.yaml`, find where it is **introduced**, **practised** and **assessed** (only the roles in its `roles` list, when given):

| Ref | Introduced | Practised | Assessed |
|---|---|---|---|
| `g:` / `s:` | the step that introduces it (`docs/05` § Introductions) | ≥ 1 learn exercise with it as a primary target | ≥ 1 check or final exercise with it as a primary target |
| `cd:` | its unit | ≥ 1 learn exercise tagged with it | ≥ 1 unit-check exercise tagged with it |
| `topic:` | an item with that topic introduced | an exercise whose primary target has the topic | a check exercise whose primary target has the topic |
| `kind:` / `format:` / `section:` | a step of that kind or an exercise of that format exists | same | a check exercise of that format, or that section |
| direct `sy:` tag | first tagged step | tagged learn exercise | tagged check exercise |

An entry is satisfied in each role if any of its refs, a direct `sy:` tag, or a can-do listing the entry in its own `syllabus` is. The report lists every entry with its three locations. `syllabus_trace` in the pack stores the result. With `coverage_mode: report` (until G3) a gap is a warning showing the percentage; with `enforce` it is an error.

### Check 2 · Level gate (errors)

For every text and exercise at its course position *p* (unit order, then step order). **Titles** (unit, lesson, story and conversation titles) are annotated for glosses but exempt from every gate; unit titles naturally preview their unit.

- **Lemma gate:** every word token's item is introduced at or before *p*, introduced by this very step (new), allowlisted, or listed in the line's `recognise`.
- **Morphology gate:** every verb token has an analysis whose features are unlocked (`unlock` in `detection.yaml`) by a grammar point introduced at or before *p*, or by the current lesson's target point (its story comes before its note): status P or R for texts, P only for answers. Ambiguous forms pass if any analysis is unlocked; that gap is left to the critic and the content lead. Tokens inside chunks and `recognise` tokens are exempt, as are lines carrying `allow: {reason: …}`; every such line is listed in the report.
- **Construction gate:** every grammar detection belongs to a point introduced at or before *p*, or is the current lesson's target point appearing in its story before the note.
- **New-token budget:** (tokens new in this step + `recognise` tokens) / word tokens is at most `story_new_token_max` (0.05) for stories and listening and `real_world_new_token_max` (0.10) for real-world texts.
- **Production gate:** the **model answer** (the first expansion of an exercise's `answer`, of a cloze gap, and of the first pattern in each conversation intent's `accept`; every `help` phrase; talk and writing `model`s) uses only items introduced for `recall` at or before *p* (the same lesson's preview counts) and only grammar points with status P. Chunk tokens are exempt from the grammar part (`vorrei` is fine in a model answer although `g:conditional-courtesy` is a chunk point). Other expansions and later patterns are not gated: they exist to accept correct answers and may use later words; the linter only warns about tokens that have neither a Morph-it! analysis nor an item (likely typos).

### Check 3 · Recycling and balance (warnings unless stated)

- **Encounters:** occurrences of each item in texts and exercise strings from its introduction to course end. P items need ≥ 10 (error below 6); R items need ≥ 6.
- **Retrievals in the introducing lesson:** the preview counts 2 (match, then recall or choice). Add each exercise in the lesson that has the item as a primary target, contains it in the model answer of a production format (recall, sentence building, dictation, a cloze gap, a conversation turn's first accepted expansion), or pairs it in a `match`. Repeat-after-me and text the learner only reads don't count. P items need ≥ 4 (error below 2).
- **Recycling:** ≥ 30% of content-word tokens in each unit's texts come from earlier units.
- **Grammar spiral:** every grammar point is detected or targeted in ≥ 2 later units (Units 11–12: in the final review).
- **Strand balance:** estimated minutes per strand per unit from the durations in `checker.yaml` must be 15–35% each.
- **Story length:** within the unit spec's `words` range.

### Check 4 · Alignment (errors)

- Every exercise has ≥ 1 `cd:` or `sy:` tag.
- Every can-do has ≥ 1 learn exercise and ≥ 1 unit-check exercise.
- Every unit check covers listening, reading, writing and speaking.
- Every note has ≥ 2 examples from its lesson's story.
- Every `match` exercise has as many `targets` as `pairs` (`targets[i]` belongs to `pairs[i]`).
- Every P grammar point of a complete unit is introduced by a note (`docs/05` § Introductions).

### Check 5 · Story consistency (deterministic part)

- Every speaker exists in `story-bible.yaml`; `narrator` and `announcer` are reserved speakers that need no entry.
- Every line with `to:` has a `register` allowed by the register matrix at its step: exact pairs win over `(speaker, '*')`, which wins over `('*', addressee)`; at a row's `switch_at` step both registers are allowed, before it `register`, after it `then`. Conversation nodes may override `register` (the node where someone offers tu). A mismatch is an error.
- Heuristic warnings: second-person-singular forms (`ind+pres+2+s`, `ti`, `tuo`) in a `lei` line; `Lei/La/Le/Suo` in a `tu` line.
- The rest (ages, relationships, places, timeline, prices that must match a menu) is checked by the **content-critic** subagent (`.claude/agents/content-critic.md`) on every draft. Its report goes to `build/reports/critic/`. Trust it only after its verdicts agree with the content lead on 20–30 drafts.

### Checks 6–10 · People and learners

| # | Check | Tooling |
|---|---|---|
| 6 | Italian correctness (content lead reads every text and exercise against the style guide) | review pages and review mode → `content review-import` → fixes → sign-off → `content approve --signoff` (§ Content review loop) |
| 7 | Answer keys (accepted alternatives; beta-rejected answers adjudicated weekly) | "This should be accepted" in review mode; `content beta-import` → "Answers to adjudicate" in the next review page (M8.3) |
| 8 | Grammar explanations (content lead reviews every note) | the review page lists notes separately |
| 9 | Audio (native listener checks all audio; IPA fixes) | the review page embeds audio players and takes `audio` comments; `pronunciation.yaml` and line `say:` overrides |
| 10 | Learner item data (error rate, time, glosses tapped) | `content beta-import` → `build/reports/beta/items.md` (outliers first) |

## Audio (`content tts`)

1. **Collect audio needs:** every text line, every item's display form, every exercise string that is voiced (dictation, repeat, sound-pair words, recall answers with `audio_after`, conversation lines, model answers) and note examples. Lines spoken by `ch:you` with `{m:…|f:…}` forms are rendered twice, once per learner voice (`voices.yaml`).
2. **Build SSML per need:**

   ```xml
   <speak version="1.0" xml:lang="it-IT"><voice name="it-IT-…Neural"><prosody rate="…">…</prosody></voice></speak>
   ```

   The voice comes from `voices.yaml` (by speaker; `narrator`; `announcer`; `items`; `ch:extra` picks by FNV-1a 64 of the text ID). Add `<phoneme alphabet="ipa" ph="…">` for words in `pronunciation.yaml` or the line's `say:` overrides.
3. **Cache key:** sha256 of voice, style, rate, pitch, SSML and output format. The cache (`content-build/tts-cache/`, Git LFS) keeps the audio as **FLAC** (lossless and sample-exact, about half the size of WAV) with its word boundaries; skip needs already cached.
4. **Batch synthesis** for the rest:
   - Send `PUT {endpoint}/texttospeech/batchsyntheses/{id}?api-version=2024-04-01` with `inputKind: SSML`, at most 1,000 inputs per job, and properties `outputFormat: riff-24khz-16bit-mono-pcm`, `wordBoundaryEnabled: true`, `sentenceBoundaryEnabled: true`.
   - Poll until done, download the result ZIP and keep each `NNNN.wav` with its `NNNN.word.json` entries (`Text`, `AudioOffset` ms, `Duration` ms).
5. **Align** the word boundaries to our tokens: match normalised `Text` to tokens in order, skipping punctuation entries. Any mismatch is an error that names the line. This is why voiced numbers are written in words.
6. **Assemble each text in PCM** from the cached WAVs: lines joined with 300 ms of silence for the same speaker, 600 ms on a speaker change, plus any `pause_ms`. Compute `text_lines.start_ms/end_ms` and `tokens.start_ms/end_ms` from sample counts. Announcements get a light station effect (band-pass plus reverb) here.
7. **Encode once** per text and per standalone need to AAC-LC `.m4a`, 24 kHz mono, 48 kbps, with ffmpeg. Never concatenate encoded AAC: every join adds encoder priming and padding and the read-along drifts. The file name is the audio ID's 12 hex digits (`audio.file = 3f9c0e1a2b4d.m4a`); the app always reads `audio.file`. A test in M5.2 checks that AVPlayer honours the encoder delay (the highlighted word is within 50 ms).

Secrets come from the environment (`AZURE_SPEECH_KEY`, `AZURE_SPEECH_ENDPOINT`) and are never committed. `--dry-run` prints the character count and cost at $15 per 1M characters. HD voices can't be used: they're real-time only, and Omni variants reject `<phoneme>`.

## Pack build (`content build`)

- Create the database from `schemas/content-pack.sql`. Insert rows sorted by primary key, then `VACUUM INTO` the destination with `journal_mode=DELETE` (the app opens it read-only).
- `meta`: `schema_version`, `pack_version` (from `course.yaml`), `content_hash`, `git_sha`, `built_with` (pipeline version), `course_id`, `locale`, `release` (0 or 1), and in dev packs `review_files` (JSON `{"<id prefix>": {"file": "content/…yaml", "hash": "<approval hash>"}}`, which the app's review mode uses to fill in a comment's file and hash). The app refuses a pack without `schema_version`, `pack_version`, `content_hash`, `course_id`, `locale` or `release`; the other keys are optional.
- Row shapes the app relies on beyond the DDL: `sounds.pairs` is `[[{"it": "pena", "audioId": "a:…" | null}, …]]`; `exercise_targets` has no order column, so a `match` exercise's target order is its payload's `targets` (`targets[i]` belongs to `pairs[i]`), which must name exactly the pairs in `exercise_targets` (the reader checks).
- Positions: `units.ord` is the unit's index in `course.yaml` (u00 = 0); every other `ord` counts from 1 (`steps.ord` within the unit, `lessons.ord` = K, `can_dos.ord`, `note_items.ord`, `text_lines.ord` = the line's `#n`, `tokens.ord` within its line). Token indices inside payloads (a note example's `highlight`) are 0-based positions in the payload's token array.
- **Pack hash:** sha256 of a canonical SQL dump of every table (rows sorted by primary key), **excluding** the `meta` keys `content_hash`, `git_sha` and `built_with`. `content_hash` stores this value. The dump is, per table in name order, a line `table(col,…)` and then each row as a JSON array. CI rebuilds the pack and compares hashes, so the committed pack can be checked for freshness.
- **Packs are build outputs, never committed.** `make pack` builds the dev pack (`meta.release = 0`, drafts included) into the bundle folder, which is gitignored; release packs are built only for archiving or TestFlight (`make pack-release`, into `build/release/`). `make archive` (owner) puts the release pack into the bundle for the archive only and restores the dev pack afterwards. Determinism is tested instead of freshness: two builds from the same input have the same `pack-hash` (pipeline tests and CI).
- Every build first runs `content lint` (any error stops it) and reads the annotation lock files: tokens come only from them, and a string whose YAML text no longer matches its lock entry stops the build ("stale: run `make annotate`"). Every payload is validated against `schemas/pack-payloads.schema.json` and every foreign key is checked before the file is written.
- Compile:
  - step and exercise payloads (pattern expansions, token arrays, audio IDs; `docs/06`);
  - unit-level steps (opener, task steps, check, fluency) in the order `docs/06` § Unit-level steps gives: the opener for every unit with a spec; conversation, talk, writing and relay steps only from a written `task.yaml`; the check only from a written `check.yaml`; fluency only when the unit has story texts;
  - `step_introduces`, `exercise_requires` and `text_requires` from the annotations (§ Requirements);
  - `item_skills` (words and chunks: the four skills, or those of a per-skill `status`; sounds: their listed skills; grammar points: `read`, plus `recall` when P) and `item_skills.scheduled` (`docs/05`);
  - `items` for grammar points from `points.yaml` (`it` and `gloss_en` = the title, `note_en` = `about`, `lesson_id` = the lesson of their first note) and `item_requires` from their `requires`;
  - `note_items` (a note may introduce several grammar points);
  - `assessments` (placement blocks and final-check sections);
  - `syllabus_trace` (filled by check 1's tracer, M1.11; empty until then);
  - generated preview exercises (`docs/06` § 1);
  - `forms`: every word token of the included files (near-misses aside), normalised, with its item (a chunk's words with the chunk, a lexical article with its article point) and Morph-it! features, plus each word item's `it`, `plural` and `forms`;
  - `steps.strand` from `checker.yaml` `strands.by_kind` (opener `input`, practice and sounds `language-focus`, check `assessment` unless it says otherwise) and `est_seconds` from its `durations_seconds` (opener 30 s; a story's words × `story_per_word` plus its questions; a conversation `conversation_turn` × the learner turns on its longest path; fluency the unit's story words × `story_per_word` / `fluency_rate`); `lessons.est_minutes` rounds its steps up; `units.est_minutes` is the spec's `est_hours` × 60.
- **Audio:** copy only referenced audio into `App/Italiano/Resources/Content/Audio/` (`Audio/` next to the pack; files nothing references are removed). Fail if the total exceeds 150 MB, and print a projection per unit. Dev builds warn on missing audio (one summary line counting the texts, items, exercise strings and note examples without audio) and leave `audio_id` NULL (the app shows the text without a play button); `--release` fails.
- **Outputs:** dev builds write `App/Italiano/Resources/Content/content.sqlite`, `--release` writes `build/release/content.sqlite`, `--mini` the fixtures below; `--out PATH` overrides. The file is written through `VACUUM INTO` a temporary file and a rename, so a failed build never leaves half a pack.
- **Release mode** includes only units whose every file (unit spec, lessons, task, check, items file) is approved and that are complete (every lesson, the task and the check exist), and fails if a unit referenced in `course.yaml` falls short; the course-wide files the content lead signs off (syllabus, grammar points, story bible, countries) must be approved too. Pass `--allow-partial` to ship the longest prefix of such units, as the beta does; unapproved placement and final-check files are then left out with a warning (the final check also needs `u99` shipped). Release packs have no `review_files`.
- **`ids.lock`** records only IDs compiled by `--release` builds: units, can-dos, items and grammar points, lessons, steps, texts, notes, exercises (including generated preview exercises), characters, and task, check and assessment IDs, each as `<id> <pack version>` the first time it ships. Draft IDs may change until their file is first approved; after that an ID can only be retired (`retired.yaml`).
- **Tiny test packs:** `make mini-pack` builds `fixtures/packs/mini.sqlite` (Unit 2 Lesson 1 and its task and check) from the golden sample for app tests and previews, plus `fixtures/packs/mini-payloads.json` (`{"exercises": {id: payload}, "steps": {id: payload}, "notes": {id: body}}`, for LearningCore's decode tests on Linux). Its catalog (units, items, grammar points, can-dos) is Units 0–2, its steps are Unit 2's and it has no assessments; it leaves out `meta.git_sha`, so the committed files change only when their content does (a pipeline test fails when they are stale: run `make mini-pack`). It has no audio until M5.1 renders the golden lesson's audio; then it includes 2–3 files.

### Requirements (what eligibility checks)

The build derives what each text and exercise requires, per skill, from the annotations:

- `text_requires`: `read` for every word, chunk and grammar point in the text (its lines, or every annotated layout string; titles are exempt); `listen` as well for audio-first texts (listening steps and exercises' `audio_text`). Stories are read with audio, so they require `read` only.
- `exercise_requires`: `read` for items in prompts (`prompt_it`, `context_it`), options, match left sides, sentence-building tiles, writing labels, repeat and conversation `say` (shown with the audio) and sources (the source line, or the whole source text); `listen` for items heard without text (dictation `say`, `audio_text`, sound-pair words); `recall` for items in the model answer of production formats (the first expansion of a recall answer, a cloze gap, the first sentence-building order, the first accepted expansion of each conversation intent, conversation `help` phrases, talk and writing models). The rest of a cloze sentence is `read`. Other expansions, near-misses and content-point patterns require nothing. An exercise also requires its primary targets.
- A token requires its item; a token inside a chunk requires only the chunk and a lexical article only its noun; an article or articulated preposition requires its grammar point, as does every grammar detection. Grammar points require `read` (shown or heard) or `recall` (in model answers), never `listen` or `speak`.
- Glossed new tokens and `recognise` tokens require nothing, nor does a detection that covers one; names, numbers, foreign words, punctuation and allowlisted words require nothing.
- A lesson's target grammar points (its notes' `grammar`) are excluded from the requirements of the steps of that lesson that come before the note (the story comes before the note); an exercise after the note that shows a story line as its source does require them.
- The step that introduces an item doesn't require it: LearningCore subtracts a step's `step_introduces` from what its texts and exercises require when the step is entered (`docs/05`), so the rows stay complete and a review of the same exercise needs the items introduced.
- `pipeline/tests/fixtures/expected-requirements-u02-l1.json` holds the golden lesson's rows, checked by hand.

## Approval hash

`review.hash` is the sha256 (lowercase hex) of the file's bytes after normalising line endings to LF and removing the top-level `review:` entry (its line and any indented continuation lines; blank lines and column-0 comments *between* continuation lines belong to the entry, those after it don't). Flow style (`review: {status: draft, …}`) and block style hash alike. `content approve` writes it; `content lint` fails when an approved file's hash doesn't match, so any edit to approved content is caught even if the hook was bypassed.

## How content gets made (agents draft, people decide)

1. **Sign-off (weeks 1–3):** the content lead approves `syllabus/a1-syllabus.yaml`, all `unit.yaml` specs, `grammar/points.yaml` and `story-bible.yaml`. (`grammar/detection.yaml` stays with engineering.)
2. **Item graph:** agents draft `items/uNN.yaml` from the unit specs: words by need, then frequency (`content suggest`), about 55–70 new per unit, nouns with gender and plural, false friends flagged. The content lead reviews it with the specs.
3. **Drafting:** one non-interactive drafting run per lesson file, using the `italian-content` skill. It gets the unit spec, the story bible, the allowed items and the golden sample. Parallel runs each use **their own worktree** and `content check --unit uNN`, because they would otherwise race on `content/.annotations/` and `build/reports/`.
4. **Automatic checks:** `make annotate`, then `make check-content`; failures go back to the drafter with the report.
5. **Critic:** the content-critic subagent reviews each passing draft (story bible, naturalness, register, recycling, prices); the drafter fixes.
6. **Human review:** the content lead reviews and signs off through the review loop below; the owner runs `content approve --signoff`. Then `content tts`, and the audio reviewer listens (audio comments use the same loop).
7. **Beta:** units go to the beta cohort; `content beta-import` feeds weekly fixes, and rejected answers come back to the content lead for adjudication in the review page. Reopening an approved file needs the owner.

## Content review loop (how the teacher reviews, and how feedback gets back)

The content lead never edits YAML and never needs Git. They review in two places, both producing the same **review file**, and one command brings it into the project.

### 1 · Review pages (from week 1; no app needed)

- `content review-export --specs` covers the sign-off files (syllabus, unit specs, grammar points, story bible, countries, and the content questions in `docs/13`); `content review-export --unit u02` covers a unit's items, lessons, task and check.
- The output is **one self-contained HTML file** (styles, script and, from M5.1, audio embedded) that opens offline in any browser. The owner sends it by email or a shared folder.
- It shows everything a learner would meet, plus what a learner never sees at once: every story line with its English, the note, each exercise's prompt, model answer, **every accepted answer** (expanded and grouped) and each near-miss with its hint, conversations as a tree of turns, and the items with gloss, gender, plural and note.
- Every element has a verdict (✓ OK · ✎ Change · ? Question), a category (Italian error, unnatural, level, answer key, hint or rule, English, culture or facts, audio, other), a comment box and an optional "Suggested Italian" field. A header shows progress (reviewed / total).
- Comments save in the browser as the teacher types (local storage; some browsers don't keep it for files opened from disk, so the page warns and offers a download before closing). **Download my review** writes `review-<scope>-<date>.json` at any time, which the teacher sends back to the owner.
- After fixes, `--since` re-exports the page with each earlier comment's resolution (fixed, answered, declined with a reason) and highlights changed elements, so the teacher re-checks only those; they can reopen any comment.
- When no comment is open, **Sign off** asks for the teacher's name and adds a `signoff` block with the hash of every file they reviewed.

### 2 · Review mode in the app (from M6.10)

A `Review` build (dev pack with drafts, `ITA_REVIEW_MODE = YES`, no sync or telemetry) goes to an internal TestFlight group for the teacher. It shows what the page can't: the learner's experience, timing, audio, feedback and layout.

- Every unit and step is unlocked, with a jump menu and draft badges.
- **Comment** on any step, exercise, word card or story line (long-press): the sheet fills in the target ID, the quoted text and the file hash; the teacher adds the category, the comment and a suggestion.
- **Answer key** shows every accepted answer and near-miss of the current exercise.
- **This should be accepted**, in the feedback panel after a rejected answer, files an answer-key comment with the teacher's own answer in one tap.
- **Send** uploads the comments to the endpoint (`docs/12`) when `ITA_REVIEW_URL` is set; **Export** always writes the same review file through the share sheet.

### 3 · The review file

```json
{
  "format": 1, "reviewer": "…", "channel": "page", "scope": "u02", "created": "2026-10-20T09:12:00Z",
  "files": {"content/units/02-al-bar/lesson-1.yaml": "<approval hash of the version shown>"},
  "comments": [
    {"id": "6c1f…", "target": "u02.l1.story#3", "file": "content/units/02-al-bar/lesson-1.yaml",
     "quote": "Buongiorno. Vorrei un cappuccino, per favore.", "verdict": "change", "category": "naturalness",
     "comment": "…", "suggestion": "…", "response": null, "at": "2026-10-20T09:15:00Z"}
  ],
  "signoff": null
}
```

A `target` is any ID from `docs/03` (item, text line `<textId>#n`, exercise, conversation node `<exerciseId>/<nodeId>`, note, step) or a path into a spec file (`u02.can_do[1]`, `ch:giulia`). `response` holds the learner answer behind a "This should be accepted" comment. `signoff` is `{name, at, files: {path: hash}}`. `verdict` is `ok | change | question`; `category` is a lowercase key (`naturalness`, `answer-key`, …). Schema: `schemas/review-file.schema.json`.

The ledger `reviews/<scope>.yaml` (`schemas/review-ledger.schema.json`) keeps every comment of every imported review file, as filed, plus three fields:

```yaml
scope: u02
comments:
  - id: 6c1f…                                  # … every field of the comment as filed (target, file, quote, verdict, …)
    review: reviews/inbox/review-u02-2026-10-20.json   # the review file it came from
    hash: <approval hash of the version the teacher saw>  # optional, from the review file's `files`
    stale: false                               # made on an older version of the file
    resolution: {status: open, note: null, commit: null}   # open | fixed | answered | declined | owner
```

`answered`, `declined` and `owner` resolutions need a `note` for the teacher.

### 4 · Back into the project

1. **Import:** `uv run content review-import review-u02-2026-10-20.json` (the owner, or an agent the owner asks) copies the file unchanged into `reviews/inbox/`, checks every target, flags comments made on an older version as `stale`, and appends the comments to the ledger `reviews/u02.yaml` with `resolution: {status: open}`. Files in `reviews/inbox/` are the teacher's words: agents never edit them (a hook blocks it).
2. **Fix:** an agent works through the ledger with the `content-review` skill. For each open comment it edits the draft, then records `resolution: {status: fixed | answered | declined | owner, note, commit}`. Answer-key comments add accepted alternatives or near-misses; they never silently change a model answer. Suggestions that would break the level gate are declined with the reason and an alternative. Decisions about scope, story facts or register go to the owner (`status: owner`). Comments on approved files wait until the owner runs `content reopen`.
3. **Check:** `make annotate`, `make check-content`, then the content-critic on the changed files.
4. **Return:** `content review-export --unit u02 --since` produces the next page. The loop repeats until the teacher signs off.
5. **Approve:** the owner runs `uv run content approve <file> --by "<teacher>" --signoff reviews/inbox/<signed review>.json`. Because the sign-off carries the file hashes, the approved text is exactly the text the teacher signed.

`reviews/<scope>.yaml` is the audit trail: who said what about which version, and what was done about it. `content report` lists open comments per unit.

