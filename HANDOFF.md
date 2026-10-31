# Italian Learning App: Project Handoff

As of 2026-10-31. This file is the single source of truth for the project. Paste it into a new project as context.

Related artifacts (private until shared):
- Plan doc: https://claude.ai/artifact/1XmB2MpMvtVEvxBNW7UhzP
- Mocks canvas (iPhone, iPad, Mac): https://claude.ai/artifact/BGAkN5oybVfToot5mK8efQ
- Spec fixes proposal, approved 2026-10-31 (content IDs, form tags, learner model, pack format, minimum OS): https://claude.ai/artifact/6W2dzw9WVXqJAZuJY2buaE. Its decisions are folded into sections 3.4, 5, 5.1, 5.2, 6.2, 6.3, 6.5 and 9 below.

Where this file and the plan doc disagree, this file wins. The plan doc still describes grammar highlight layers, conjugation drills and a "vocab trainer"; all three were replaced by the decisions below.

---

## 1. The product in one paragraph

A native app for iPhone, iPad and Mac that teaches Italian through reading and listening. Learners read graded texts (100 texts, A1 to B2) as plain text. When they tap a word or phrase they get help: meaning in context, the dictionary form, a grammatical analysis, and why that form is used. Anything from that help (a word, a verb form, a grammar point) can be kept in **Remember**, a flashcard deck reviewed with spaced repetition, always shown in the sentence it came from. A full offline dictionary, verb tables and grammar reference sit behind it. Listening uses on-device text-to-speech. Everything works offline; progress syncs over iCloud; there is no server.

## 2. Decisions so far

| Area | Decision |
| --- | --- |
| Platforms | iPhone, iPad, Mac. One SwiftUI codebase with a native macOS target (not Mac Catalyst). |
| Offline | Every feature works in airplane mode. The network is used only for iCloud sync and optional text-pack downloads. |
| Backend | None. The learner's Apple ID is the identity; CloudKit private database is the only cloud. |
| Reading | Text first. The reader shows clean text with no highlighting, colour coding or grammar layers. Help appears only on tap (iPhone), in a popover (iPad) or in an inspector panel (Mac). |
| Grammar | Reference only: explicit lookup, verb tables, grammar pages. No drills, no quizzes. |
| Remember | Replaces the "vocab trainer". Three kinds of item: Word, Verb form, Grammar point. Reviewed as flashcards (FSRS scheduling), front shows the original sentence with the item highlighted. |
| Library | 100 texts across A1 to B2, grouped by level and collection, ranked by "good fit" (share of words the learner already knows). |
| Navigation (iPhone) | Tabs: Read, Dictionary, Verbs, Remember, Listen. Settings is reached from Read. "Today" was dropped. |
| Listening | On-device TTS (`AVSpeechSynthesizer`). Player with "Show text" and "Listen first" modes, sentence-by-sentence navigation, repeat, speed. |
| Questions | Each text has comprehension questions; a wrong answer shows the sentence that answers it. |
| iPhone help sheet | The sentence translation was removed (user feedback). iPad popover and Mac inspector still show it: open question. |

## 3. Functional spec

### 3.1 Reader and tap-for-help

- Text is plain, serif, comfortable size (19 pt iPhone, 21 pt Mac, 22 pt iPad in the mocks). Only the current selection is highlighted.
- Tap a word, or select a phrase, to open help. Help contains:
  - The tapped words, a play button, and the meaning in this context ("we would go").
  - Lemma and analysis: `andare · condizionale passato · noi`.
  - Splits for contractions and clitics: `dal = da + il`, `dammelo = da' + me + lo`.
  - A short "why this form" note when there is a grammar point (e.g. "future in the past: condizionale passato after a past verb, where English says *would*").
  - **Remember** rows, one per item that can be kept: Word (`andare`, to go), Verb form (`saremmo andati`, cond. passato, noi), Grammar (`Future in the past`). Each toggles Remember / Added.
  - Links: open the verb page, open the dictionary entry.
- Read aloud and text-size controls in the reader toolbar. Questions are reachable at the end of the text and from the toolbar on iPad/Mac.

### 3.2 Dictionary

