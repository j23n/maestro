# Italian Learning App: Project Handoff

As of 2026-10-31. This file is the single source of truth for the project. Paste it into a new project as context.

Related artifacts (private until shared):
- Plan doc: https://claude.ai/artifact/1XmB2MpMvtVEvxBNW7UhzP
- Mocks canvas (iPhone, iPad, Mac): https://claude.ai/artifact/BGAkN5oybVfToot5mK8efQ

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
- Every item keeps its source text and sentence. The card front is that sentence with the item highlighted, plus a prompt:
  - Word: "What does it mean?"
  - Verb form: "Which verb, tense and person?"
  - Grammar: "What is this construction, and how would you say it in English?"
- Back: the answer, a one-line explanation, and for verb forms the full row (`sarei, saresti, sarebbe, saremmo…`).
- Grading: Again / Hard / Good / Easy with the next interval shown. Mac keys: Space shows answer, 1 to 4 grade.
- Scheduling: FSRS via a Swift package behind a `Scheduler` protocol. Candidates: `open-spaced-repetition/swift-fsrs` (MIT, FSRS-5), `bitbemol/swift-fsrs` (FSRS v6, unofficial, pre-1.0).
- Remember tab: due count with Review button, filters (All, Words, Verb forms, Grammar), lists grouped New / Due today / Later.
- Settings: new items per day, daily reminder time.

### 3.5 Library

- iPhone: search, level chips with counts, Continue reading, "Good fit for you" (texts with ~90 to 97% known words), By level with progress.
- Mac: sortable table (title, level, collection, words, known %, status) with a preview panel.
- "Known %" = share of running words in the text that the learner has met or kept. Reading research suggests 95 to 98% known words for comfortable reading; use it to rank and to guide authoring.

### 3.6 Listen

- Listen tab: voice-quality banner when only the standard voice is installed, Continue, "Listen first" (new texts), "Listen again" (texts already read).
- Player: Show text / Listen first toggle; current sentence and word highlighted; scrubber with sentence count; previous / play-pause / next sentence; speed (0.6× to 1×); repeat each sentence; voice.
- Enhanced and Premium Italian voices must be installed by the learner in iOS Settings (Accessibility › Spoken Content › Voices); the app detects voice quality and shows a guide. There has been no API to trigger the download; re-check on iOS 27.
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
| Minimum OS | iOS / iPadOS / macOS 26 (managed asset packs, `TranslationSession(installedSource:target:)`, Foundation Models). Open: 26 vs 27 |
| Content store | Read-only SQLite (via GRDB) bundled with the app, FTS5 index |
| Learner store | SwiftData + CloudKit private database |
| Scheduler | FSRS package behind a protocol |
| Speech | `AVSpeechSynthesizer`, it-IT voices |
| Translation | Apple Translation framework, on device after a one-time download; does not run in the Simulator |
| Lemmatizer fallback | NaturalLanguage `NLTagger` (`.lemma`, `.lexicalClass` support Italian) |
| Text delivery | Starter texts bundled; the rest as Apple-hosted Background Assets (iOS/macOS 26+) |
| Optional AI | Foundation Models framework, only on Apple Intelligence devices, never required |

Suggested Swift packages: `LexiconKit` (lookup cascade, forms, entries), `GrammarKit` (verb tables, grammar topics), `SRSKit` (FSRS, log replay), `PackKit` (pack loading, downloads, `PackStore`), `SpeechKit` (TTS, highlighting), `TranslateKit`, `SyncStore` (SwiftData models, merge pass), plus the app target.

### 5.1 Learner data model (SwiftData)

```swift
@Model final class Card {
    var id: UUID = UUID()
    var kind: String = "word"          // word | verbForm | grammar (phrase: open question)
    var lemmaID: String = ""           // key into the bundled content DB
    var senseID: String = ""
    var formTag: String = ""           // e.g. "cond.pass.1pl" for verb forms
    var grammarID: String = ""         // e.g. "future-in-the-past"
    var surface: String = ""           // as it appeared: "saremmo andati"
    var sourceTextID: String = ""      // where it was found
    var sourceSentenceID: String = ""  // card front
    var createdAt: Date = Date.now
    // FSRS cache, rebuilt from logs after sync
    var stability: Double = 0
    var difficulty: Double = 0
    var due: Date = Date.now
}

@Model final class ReviewLog {
    var id: UUID = UUID()
    var cardID: UUID = UUID()
    var reviewedAt: Date = Date.now
    var rating: Int = 0                // 1 Again, 2 Hard, 3 Good, 4 Easy
    var deviceID: String = ""
}

@Model final class TextProgress {
    var id: UUID = UUID()
    var textID: String = ""
    var fractionRead: Double = 0
    var finishedAt: Date? = nil
    var answersJSON: String = ""       // question id -> chosen option
    var updatedAt: Date = Date.now
}

@Model final class LookupEntry {
    var id: UUID = UUID()
    var query: String = ""
    var lemmaID: String = ""
    var lookedUpAt: Date = Date.now
}
```

