# 06 · Lesson types

The MVP has **17 learning types and 3 assessments**. In the code they map onto three layers:

- **Step kinds** — what a lesson is made of (`preview`, `story`, `note`, …).
- **Exercise formats** — atomic graded questions (`cloze`, `recall`, `choice`, …). They appear inside steps, in reviews and in checks.
- **Sessions** — review, placement and the final check, built at runtime.

"Try again" is not a type. It is the stepped feedback every graded format uses (`docs/05` § Stepped feedback).

| # | Lesson type (plan name) | Implemented as | Strand | Graded by | Design reference |
|---|---|---|---|---|---|
| 1 | Preview words | step `preview` (meet → `match` → `recall`/`choice`) | language focus | recall, accent-tolerant | — (new) |
| 2 | Story | step `story` + comprehension `choice` | input | not graded; glosses logged | `Main.png` (iPad; iPhone is one column) |
| 3 | Listening | step `listening` + `choice`/`true-false`/`match` | input | choice | — (new) |
| 4 | Real-world reading | step `reading` (native layouts) + questions | input | choice, matching | — (new) |
| 5 | Grammar note | step `note` | language focus | not graded | `Grammar.png` |
| 6 | Cloze | format `cloze` | language focus | accepted answers | `LibroPhone.png` |
| 7 | Recall (English → Italian) | format `recall` | language focus | accepted answers, accent-tolerant | `LibroPhone.png` (layout) |
| 8 | Sentence building | format `sentence-building` | language focus | order | — (new) |
| 9 | Dictation | format `dictation` | language focus | word-by-word | `Dictation.png` |
| 10 | Sound pairs | format `sound-pair` (step `sounds`) | language focus | choice | `Pairs.png` |
| 11 | Repeat after me | format `repeat` | fluency | transcript match | — (new) |
| 12 | Conversation | format `conversation` (unit task, `use` step, check) | output | intents + accepted answers | `Dialogue.png` |
| 13 | Talk about it | format `talk` | output | content points + model answer | — (new) |
| 14 | Guided writing | format `writing` | output | word count, content, taught forms; model | — (new) |
| 15 | Relay to a friend | format `relay` | output | short English answer | — (new) |
| 16 | Fluency replay | step `fluency` | fluency | not graded; time logged | `Main.png` (mode) |
| 17 | Review | review session | language focus, fluency | per format; FSRS | `LibroPhone.png`, `Complete.png` |
| 18 | Unit check | step `check` | assessment | auto + checklists | — (new) |
| 19 | Placement | onboarding session | assessment | adaptive blocks | — (new) |
| 20 | Final A1 check | final session | assessment | auto; examiner export | — (new) |