Lookup cascade, stopping at the first hit:
1. Normalise input (lowercase, trim, split elisions: `dall'Italia` → `dall'` + `Italia`).
2. Exact headword.
3. Inflected form → lemma (`andavamo` → `andare`, imperfetto, noi). Show the parse.
4. Clitic split for verb + pronoun forms (`dammelo`).
5. `NLTagger` lemma as a last resort.
6. Fuzzy: FTS5 prefix, then accent-insensitive ("did you mean *perché*").
7. Several words: offer sentence translation.

Ambiguous forms list every reading (`canti` → cantare indicativo presente tu; cantare congiuntivo presente io/tu/lui; canto, noun plural). Each reading has a Remember button.

Entry page: headword with article, IPA, gender, plural, numbered senses with examples, common phrases, "In your texts" occurrences, related words, source credit ("Entry from Wiktionary, CC BY-SA").

English → Italian search runs over English glosses; weaker, so curate the most frequent words by hand.

### 3.3 Verbs and grammar reference

- Verbs home: search accepting any form (`vada`), recent verbs, most-used irregular verbs, list of grammar topics.
- Verb page: lemma, meaning, badges (irregular, auxiliary, conjugation group), participle and gerund, a banner for the form the learner came from, mood tabs, tense blocks with irregular forms in bold orange, the looked-up form highlighted.
- Mac shows the full table at once (indicativo presente, imperfetto, passato remoto, futuro; congiuntivo presente, imperfetto; condizionale; imperativo).
- Compound tenses are generated from auxiliary + past participle, with agreement for *essere* verbs (`andato/a/i/e`). Store the auxiliary per verb (some take both).
- Reflexive and pronominal verbs (`lavarsi`, `andarsene`) are modelled explicitly.
- Grammar pages: when it is used, how it is formed (table), common irregulars, examples from the learner's own texts, "Find all in my texts", Remember button.

### 3.4 Remember and review