Preferences (level, text size, new items per day, reminder) go in `NSUbiquitousKeyValueStore`.

### 5.2 Sync rules

- What syncs: cards, review logs, text progress, lookup history (capped), preferences. What doesn't: content DB (ships with the app), downloaded packs (re-downloaded per device), translation models and voices (system assets).
- SwiftData + CloudKit constraints: no `@Attribute(.unique)`; every property optional or defaulted; relationships optional; never rename, delete or retype a property after the schema is in Production (add new ones instead); lightweight migrations only; deploy the schema to Production in the CloudKit Dashboard before each release that changes it; private database only.
- `ReviewLog` is append-only and the source of truth. Card scheduling state is a cache: after remote changes, replay a card's logs in time order.
- Merge pass after each sync: dedupe cards on (`kind`, `lemmaID`, `senseID`, `formTag`, `grammarID`), keep the oldest, move logs from the removed duplicate.
- Keep sync behind a repository protocol so it can move to GRDB + `CKSyncEngine` if SwiftData limits bite.
- Test on real devices: same card reviewed offline on two devices; same item added offline on two devices; fresh install; signed out of iCloud.

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

1. Download kaikki Italian JSONL, Morph-it!, Tatoeba ita–eng pairs.
2. Normalise into SQLite: `lemma`, `sense`, `form`, `conjugation`, `sentence`, `grammar_topic`, plus FTS5 on headwords and glosses.
3. Validate: every Morph-it! verb form resolves to a lemma; common verbs match Wiktionary.
4. Stamp a content version; bundle read-only.

### 6.3 Text packs

- A pack is a versioned folder: `manifest.json` plus one JSON file per text. See `examples/pack-manifest.json` and `examples/text.json`.
- Every token is pre-linked at build time to `lemmaID` and `senseID` and carries its analysis (mood, tense, person, number, clitics) and any grammar-topic tags. This powers tap-for-help without guessing; it is not shown as highlighting.
- Each sentence has an English translation. Each text has questions pointing at their answering sentence.
- Authoring: Markdown with front matter → build tool tokenises, links lemmas, proposes analyses, flags unknowns → native speaker reviews → pack.
- Delivery: starter texts bundled; others as Apple-hosted asset packs (up to 200 packs, 200 GB per app; reviewed separately from builds). Packs stay on disk until `remove(assetPackWithID:)`. Forum reports show download failures on some iOS 26.4–26.6 devices, and several `AssetPackManager` methods were deprecated in 26.4 and 27.0. Bundle enough to never block the first session; add retry and "not downloaded" states. Don't use On-Demand Resources (deprecated in iOS 27).

### 6.4 Curriculum gaps to close

1. **Scope and sequence.** Define per level the grammar points and core vocabulary; tag each text with what it uses and introduces; order texts to add one or two points at a time and recycle earlier ones. Reference: *Profilo della lingua italiana* (Spinelli & Parizzi), CEFR levels A1 to B2.
2. **Vocabulary targets.** Write each text for ~95 to 98% known words at its level; make new words recur in later texts.
3. **Speaking and writing.** Currently out of scope by default. Options that fit: shadowing (optionally with on-device speech recognition), short writing prompts per text with optional on-device model feedback.
4. **A1 on-ramp.** Tiny first texts, fuller help, pronunciation basics (double consonants, c/g/sc before e/i, gli/gn, stress), survival phrases, numbers, time.
5. **Text variety and register.** Dialogues (two voices), messages, emails, signs, menus, articles; *tu* vs *Lei*. Narrative alone over-weights the passato remoto.
6. **Placement and progress.** Short placement (calibrated passages, mark unknown words); per-level progress (texts read, core words known, grammar points met).

Smaller: Phrase as a fourth Remember kind; full A1 to B2 grammar topic list; cultural notes.

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
- [ ] Minimum OS 26 or 27?
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
| SwiftData schema is add-only once live | Finalise the model before the first Production deploy |
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