Other step kinds: `opener` (unit start: episode and can-dos, `Unit.png`), `use` (the lesson's closing mini-task: one short conversation or a spoken recall), `sounds` (holds sound-pair exercises), `practice` (a block, then a mix) and the task steps `conversation`, `talk`, `writing` and `relay` (one exercise each).

Which formats each container holds (the schemas in `schemas/` enforce it): story questions are `choice`; listening and reading steps hold `choice`, `true-false` and `match`; `sounds` holds `sound-pair`; `use` holds one `conversation` or `recall`; `practice` holds any format except `conversation`, `talk`, `writing` and `relay`; a task holds its conversations, talk, writing and relay; placement holds `cloze`, `recall`, `sentence-building`, `dictation`, `choice`, `true-false` and `match`; unit checks and the final check hold any format. Unit-level kinds (`opener`, `check`, …) are generated, never authored in a lesson.

Design references are in `design/screens/`. Their **sample text is placeholder** and predates the final syllabus (for example 8 units, *c'è*, *nel*); copy layout, never text.

## Shared lesson-player behaviour

- **Chrome:** a close button (X; Esc on Mac), a progress bar with `n / total` for exercise steps, and the step title (`Unit 2 · Grammar`). Closing saves nothing extra: the resume cursor is derived from attempts (`docs/05` § Replay), so reopening resumes at the next unanswered exercise.
- **Answer input:** a text field in Literata, placeholder "Type in Italian". The **accent keys** row (à è é ì ò ù) inserts at the caret. A **Say it** button shows when speech is available and enabled. The primary button is **Check** (Return on Mac and hardware keyboards), with **Show a hint** under it.
- **Feedback panel:** slides up from the bottom (`TryAgain.png`) with Moka (think pose) and a short headline ("Close. That's a real word."). Mismatched tokens are underlined in the answer, and the hint text follows. Buttons: **Show answer** and **Try again**, then **Continue** once finished. Success uses the success colour and no mascot unless a note is shown. All feedback text is announced to VoiceOver.
- **Audio:** every Italian prompt that has audio shows a speaker button. Lines without audio (dev packs before M5.1) show no button.
- **Mac and hardware keyboards:** Return = Check/Continue; **1–6** choose options (choice, true-false, the left column of match, sound pairs); **⌘L** = listen again; **⇧⌘H** = hint (⌘H is the system Hide); Esc = close. **Space** plays and pauses only when no text field has focus, so it never fights typing.
- **Mini-preview** (eligibility, `docs/05`): when a step needs an item the learner hasn't met (after placement or a content update), a sheet titled "Before we go on" shows a meet card per missing item (display form, audio, gloss) and **Continue**. It writes `introduced` with `via: catchup`. IDs: `minipreview.card.<n>`, `minipreview.continue`.
- **Review mode** (`ITA_REVIEW_MODE`, Review and Debug builds; `docs/04` § Content review loop): every unit and step unlocked, a jump menu and draft badges; a **Comment** button on every step and exercise, and long-press on story lines and word cards, opening a sheet pre-filled with the target ID, the quoted text and the file hash; **Answer key** (all accepted answers and near-misses of the current exercise); **This should be accepted** in the feedback panel after a rejected answer; **Send** and **Export** for the review file. IDs: `review.jump`, `review.comment`, `review.commentSheet`, `review.key`, `review.shouldAccept`, `review.send`, `review.export`.
- **Accessibility identifiers:** `player.close`, `player.progress`, `answer.field`, `answer.accent.<char>`, `answer.check`, `answer.hint`, `answer.sayIt`, `feedback.panel`, `feedback.showAnswer`, `feedback.tryAgain`, `feedback.continue`, plus the per-type IDs below. Every interactive element has one (CLAUDE.md rule 9).
- **Italian text for VoiceOver:** render Italian through one `ItalianText` view that sets `accessibilitySpeechLanguage = "it-IT"` on the attributed string (verify per tappable token on iOS 26 and macOS 26 in M3.2).
- **Seeded shuffles** (options, pairs, tiles, the practice mix) use SplitMix64 seeded with FNV-1a 64 of the exercise or step ID (`docs/05`), so every device shows the same order.

## Payloads

Each section below shows the **authoring YAML**. The compiled JSON payload in the pack has the same fields (camelCase: `prompt_en` → `promptEn`) plus:

- `expanded` arrays (pattern expansions with focus spans);
- resolved `audioId`s (or null when audio is missing in a dev pack);
- token arrays for every Italian string (surface, item ID, gloss).

**Step payloads** (in `steps.payload`) reference exercises and texts by ID; the exercises themselves are rows in `exercises`:

| Step kind | Payload |
|---|---|
| `preview` | `{batches: [{itemIds, exerciseIds}]}` (`exerciseIds` = the generated match, then one per item) |
| `story` | `{textId, questionIds}` |
| `listening` | `{textId, plays, exerciseIds}` (`plays`: null = unlimited) |
| `reading` | `{textId, exerciseIds}` |
| `note` | `{noteId}` (body in `grammar_notes`, points in `note_items`) |
| `practice` | `{block: [exerciseId], mix: [exerciseId]}` (the app shuffles `mix`, seeded by the step ID) |
| `sounds` | `{exerciseIds}` |
| `use` | `{exerciseId}` |
| unit-level kinds | see § Unit-level steps |

`fixtures/packs/mini-payloads.json` (from `make mini-pack`) holds every payload of the golden lesson, task and check; LearningCore's decode tests use it.

### Unit-level steps

The pipeline generates these from `unit.yaml`, `task.yaml` and `check.yaml`. Within a unit, `steps.ord` runs:

1. `uNN.step-opener` — kind `opener`, payload `{unitId}`.
2. The lessons' steps, lesson 1 to K, in file order.
3. `uNN.step-conversation-N` — kind `conversation`, one per task conversation in file order (N from 1), payload `{exerciseId}`.
4. `uNN.step-talk`, `uNN.step-writing`, `uNN.step-relay` — kinds `talk`, `writing`, `relay`, payload `{exerciseId}`; only those the unit has.
5. `uNN.step-check` — kind `check`, payload `{checkId, pass: {overall, sectionMin}, sections: [{id, titleEn, exerciseIds}]}`.
6. `uNN.step-fluency` — kind `fluency`, payload `{textIds, rate: 1.15}` (the unit's story texts).

Course order is `(units.ord, steps.ord)`; the register matrix's `switch_at` and the level gate's position *p* use it.

### Building-block formats: `choice`, `true-false`, `match`

These three are used inside many lesson types (story questions, listening, reading, previews, reviews and checks).

```yaml
- id: u02.l1.ex21
  format: choice
  targets: [{item: w:buono, skill: read}]    # none for comprehension questions (role: comprehension)
  tags: [sy:cefr.reading]
  prompt_it: "Mmm! Buono!"           # optional Italian shown above the question (tappable, it-IT speech)
  audio: {speaker: ch:marco}         # optional: voice prompt_it with this character's voice
  audio_text: null                   # optional inline text (lines…) played as audio and hidden until answered
  plays: null                        # optional cap on plays of the audio (checks use 2); null = unlimited
  source: null                       # optional text shown above: a text ID or an inline text, e.g. {text: u02.task.menu}
  question_en: "Marco tastes his croissant and says this. What does he mean?"
  options: ["It's delicious!", "It's expensive!", "It's small!"]   # 2–4; shuffled with a seed
  answer: 0                          # index in options as written
- {id: u02.check.03, format: true-false, tags: [...], source: {text: u02.task.menu}, statement_en: "…", answer: true}
- {id: u02.l1.ex20, format: match, targets: [...], pairs: [["un caffè", "a coffee"], ["oggi", "today"]]}   # 2–6 pairs
```

- Options and pairs are shown in a seeded shuffle. The answer index refers to the order as written.
- **Match:** `targets[i]` belongs to `pairs[i]`, and each pair is graded on its own; `content lint` fails if the lengths differ.
- **Choice:** `answer` must be an index into `options`; lint checks it.
- Options in Italian use `ItalianText`.
- IDs: `choice.option.<n>`, `tf.true`, `tf.false`, `match.left.<n>`, `match.right.<n>`.

---

### 1 · Preview words (step `preview`)

```yaml
- kind: preview
  id: u02.l1.step-preview
  batches: [[w:caffe, w:cappuccino, w:cornetto, w:spremuta, c:vorrei, c:quant-e], [w:ecco, w:oggi, w:buono, w:amico, c:cosa-prende]]
```

- For each batch (≤ 6 items):
  1. **Meet:** one card per item with the display form (Literata 34; nouns with the definite article, `docs/03`), audio played once automatically, part of speech · gloss, and the note.
  2. **Match:** one `match` exercise pairing the display form with the gloss (up to the first `;`), targets = each item with skill `read`.
  3. **Retrieve:** one `recall` per P item (English → Italian) and one `choice` per R item (Italian → English).
- **Generated content:**
  - The recall prompt is the gloss up to the first `;`. The answer follows `docs/05` § Review session builder (generated recall): `recall_answer` if set; for nouns the definite or indefinite article with the noun as focus, a bare noun is `correctWithNote`, a wrong article is `almost`; chunks without trailing `… ? !`.
  - The choice shows the display form with audio and three English options: the gloss and two distractors, taken first from the same batch, then from the same unit, with the same POS where possible.
  - IDs: `<stepId>.b<k>.match` and `<stepId>.b<k>.<itemId with ":" replaced by "-">` (`u02.l1.step-preview.b1.w-cornetto`).
- Introductions happen at step start (`docs/05`).
- **Accept when:** a batch can be completed with keyboard only; with VoiceOver only; and with speech for recall. Meet cards replay audio on tap. IDs: `preview.card`, `preview.next`.

### 2 · Story (step `story`)

```yaml
- kind: story
  id: u02.l1.step-story
  text: {id: u02.l1.story, kind: story, title: {it: …, en: …}, lines: [...]}
  questions:
    - {id: u02.l1.q1, format: choice, question_en: What does Marco order?, options: [A cappuccino and a croissant, A coffee and a croissant, A fresh orange juice], answer: 0}
```

- **Regular width (iPad, Mac):** two panes as in `Main.png`. On the left, the text in Literata 28/1.6, max ~32 em per line. On the right, the word panel: the tapped word in accent colour at 36, POS · gloss, the note, **Hear it**, and a list headed "New in this story".
- **Compact width (iPhone):** one column. Tapping a word opens a bottom sheet with the same content.
- **Audio bar:** play/pause, scrubber, time, speed (0.8× / 1×), and **Continue** (to questions).
- **Read-along:** while playing, the current token gets the accent-tint background. Tapping a line plays from that line.
- **New words** have a dotted accent underline. **Grammar targets are not highlighted** on the first read; the note does that (cohesion rule 3).
- Speaker labels (small caps, secondary) appear before dialogue lines when the speaker changes. `Aa` opens text size (`display.textScale`), speaker labels (on by default in Units 0–4) and English under each line (the "English under stories" setting, off by default).
- **Events:** `glossTapped`, `audioPlayed`; then 2–4 comprehension questions (`choice`, no FSRS) and `stepCompleted`.
- **Accept when:**
  - the highlight tracks audio to within 50 ms at 0.8× and 1×;
  - every word token is tappable and names and punctuation aren't;
  - VoiceOver reads each line in Italian with actions "Play line" and "Show English";
  - the layout passes at the largest Dynamic Type size.
- IDs: `story.text`, `story.token.<line>.<n>`, `story.play`, `story.speed`, `story.continue`, `story.wordPanel`, `story.textSize`.

### 3 · Listening (step `listening`)

```yaml
- kind: listening
  id: u02.l2.step-listening
  text: {id: u02.l2.phone, kind: phone, lines: [...]}
  plays: unlimited               # checks use 2
  exercises: [{id: u02.l2.ex20, format: true-false, statement_en: Sara orders two pizzas., answer: false, tags: [cd:order-food-drink]}]
```

- Audio first: a large play button, **Play slower**, and a play counter.
- The transcript stays hidden until every question is answered. Then **Show transcript** opens it with read-along and glosses.
- Kinds: `dialogue`, `phone`, `announcement`, `message` (voicemail). Announcements use the station voice with a light reverb, applied by the pipeline.
- **Accept when:** questions can be answered with no transcript; replay respects `plays`; the transcript appears only after answering.
- IDs: `listening.play`, `listening.slower`, `listening.count`, `listening.transcript`.

### 4 · Real-world reading (step `reading`)

```yaml
- kind: reading
  id: u02.l2.step-reading
  text:
    id: u02.l2.menu
    kind: real_world
    layout:
      type: menu
      title: Bar Aurora
      sections:
        - title: Caffetteria
          rows: [{name: caffè, price: "1,20"}, {name: cappuccino, price: "1,60"}]
      ignore: []                    # decorative strings exempt from annotation (shown without glosses)
  exercises: [...]
```

- Layouts are drawn natively from structured data, never as images, so every word can be tapped for English and read by VoiceOver. Implement one SwiftUI view per layout type, all sharing card styling. Every string is Italian (annotated and tappable) unless listed in `ignore`; digits are allowed because layouts aren't voiced.
- Layout shapes (all used by the unit specs):

| `type` | Fields |
|---|---|
| `menu` | `title`, `sections: [{title, rows: [{name, price, note?}]}]` |
| `receipt` | `shop`, `rows: [{name, qty?, price}]`, `total`, `footer?` (e.g. *Grazie e arrivederci*) |
| `sign` | `lines: [text]`, `style: info \| warning \| closed` |
| `hours` | `title`, `rows: [{days, times}]` (`lun–ven`, `9:00–13:00, 15:30–19:30`), `note?` |
| `timetable` | `title`, `columns: [text]`, `rows: [[text]]` (e.g. *Treno, Destinazione, Partenza, Binario*) |
| `ticket` | `title`, `fields: [{label, value}]` |
| `form` | `title`, `fields: [{label, value}]` (a filled-in form to read; forms to fill are `writing`) |
| `label` | `title`, `fields: [{label, value}]` (a product label) |
| `ad` | `title`, `body: [text]`, `contact?` |
| `message` | `from`, `time?`, `bubbles: [text]` (a phone message thread) |
| `postcard` | `greeting`, `body: [text]`, `closing`, `signature`, `address?: [text]` |
| `list` | `title?`, `items: [text]` (a shopping or to-do list) |

- Up to 10% unknown tokens are allowed here (`content/checker.yaml`).
- **Accept when:** every layout type renders on iPhone, iPad and Mac (snapshot tests at compact and regular widths and at the largest Dynamic Type size), and tap-to-gloss works in every field.
- IDs: `reading.layout`, `reading.field.<n>`.

### 5 · Grammar note (step `note`)

```yaml
- kind: note
  id: u02.l1.step-note
  note_id: u02.l1.note
  grammar: [g:indefinite-article, g:noun-gender]     # one or more points; the first is the main one
  title_en: un, una and un'
  intro: {mascot: think, text_en: "Did you spot it? Marco orders *un cappuccino*, but Sara asks for *una spremuta*."}
  body:
    - {p: Every Italian noun is masculine or feminine. *Un* and *una* both mean "a"; the noun decides which one you use.}
    - table: {columns: [Masculine, Feminine], rows: [["**un** caffè", "**una** spremuta"], ["**un** cornetto", "**un'**amica"]]}
    - examples: [u02.l1.story#3, u02.l1.story#16]      # story lines (1-based), re-shown with the target forms highlighted
    - tip: Most nouns ending in -o are masculine and most ending in -a are feminine. Learn *caffè* with its article.
```

- The note follows `Grammar.png`: the mascot line, the title, the body, side-by-side table cards (stacked on compact width), a tip box on the subtle background, and **Try it** to start practice.
- Inline `*…*` marks Italian (Literata, italic, `it-IT` speech) and `**…**` marks the highlighted form (accent colour, semibold).
- At least two `examples` must be lines from the lesson's own story (checker).
- **Accept when:** examples highlight only the target forms, and the table remains readable at the largest Dynamic Type size.
- IDs: `note.table`, `note.example.<n>`, `note.tryIt`.

### 6 · Cloze (format `cloze`)

```yaml
- id: u02.l1.ex01
  format: cloze
  targets: [{item: g:indefinite-article, skill: recall}]
  tags: [cd:order-food-drink]
  source: u02.l1.story#3
  text: "Vorrei [[un]] cappuccino, per favore."
  prompt_en: I'd like a cappuccino, please.
  bank: null                    # optional word bank: tap instead of typing (early units, R items)
  hint: Cappuccino is masculine.
  rule: un with most masculine nouns, una with feminine nouns (un' before a vowel).
  near: [{answer: una, hint: Una is for feminine nouns. Is cappuccino masculine or feminine?}]
```

- One gap per exercise in the MVP (a gap may span several words).
- The UI follows `LibroPhone.png`.
- IDs: `cloze.sentence`, `cloze.gap`.

### 7 · Recall, English → Italian (format `recall`)

```yaml
- id: u02.l1.ex07
  format: recall
  targets: [{item: c:quant-e, skill: recall}]
  tags: [cd:ask-price-pay]
  prompt_en: How much is it?
  context_it: null              # optional line shown before the prompt (who you're talking to)
  answer: "{quant'è|quanto è|quanto costa|scusi quant'è|scusi quanto costa}"
  audio_after: true             # play the model answer after feedback
```

- The prompt is shown in Literata italic, with the same input as cloze.
- Answering with **Say it** grades the transcript (`docs/05`) and records the target under skill `speak` (`mode: spoken`).
- IDs: `recall.prompt`.

### 8 · Sentence building (format `sentence-building`)

```yaml
- id: u02.l1.ex10
  format: sentence-building
  targets: [{item: w:oggi, skill: recall}]
  tags: [cd:order-food-drink]
  prompt_en: Today I'd like a coffee.
  tiles: [oggi, vorrei, un, caffè]
  distractors: [una]
  answer: ["oggi vorrei un caffè", "vorrei un caffè oggi"]
```

- Every accepted `answer` orders exactly the `tiles` (lowercase, no punctuation; `distractors` are left out); lint checks it.
- Tiles appear in a seeded shuffled order, never in the answer order.
- Tap a tile to move it to the answer line, and tap it again to return it; drag to reorder on iPad and Mac. Tiles are buttons with "Move left" and "Move right" accessibility actions.
- Punctuation and capitals are added in the displayed result.
- IDs: `build.tile.<n>`, `build.answer`.

### 9 · Dictation (format `dictation`)

```yaml
- id: u02.l1.ex13
  format: dictation
  targets: [{item: w:cornetto, skill: listen}]
  tags: [sy:cefr.orthographic-control]
  say: Vorrei un cornetto, per favore.
  slow: true                    # offer Play slower (0.75×)
  plays: null                   # optional cap on plays (checks use 2)
```

- The UI follows `Dictation.png`: a big play button, **Play slower** (0.75×), a hint line ("5 words · from the story"), an answer area and accent keys.
- After Check, a word-by-word diff marks each word correct, accent, doubling, typo or wrong.
- IDs: `dictation.play`, `dictation.slower`.

### 10 · Sound pairs (format `sound-pair`, step `sounds`)

```yaml
- id: u02.l1.ex22
  format: sound-pair
  targets: [{item: s:double-consonants, skill: listen}]
  tags: [sy:ss.double-consonants]
  pair: [eco, ecco]
  play: ecco
  glosses: {eco: echo, ecco: here is}
  question: which-word           # which-word | single-or-double (then: word: caffè, answer: double)
  tip_en: Listen for the double c. Italians hold it a little longer.
```

- The UI follows `Pairs.png`. Audio for both words must exist; the pipeline generates it. `play` is one of the two words of `pair`, and `glosses` names only those words.
- `single-or-double` uses `word` and `answer: single | double`: it plays one word from the story and asks "Single or double consonant?" Vary the answers within a step, so always picking one button doesn't pass.
- IDs: `pairs.play`, `pairs.option.<n>`.

### 11 · Repeat after me (format `repeat`)

```yaml
- id: u02.l1.ex14
  format: repeat
  targets: [{item: c:vorrei, skill: speak}]
  tags: [sy:cefr.phonological-control]
  say: Vorrei un cappuccino, per favore.
```

- The flow:
  1. The model audio plays.
  2. The learner taps the mic and speaks. Recording auto-stops after 1.2 s of silence; the limit is 10 s.
  3. A live transcript shows while they speak.
  4. The result shows "I heard: …", with **Try again**, **Hear it again** and **Skip — can't speak now** (outcome `skipped`).
- Playing back their own recording is P1.
- Without speech recognition, the screen becomes listen-and-repeat (ungraded) with Continue.
- IDs: `repeat.mic`, `repeat.transcript`, `repeat.skip`.

### 12 · Conversation (format `conversation`)

```yaml
- id: u02.task.conv1
  format: conversation
  with: ch:giulia
  register: lei                      # default for every node; a node may override it
  title: {en: Order breakfast from Giulia}
  tags: [cd:order-food-drink, cd:ask-price-pay]
  goals: [{id: drink, en: Order a cappuccino}, {id: food, en: "Order something to eat, or say no thanks"}, {id: price, en: Ask how much it is}]
  start: n1
  nodes:
    n1:
      say: Buongiorno! Cosa prende?
      en: Good morning! What will you have?
      expect:
        - {intent: order-drink, goal: drink, next: n2,
           accept: ["(buongiorno )(vorrei )un cappuccino( per favore)", "(buongiorno )(vorrei )un cappuccino grazie"]}
      help: [Vorrei un cappuccino, per favore.]
      hint_en: Order a cappuccino.
    n2:
      say: "Certo. E da mangiare?"
      en: "Of course. Anything to eat?"
      expect:
        - {intent: order-food, goal: food, accept: ["(vorrei )un cornetto( per favore)"], next: n3}
        - {intent: nothing-to-eat, goal: food, accept: ["no grazie"], next: n3b}     # branches may end differently
      help: [Un cornetto, per favore., No, grazie.]
    end: {say: "Tre euro, grazie. Buona giornata!", en: "Three euros, thanks. Have a good day!", final: true}
```

- **Nodes:** `say` and `en` (the character's line), `expect` (intents, each with a `goal`, `accept` patterns and `next`), optional `near` (register slips and common errors, with a hint; see `u02.l1.ex25` node n3), `help` (phrases offered as chips), `hint_en`, optional `register` (overrides the conversation's register from this node on: the node where someone offers tu), and `final: true` on end nodes. A conversation may have several final nodes (different prices for different orders), and needs at least one. Final nodes have no `expect` or `help`; every other node has `expect`. Lint checks that `start` and every `next` name a node and every `goal` is one of `goals` (and warns about a goal no intent completes).
- **Layout:** follows `Dialogue.png`. The character's name is in small caps over their line; the learner's turns are labelled **YOU** in the accent colour. On regular width, the goals checklist and "Stuck? You could say:" help chips sit in the right column. Bottom bar: **Type instead**, the mic (primary), **Hear Giulia again**. **Show English** toggles translations. On iPhone the goals collapse above the transcript.
- **Turn matching:** typed turns use the typed grader (accepted if `correct`, `correctWithNote` or `almost`); spoken turns use the transcript matcher.
- **First miss:** show the matching `near` hint, else `hint_en`, and the help chips. **Second miss:** "You could say: …" — the learner repeats or types it, or taps Continue — and the conversation follows the first intent's `next`.
- **Modes:** in practice, typing is allowed. In the unit check, speech is required when available, typing is hidden and the section is excluded on devices without speech.
- **Events:** one `attempt` per turn (`exerciseId` + `turnId`), with no targets and no FSRS update; check score = goals completed.
- IDs: `conv.line.<n>`, `conv.mic`, `conv.type`, `conv.replay`, `conv.english`, `conv.goal.<id>`, `conv.help.<n>`.

### 13 · Talk about it (format `talk`)

```yaml
- id: u02.task.talk
  format: talk
  tags: [cd:order-food-drink, cd:ask-price-pay]
  prompt_en: You're at Bar Aurora. Greet Giulia, order something for you and a friend, and ask the price.
  points:
    - {id: greet, en: Greet Giulia, accept: ["{buongiorno|buonasera}"]}
    - {id: order, en: Order two things, accept: ["{un {caffè|cappuccino|cornetto}|una spremuta} e {un {caffè|cappuccino|cornetto}|una spremuta}"]}
    - {id: price, en: Ask the price, accept: ["{quant'è|quanto è|quanto costa}"]}
  pass: 2
  model: Buongiorno! Vorrei un cappuccino e una spremuta, per favore. Quant'è?
  duration_s: {min: 5, max: 60}
```

- Show the points as a checklist before recording (scaffolding).
- After recording, show the transcript, the points found (ticks), the model answer with audio, and **Try again**.
- Typing is allowed in practice when speech is unavailable. No FSRS. The transcript is stored in the attempt's `response` (≤ 2,000 characters; never uploaded in telemetry).
- IDs: `talk.mic`, `talk.type`, `talk.point.<id>`, `talk.model`, `talk.tryAgain`.

### 14 · Guided writing (format `writing`)

```yaml
- id: u01.task.write
  format: writing
  kind: form                    # form | message | postcard | list | description
  tags: [cd:give-personal-details, sy:fn.forms]
  prompt_en: Fill in the registration form at the language school.
  fields:
    - {label_it: Nome, label_en: First name, type: text}
    - {label_it: Nazionalità, label_en: Nationality, type: text, accept: ["{ME.nationality}"]}
    - {label_it: Indirizzo email, label_en: Email, type: email}
  model: null
```

```yaml
- id: u12.task.write
  format: writing
  kind: postcard
  prompt_en: Write a postcard to a friend at home about your stay in Bologna.
  words: {min: 25, max: 50}
  points: [{id: opening, en: Open the postcard, accept: ["{caro|cara} {NAME}"]}, …]
  pass: 3
  model: "Caro Tom, …"
```

- `kind: form` needs `fields`; every other kind is free text and needs `words`, `points`, `pass` (at most the number of points) and `model`.
- **Forms** render as an Italian form with per-field checks.
- **Free text** gets a word counter, the checklist and accent keys.
- **Feedback** shows the word count, the points found, spelling suggestions for unknown forms close to known ones, and the model answer.
- The text is stored in the attempt's `response` (≤ 2,000 characters; synced, never uploaded in telemetry).
- The optional on-device LLM hint (`WritingHintProviding`) is behind `ITA_LLM_HINTS` and off in study builds. No FSRS.
- IDs: `writing.field.<n>`, `writing.text`, `writing.count`, `writing.point.<id>`.

### 15 · Relay to a friend (format `relay`)

```yaml
- id: u02.task.relay
  format: relay
  tags: [cd:pass-on-prices, sy:cefr.mediation]
  source: {text: u02.task.menu}          # a text ID, an inline text (as in task.yaml), or {audio_text: {...}} for something heard
  friend_en: "I'm waiting outside. How much is a cappuccino in there?"
  answer_en: {type: price, value: 1.60}
```

- A friend's message bubble (in English) sits above the Italian source; the learner answers in English.
- Answer types: `time` (`value: "15:30"`), `price` and `number` (a numeric `value`), `text` (`accept: [...]`). No FSRS.
- IDs: `relay.friend`, `relay.source`, `relay.answer`.

### 16 · Fluency replay (step `fluency`)

- Generated after the unit check (`uNN.step-fluency`): the unit's stories at 1.15× (a 1.25× option).
- Continuous read-along; glosses can still be tapped (logged).
- A listened-time counter. Not graded, optional, and never blocks progress.
- IDs: `fluency.play`, `fluency.speed`, `fluency.done`.

### 17 · Review (session)

- Built by the planner (`docs/05`). Each card uses its exercise's view inside the player chrome (`LibroPhone.png`: `12 / 20` and close).
- At the end, `Complete.png`: **Bravo!**, remembered x of y, new words met, "To practise again" (the Again items), next review, the weekly dots, **Done** and **Read the next story**.
- IDs: `review.start`, `complete.done`, `complete.next`.

### 18 · Unit check (step `check`)

```yaml
# units/02-al-bar/check.yaml
id: u02.check
review: {status: draft}
pass: {overall: 0.70, section_min: 0.50}
sections:
  - {id: listening, title_en: Listening, exercises: [...]}
  - {id: reading, title_en: Reading, exercises: [...]}     # incl. relay items
  - {id: writing, title_en: Writing, exercises: [...]}     # structures (cloze, sentence building) + one short writing task
  - {id: speaking, title_en: Speaking, exercises: [...]}   # conversation (speech) + talk
```

- **Check mode:** one attempt per item, no hints, no feedback until the end; listening plays twice. Each item has a `score` (default 1); the file sets `pass: {overall, section_min}`; listening items carry their audio in `audio_text`.
- **Intro screen:** sections, about 15–20 minutes, and "No hints in the check — just do your best".
- **Result screen:** overall and per-section scores, can-dos reached (ticks), "Review your mistakes" (each wrong item with the answer and rule), **Continue to Unit N+1**, and "Retake tomorrow" if failed. Scoring is in `docs/05`.
- About 18–20 items, covering every can-do of the unit and all four skills.
- IDs: `check.start`, `check.section.<id>`, `check.result`, `check.mistakes`, `check.continue`, `check.retake`.

### 19 · Placement (session)

- Onboarding asks "Have you studied Italian before?" On yes, it runs the adaptive blocks (`docs/05`) with one attempt per item, no feedback and a progress bar. Blocks come from the pack's `assessments` table (`placement`).
- **Result:** "We'll start you at Unit N: *title*", with **Start there** and **Start from the beginning** (`docs/05` § Placement says which events each writes).
- IDs: `placement.start`, `placement.startThere`, `placement.fromBeginning`.

### 20 · Final A1 check (session)

- Five sections modelled on CILS A1 (listening, reading, structures, writing, speaking), 12 points each, with check-mode rules. Sections come from `assessments` (`final`).
- Speaking items always record to m4a (`docs/09`), whatever the recording setting.
- **Result:** per-section score with an indicative pass of ≥ 7/12 each, and the line "This is a practice check, not an official certificate."
- **Export for examiner:** builds `final-check-<installId>-<date>.zip` (`responses.json`, `writing/*.txt`, `speaking/*.m4a`, `README.txt`; contents in `docs/12`) and opens the share sheet. Nothing uploads automatically.
- IDs: `final.start`, `final.result`, `final.export`.

## Opener and Use

- **Opener** (`Unit.png`, `uNN.step-opener`): unit number, Italian title and English subtitle, "By the end you can" can-dos (ticked when reached), and the list of lessons, notes and tasks with their state. The primary button is **Continue with …**. IDs: `opener.continue`, `opener.cando.<n>`, `opener.step.<n>`.
- **Use** closes each lesson with one tiny task in the story's situation: a 2–3-turn `conversation` or a spoken `recall`.