- Item kinds: **Word**, **Verb form**, **Grammar**. (A fourth kind, **Phrase** for collocations like *essere d'accordo*, is proposed; see open questions.)
- Each item has a key that identifies it across devices (section 6.5): Word `word|lemmaID|senseID`, Verb form `verbForm|lemmaID|formTag` (no sense: a form is the same whatever the meaning), Grammar `grammar|grammarID`.
- Every item keeps its source text and sentence, plus a snapshot of the sentence so the card renders on devices without that pack. Items added from the dictionary or a verb page snapshot an example sentence from the entry, or show the headword alone. The card front is that sentence with the item highlighted (several ranges, so split units like *non l'**ho** mai **visto*** work), plus a prompt:
  - Word: "What does it mean?"
  - Verb form: "Which verb, tense and person?"
  - Grammar: "What is this construction, and how would you say it in English?"
- Back: the answer, a one-line explanation, and for verb forms the full row (`sarei, saresti, sarebbe, saremmo…`).
- Grading: Again / Hard / Good / Easy with the next interval shown. Mac keys: Space shows answer, 1 to 4 grade.
- Scheduling: FSRS-6 via a Swift package behind a `Scheduler` protocol. Candidates: `open-spaced-repetition/swift-fsrs` (MIT, now FSRS-6), `bitbemol/swift-fsrs` (FSRS v6, unofficial, pre-1.0). The schedule is computed from the synced review logs and kept on each device (section 5.2).
- Deleting a card hides it (soft delete). Adding the same item again restores it with its review history.
- Remember tab: due count with Review button, filters (All, Words, Verb forms, Grammar), lists grouped New / Due today / Later.
- Settings: new items per day, daily reminder time.

### 3.5 Library

- iPhone: search, level chips with counts, Continue reading, "Good fit for you" (texts with ~90 to 97% known words), By level with progress.
- Mac: sortable table (title, level, collection, words, known %, status) with a preview panel.
- "Known %" = share of running words in the text that the learner has met or kept. Reading research suggests 95 to 98% known words for comfortable reading; use it to rank and to guide authoring.

### 3.6 Listen

- Listen tab: voice-quality banner when only the standard voice is installed, Continue, "Listen first" (new texts), "Listen again" (texts already read).
- Player: Show text / Listen first toggle; current sentence and word highlighted; scrubber with sentence count; previous / play-pause / next sentence; speed (0.6× to 1×); repeat each sentence; voice.
- Enhanced and Premium Italian voices must be installed by the learner in iOS Settings (Accessibility › Spoken Content › Voices); the app detects voice quality and shows a guide. There was no API to trigger the download through iOS 26; check whether iOS 27 added one (open task).
- Optional: render a text to buffers with `write(_:toBufferCallback:)` for a scrubbable timeline; background audio with Now Playing info.

### 3.7 Comprehension questions

Multiple choice and yes/no/not stated per text, in Italian with an English toggle. Correct and wrong picks are marked; a wrong answer shows the answering sentence with "Show in text".

### 3.8 Onboarding and settings

- First launch: checklist (dictionary built in; starter texts included; sentence translation download; enhanced voice guide; iCloud sync on) and a level pick (A1 to B2).
- Settings: iCloud sync and last sync; offline status (translation downloaded, voice quality, downloaded texts); level, text size, sentence translation in help; Remember new items per day and reminder; acknowledgements (Wiktionary, Morph-it!, Tatoeba); version.

## 4. Screen inventory (mocks)

| Screen | Platform | Mock file |
| --- | --- | --- |
| Library, 100 texts | iPhone | Library.dc.html |
| Reader with tap-for-help sheet | iPhone | Main.dc.html |
| Comprehension questions | iPhone | Questions.dc.html |
| Remember list | iPhone | Remember.dc.html |
| Flashcard review (word / verb form / grammar variants) | iPhone | Review.dc.html |
| Form lookup results | iPhone | Lookup.dc.html |
| Dictionary entry | iPhone | Entry.dc.html |
| Verbs and grammar home | iPhone | VerbsHome.dc.html |
| Verb page | iPhone | Verb.dc.html |
| Grammar reference page | iPhone | Grammar.dc.html |
| Listen | iPhone | ListenHome.dc.html |
| Player | iPhone | Player.dc.html |
| First launch setup | iPhone | Onboarding.dc.html |
| Settings | iPhone | Settings.dc.html |
| Reader with popover help | iPad | iPadReader.dc.html |
| Library | Mac | MacLibrary.dc.html |
| Reader with inspector | Mac | Mac.dc.html |
| Dictionary and full verb table | Mac | MacDictionary.dc.html |
| Review | Mac | MacRemember.dc.html |

Not mocked yet: dark mode, iPad library and review, Mac Listen and Settings, widgets, text-size sheet, grammar topic index, acknowledgements.

## 5. Architecture

| Layer | Choice |
| --- | --- |
| UI | SwiftUI multiplatform, native macOS target, `NavigationSplitView` (tabs on iPhone, sidebar on iPad/Mac) |
| Language | Swift 6 with strict concurrency |
| Minimum OS | iOS / iPadOS / macOS 26.0 (decided 2026-10-31; exact value in `project.yml`). Builds with the hosted runners' default Xcode 26.6, so CI and TestFlight need no Xcode 27. Intel Macs on macOS 26 stay supported. Pack downloads are enabled at runtime only on 26.7 and later, which avoids the 26.4–26.6 Background Assets download failures |
| Content store | Read-only SQLite (via GRDB) bundled with the app, FTS5 index, plus a catalog of every text (downloaded or not) |
| Learner store | SwiftData + CloudKit private database for cards, review logs, progress and lookups; the FSRS schedule cache in a separate local-only SwiftData store |
| Scheduler | FSRS-6 package behind a protocol |
| Speech | `AVSpeechSynthesizer`, it-IT voices |
| Translation | Apple Translation framework, on device after a one-time download; does not run in the Simulator |
| Lemmatizer fallback | NaturalLanguage `NLTagger` (`.lemma`, `.lexicalClass` support Italian) |
| Text delivery | Starter texts bundled; the rest as Apple-hosted Background Assets (iOS/macOS 26+) |
| Optional AI | Foundation Models framework, only on Apple Intelligence devices, never required |

Suggested Swift packages: `LexiconKit` (lookup cascade, forms, entries), `GrammarKit` (verb tables, grammar topics), `SRSKit` (FSRS, log replay), `PackKit` (pack loading, downloads, `PackStore`), `SpeechKit` (TTS, highlighting), `TranslateKit`, `SyncStore` (SwiftData models, merge pass), plus the app target.

### 5.1 Learner data model (SwiftData)

Only facts sync: what the learner kept and every review they did. The FSRS schedule is derived from the logs and lives in a separate local-only store on each device, so a review never writes to a synced record and two devices never conflict over schedule fields.

```swift
// Synced: SwiftData + CloudKit private database
@Model final class Card {
    var id: UUID = UUID()
    var itemKey: String = ""            // per kind, section 6.5
    var kind: String = "word"           // word | verbForm | grammar (phrase: open question)
    var lemmaID: String = ""            // key into the bundled content DB (section 6.5)
    var senseID: String = ""
    var formTag: String = ""            // section 6.5, e.g. "cond.pass.1p"
    var grammarID: String = ""          // e.g. "future-in-the-past"
    var surface: String = ""            // as it appeared: "saremmo andati"
    var sourceTextID: String = ""       // empty when added from the dictionary or a verb page
    var sourceSentenceID: String = ""
    // Snapshot, so the card renders on a device without that pack
    var sentenceText: String = ""       // NFC
    var sentenceTranslation: String = ""
    var highlightRanges: String = ""    // "14:6,27:3": UTF-16 start:length, allows split units
    var createdAt: Date = Date.now
    var deletedAt: Date? = nil          // soft delete
    var restoredAt: Date? = nil         // active when deletedAt is nil or restoredAt > deletedAt
}

@Model final class ReviewLog {
    var id: UUID = UUID()
    var itemKey: String = ""            // links the log to an item, not to a card
    var cardID: UUID = UUID()           // informational only
    var reviewedAt: Date = Date.now
    var tzOffsetMinutes: Int = 0        // day boundaries in replay
    var rating: Int = 0                 // 1 Again, 2 Hard, 3 Good, 4 Easy
    var durationMs: Int = 0
    var deviceID: String = ""           // random UUID per install, kept in local UserDefaults
}

@Model final class TextProgress {
    var id: UUID = UUID()
    var textID: String = ""
    var position: Double = 0            // where reading stopped (0...1)
    var maxFractionRead: Double = 0
    var finishedAt: Date? = nil
    var answersJSON: String = ""        // {"q1": {"choice": 1, "at": "2026-10-31T15:00:00Z"}}
    var updatedAt: Date = Date.now
}

@Model final class LookupEntry {
    var id: UUID = UUID()
    var query: String = ""
    var lemmaID: String = ""
    var lookedUpAt: Date = Date.now
}

// Local only: its own ModelConfiguration with cloudKitDatabase: .none
@Model final class ScheduleState {
    var itemKey: String = ""
    var state: Int = 0                  // 0 new, 1 learning, 2 review, 3 relearning
    var step: Int = 0                   // learning-step index (FSRS-6)
    var stability: Double = 0
    var difficulty: Double = 0
    var reps: Int = 0
    var lapses: Int = 0
    var scheduledDays: Int = 0
    var lastReviewedAt: Date? = nil
    var due: Date = Date.now
}
```

`ScheduleState` mirrors the chosen FSRS package's card struct; adjust its fields to match once the package is picked.

Preferences (level, text size, new items per day, reminder) and the FSRS parameters go in `NSUbiquitousKeyValueStore`.

**Known words** are derived, not stored. A lemma counts as known if any of these hold: it is in the core vocabulary of a level below the learner's (needs the frequency or core list, section 9); it has an active Word or Verb form card; it appears in at least two texts the learner finished. Known % uses the bundled catalog (section 6.3), so it works for texts not yet downloaded. If placement lands in v1, it adds a small `LemmaMark` model.

### 5.2 Sync rules

- What syncs: cards, review logs, text progress, lookup history (capped), preferences, FSRS parameters. What doesn't: the schedule cache (`ScheduleState`, rebuilt per device), content DB (ships with the app), downloaded packs (re-downloaded per device), translation models and voices (system assets).
- SwiftData + CloudKit constraints: no `@Attribute(.unique)`; every property optional or defaulted; relationships optional; never rename, delete or retype a property after the schema is in Production (add new ones instead); lightweight migrations only; deploy the schema to Production in the CloudKit Dashboard before each release that changes it; private database only.
- `ReviewLog` is append-only and the source of truth. It is never edited, not even by the merge pass. After remote changes, replay an item's logs in time order into `ScheduleState`.
- Replay must give the same result on every device. The FSRS parameters (weights, desired retention, maximum interval, learning steps, short-term mode) are one versioned blob in `NSUbiquitousKeyValueStore`; changing them rebuilds every `ScheduleState`. Replay uses no fuzz, or fuzz seeded from the log's UUID. The day rolls over at 4:00 local time, using each log's `tzOffsetMinutes`.
- Merge pass after each sync:
  - Cards: duplicates are cards with the same `itemKey` after resolving IDs through `id_redirect` (section 6.5). Keep the oldest `createdAt`, ties going to the smaller UUID, and delete the rest. Logs need no moving because they point at the item. If any duplicate is active, the survivor is active.
  - A card whose IDs the local content DB doesn't know is never merged or deleted; it renders from its snapshot.
  - TextProgress: duplicates for one `textID` merge into the oldest record. `position` comes from the newest `updatedAt`, `maxFractionRead` takes the highest, `finishedAt` the earliest, and each answer the newer `at`.
  - LookupEntry: one global cap of 200, trimmed oldest first on any device.
- Keep sync behind a repository protocol so it can move to GRDB + `CKSyncEngine` if SwiftData limits bite.
- Test on real devices: same card reviewed offline on two devices; same item added offline on two devices; a card deleted on one device while the other reviews it offline; fresh install; signed out of iCloud.

## 6. Content

### 6.1 Sources and licences

| Data | Source | Licence | Use |
| --- | --- | --- | --- |
| Italian→English entries, IPA, gender, plurals, verb tables | kaikki.org Italian dictionary (Wiktionary via wiktextract; rebuilt regularly) | CC BY-SA | Dictionary, verb tables, reverse index |
| Inflected form → lemma | Morph-it! (~505k forms, ~35k lemmas; newspaper corpus, gaps in everyday words) | CC BY-SA 2.0 or LGPL | Form analysis, clitics, cross-checks |
| Example sentences with translations | Tatoeba ita–eng pairs (weekly exports) | CC BY 2.0 FR (some CC0); audio per contributor, often unusable | Examples |
| Reading texts | Written or commissioned; public-domain classics for upper levels | Yours / public domain | Library |
| Word frequency ranking | Not chosen | Check | "Known %", ordering |

The database built from Wiktionary and Morph-it! must be offered under CC BY-SA; app code is unaffected. Get a legal review. Credit sources in Acknowledgements.

### 6.2 Build pipeline (offline, never on device)

1. Download pinned, dated dumps: kaikki/wiktextract Italian data, Morph-it!, Tatoeba ita–eng pairs. Record the dump dates; never build from "latest".
2. Normalise into SQLite: `lemma`, `sense`, `form`, `conjugation`, `sentence`, `grammar_topic`, `id_redirect`, `catalog_text`, `text_lemma`, plus FTS5 on headwords and glosses. All text NFC.
3. Match against the ID registry (section 6.5): reuse existing IDs, mint new ones, retire or redirect vanished ones, write the review list.
4. Map source morphology tags (Morph-it!, kaikki) to our form tags through one tested mapping table (section 6.5).
5. Validate: every Morph-it! verb form resolves to a lemma; common verbs match Wiktionary; every source tag maps; no ID used by a pack or listed as in use vanishes; every catalog text has its lemma set.
6. Stamp a content version (including the dump dates); bundle read-only.

### 6.3 Text packs

- A pack is a versioned folder: `manifest.json` plus one JSON file per text. See `content/fixtures/manifest.json` and `content/fixtures/racconti-brevi-03.json`. The format is defined by JSON Schema 2020-12 files in `content/schema/` (`manifest.schema.json`, `text.schema.json`); the fixtures are test cases for it.
- Text is stored verbatim in typed **blocks** (`prose`, `dialogue`, `message`, `list`, `sign`, `verse`). Dialogue blocks carry a `speaker`, which also drives two-voice TTS. Each block holds its sentences; each sentence holds its tokens.
- **Ranges.** Sentences carry `r: [start, length]` into their block's `text`, and tokens carry `r` into their sentence's `text`. Sentences also repeat their `text` for readability; the build checks it equals the slice. Ranges count UTF-16 code units (what TextKit, `NSRange` and `AVSpeechSynthesizer` use) over NFC text. The build computes UTF-16 lengths explicitly (Python's `len()` counts code points) and checks that every range slices out exactly the token's `t`. The app converts to `AttributedString` indices through one helper.
- Every token is pre-linked at build time to `lemmaID` and `senseID` (section 6.5) and carries its analysis: `pos` (Universal Dependencies UPOS), `form` (section 6.5 form tag), `agree` (participle agreement, `ms` `fs` `mp` `fp`), `gn` (gender and number of nouns and adjectives), and any `grammar` topic tags. This powers tap-for-help without guessing; it is not shown as highlighting.
- Contractions and clitic clusters are UD multiword tokens: the surface token (`dai`, `dammelo`) has no `pos` and lists `parts`, each with its own UPOS and lemma.
- Free text on a token is limited to `gloss` (meaning in this context) and `note` (a remark for the learner).
- **Units** (`units[]`) cover multi-token forms and phrases: `tokens` are 0-based token indices and need not be adjacent (*non l'**ho** mai **visto***). A token belongs to at most one unit; tapping any token in a unit opens the unit's help.
- Each sentence has an English translation. Each text has questions with `optionsEN` for the English toggle and `answerSentences` (one or more sentence IDs).
- Manifest: `formatVersion` (schema version, separate from the pack's content `version`), `minContentDB` (lowest content DB that resolves the pack's IDs), and per text its lemma set so a pack newer than the app can still be ranked.
- Each app release bundles a catalog (`catalog_text`, `text_lemma`) of every text, downloaded or not, for library ranking, "Good fit" and Known %.
- Pack builds fail when an ID doesn't resolve, a range doesn't match, text isn't NFC, or units overlap.
- Authoring: Markdown with front matter → build tool tokenises, links lemmas, proposes analyses, flags unknowns → native speaker reviews → pack. Sentence IDs (`s<n>`) are assigned once and never renumbered when a text is edited after release.
- Delivery: starter texts bundled; others as Apple-hosted asset packs (up to 200 packs, 200 GB per app; reviewed separately from builds). Packs stay on disk until `remove(assetPackWithID:)`. Use only the current `AssetPackManager` API; several methods were deprecated in 26.4 and 27.0. 26.4–26.6 had download failures, so downloads are offered only on 26.7 and later (`#available`); earlier 26.x devices read the bundled texts. Bundle enough to never block the first session; add retry and "not downloaded" states. Don't use On-Demand Resources (deprecated in iOS 27).

### 6.4 Curriculum gaps to close

1. **Scope and sequence.** Define per level the grammar points and core vocabulary; tag each text with what it uses and introduces; order texts to add one or two points at a time and recycle earlier ones. Reference: *Profilo della lingua italiana* (Spinelli & Parizzi), CEFR levels A1 to B2.
2. **Vocabulary targets.** Write each text for ~95 to 98% known words at its level; make new words recur in later texts.
3. **Speaking and writing.** Currently out of scope by default. Options that fit: shadowing (optionally with on-device speech recognition), short writing prompts per text with optional on-device model feedback.
4. **A1 on-ramp.** Tiny first texts, fuller help, pronunciation basics (double consonants, c/g/sc before e/i, gli/gn, stress), survival phrases, numbers, time.
5. **Text variety and register.** Dialogues (two voices), messages, emails, signs, menus, articles; *tu* vs *Lei*. Narrative alone over-weights the passato remoto.
6. **Placement and progress.** Short placement (calibrated passages, mark unknown words); per-level progress (texts read, core words known, grammar points met).

Smaller: Phrase as a fourth Remember kind; full A1 to B2 grammar topic list; cultural notes.

### 6.5 Content IDs and form tags

Cards live in CloudKit indefinitely and packs reference content by ID, so IDs must survive every rebuild of the dictionary. Wiktionary reorders, splits and merges senses between kaikki dumps, so IDs are never positions in the source.

**ID formats**

| Kind | Format | Example | Minted by |
| --- | --- | --- | --- |
| Lemma | `it:<headword>:<pos>`, plus `:<n>` for the 2nd and later homograph with the same part of speech | `it:pesca:n` (peach), `it:pesca:n:2` (fishing) | Registry, when the entry is first seen |
| Sense | `<lemmaID>#<code>`, code = 4 base32 characters from a hash of the sense's fingerprint (5+ on collision) | `it:andare:v#k3fq` | Registry, when the sense is first seen |
| Grammar topic | Hand-picked kebab-case slug | `future-in-the-past` | Us, in `content/grammar/` |
| Text | `<collection>-<nn>` | `racconti-brevi-03` | Authoring tool |
| Sentence | `s<n>`, unique within its text | `s2` | Authoring tool |

Headwords are NFC, lowercase except proper nouns; spaces in multiword lemmas become `_`. Homograph numbers are ours, assigned when an entry is first seen, never taken from Wiktionary's etymology order. Sense codes are meaningless on purpose: readable codes invite renaming, and renaming breaks synced cards.

**Registry.** `content/ids/lemmas.tsv` and `content/ids/senses.tsv` map each ID to the fingerprint it was minted from. On each rebuild every sense is matched in this order: wiktextract's `senseid`, then its Wikidata QID, then headword + part of speech + normalised gloss. Etymology numbers are never used (they are positions and changed type in 2026). Unmatched senses get a fresh, hash-derived ID, so builds are reproducible. Uncertain matches go to a review list, limited to senses used by packs or in the curated frequent-word set. IDs are edited only by the pipeline, never by hand.

| Change in the source | What the registry does |
| --- | --- |
| Sense removed | ID retired but kept in the DB with its last gloss: hidden from search, still renders on cards, never redirected to a lemma |
| Two senses merged | Losing ID redirects to the surviving sense (sense to sense only) via `id_redirect` |
| One sense split in two | Old ID stays on the closer child; the other child gets a new ID |
| Homographs reordered | Nothing; homograph numbers are ours |

The app resolves every stored ID through `id_redirect` before use and never rewrites cards for it. Grammar slugs and sentence IDs are frozen once shipped, with the same redirect rule.

**Form tags.** One tag per verb form, used by cards (`formTag`), packs (`form`), the content DB and verb tables: `mood.tense.person` for finite forms, `mood.tense` for the rest.

| Part | Codes |
| --- | --- |
| Mood | `ind` indicativo, `sub` congiuntivo, `cond` condizionale, `imp` imperativo, `inf` infinito, `ger` gerundio, `part` participio |
| Simple tense | `pres` presente, `impf` imperfetto, `prem` passato remoto, `fut` futuro |
| Compound tense, indicativo | `pp` passato prossimo, `tpp` trapassato prossimo, `tpr` trapassato remoto, `futa` futuro anteriore |
| Compound tense, other moods | `pass` passato (sub, cond, inf, ger), `tpp` trapassato (sub) |
| Imperativo | `pres` affirmative, `neg` negative (only `imp.neg.2s`, *non andare*, differs in form) |
| Person | `1s` `2s` `3s` `1p` `2p` `3p` (Lei = `3s`, Loro = `3p`) |
| Auxiliary suffix | `+e` / `+a` on compound tags, only for verbs that take both (`ind.pp.3s+e` *è corso*, `ind.pp.3s+a` *ha corso*) |

Examples: `ind.impf.1p` (andavamo), `ind.prem.1s` (compii), `cond.pass.1p` (saremmo andati), `sub.tpp.1s` (fossi andato), `imp.pres.2s` (va'), `imp.neg.2s` (non andare), `part.pres` (cantante), `part.pass` (andato).

Not in the tag: participle agreement (`agree`), so *saremmo andati* and *saremmo andate* are one card; reflexive and pronominal verbs, which are their own lemmas (`lavarsi`, `andarsene`); clitics, which are token parts; the passive, which is a grammar topic in v1. The app turns tags into labels ("condizionale passato · noi") from one lookup table; packs and cards never store label text.

Source tags differ: Morph-it! writes passato remoto as `ind+past`, which maps to `ind.prem`. The pipeline's mapping table has tests, and the build fails on an unmapped tag.

**Item keys** (dedupe and log linking): Word `word|lemmaID|senseID`, Verb form `verbForm|lemmaID|formTag`, Grammar `grammar|grammarID`.

## 7. Design (from the mocks)

Look: quiet, text first, no colour except where it carries meaning. The mocks use web stand-in fonts; in the native app use **New York** (serif) for Italian text and **SF Pro** for UI.

- Type: reading text serif 19/21/22 pt, line height ~1.7. Large titles 32 bold. Section labels 12, semibold, uppercase, tracking 0.06 em. Body 15. Meta 13.
- Shape: chips 16 radius (32 high inside 44 touch target), cards 14 to 16, sheets 20, buttons 12, tags 5 to 6.
- Colour tokens: `design/tokens.json`. Key ones: ink `#17181A`, secondary `#4A4E55`, tertiary `#5B5F66`, hairline `#E4E5E8`, accent `#2251CC`, selection `#DCE5FF`, added `#E7F3EC`/`#1D5A35`, irregular form `#9A4300`.
- Kind tags: Word gray, Verb form teal, Grammar blue. Level badges: A1 green, A2 teal, B1 blue, B2 purple.
- Touch targets ≥ 44 pt on iPhone/iPad. Dynamic Type, VoiceOver labels on every icon button, Italian text marked `it-IT` so VoiceOver pronounces it.
- Dark mode not designed yet.

## 8. Roadmap

| Phase | Scope | Gate |
| --- | --- | --- |
| 1 Foundations | Content DB pipeline, app shell on 3 platforms, SwiftData model, lookup cascade | Any word form looks up offline on all 3 devices |
| 2 Core loop | Dictionary + entry, Verbs home, verb pages, grammar pages, Remember (3 kinds), review, FSRS, iCloud sync | Remember on iPhone, review on Mac, no duplicates |
| 3 Read + listen | Pack format + authoring tool, library, reader with tap-for-help, questions, Listen + player, starter texts | TestFlight with native-reviewed texts |
| 4 Launch v1.0 | Apple-hosted packs, onboarding, settings, widgets and App Intents, accessibility | Passes App Review; CloudKit schema in Production |
| 5 After launch | Imported texts, AI-drafted questions, recorded audio, EN→IT curation, curriculum additions | Ongoing |

## 9. Open questions

- [ ] Speaking and writing: in scope?
- [ ] Phrase as a fourth Remember kind?
- [ ] Sentence translation in iPad popover and Mac inspector: keep or remove (removed on iPhone)?
- [x] Minimum OS 26 or 27? **26.0** (decided 2026-10-31, replacing an earlier choice of 27; see section 5).
- [ ] Business model: paid, subscription, or free with paid packs?
- [ ] Learners' base language: English only for v1?
- [ ] Who writes and reviews the 100 texts; level split (mocks use 20/28/30/22)?
- [ ] Which word-frequency list, and its licence?
- [ ] Placement test in v1?
- [ ] Legal sign-off on CC BY-SA obligations.

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| Writing 100 good graded texts is the biggest effort | Build the authoring tool early; start with a polished subset |
| Share-alike licences on the dictionary DB | Acknowledgements; publish the DB or build script under CC BY-SA; legal review |
| Uneven Wiktionary coverage, weak EN→IT | Hand-curate frequent words; "Report a problem" on entries |
| SwiftData schema is add-only once live | Finalise the model before the first Production deploy; keep derived state (the FSRS schedule) out of the synced schema |
| Content IDs drift between dictionary rebuilds | ID registry, pinned dumps, redirects, build fails on vanished IDs (section 6.5) |
| Asset-pack download reliability and API churn | Bundle starters; retry states; one `PackStore` wrapper |
| TTS quality depends on voices the learner installs | Onboarding guide; recorded audio later |

## 11. Sources

- kaikki.org Italian dictionary: https://kaikki.org/dictionary/Italian/index.html
- Morph-it! README and licence: https://app.unpkg.com/italian-verbs-dict@3.4.0/files/dist/readme-morph-it.txt
- Tatoeba downloads: https://tatoeba.org/en/downloads
- NLTagger language support: https://gist.github.com/mattt/36357b7ffe9370d6fc573088aed0d1f5
- Translation framework on device: https://blakecrosley.com/blog/apple-translation-framework-on-device
- TranslationSession init(installedSource:target:): https://developer.apple.com/documentation/translation/translationsession/init(installedsource:target:)
- Apple-hosted asset packs: https://developer.apple.com/help/app-store-connect/manage-asset-packs/overview-of-apple-hosted-asset-packs
- On-Demand Resources deprecation and Background Assets: https://blakecrosley.com/blog/on-demand-resources-deprecated-background-assets
- Asset-pack download failures (forum): https://developer.apple.com/forums/thread/845723
- CloudKit model rules for SwiftData: https://fatbobman.com/en/snippet/rules-for-adapting-data-models-to-cloudkit/
- swift-fsrs: https://github.com/open-spaced-repetition/swift-fsrs
- wiktextract (sense ids, Wikidata links): https://github.com/tatuylonen/wiktextract
- iOS 27 release (14 September 2026, iPhone 11 and newer): https://macrumors.com/2026/09/09/apple-announces-ios-27-release-date/
