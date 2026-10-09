# The content rules (from the MVP plan, in brief)

## Twelve rules for what goes in and when

1. **Cover every syllabus; let can-dos win.** Where CILS, CELI, the joint syllabus and PLIDA disagree, teach the more demanding version. Where a unit's can-dos need more (articulated prepositions, ordinals), the can-do wins. Decisions live in `content/syllabus/a1-syllabus.yaml`.
2. **Natural order of verb forms.**
   - Present first.
   - Passato prossimo with avere from Unit 9 and essere verbs from Unit 11, consolidated in Unit 12.
   - *sono nato/a* and *sono arrivato/a* as chunks from Unit 1.
   - No imperfetto, future, conditional or subjunctive except the chunks *era, c'era, vorrei, potrei*.
3. **Agreement in stages.** Nouns are shown with their article from Unit 0, and an article directly before a noun item, or before an adjective and a noun item, is part of that noun until the article's own unit (*un/una*: Unit 2; *il/la/lo…*: Unit 3) (the lexical-article rule in docs/04). Adjective agreement in the noun phrase from Unit 3. Agreement after *essere* starts as a personal chunk in Unit 1; it and participle agreement are graded as *developing*.
4. **Singular persons first.** io, tu, lui/lei and Lei first; *sono*, *hanno* and *si chiamano* (they) in Unit 3; noi in Unit 4; voi in Unit 6; loro in Unit 7.
5. **Chunks first, rules later.** About 25 set phrases in Units 0–2; later units vary their parts. Using a chunk never counts as knowing the rule.
6. **Object pronouns mostly for recognition.**
   - Produce: *c'è/ci sono*, *mi chiamo/ti chiami/si chiama*, *mi/ti/Le piace*, and singular reflexives.
   - Recognise: *lo/la/li/le*, *gli/le* and *ne*.
7. **Explicit notes on English speakers' traps:**
   - *piacere*;
   - the article in general statements (*mi piace il caffè*);
   - possessives with and without the article (*mia madre*, *la mia famiglia*);
   - *suo/sua* agreeing with the thing owned;
   - formal *Suo*;
   - *essere* vs *avere*;
   - *-e* nouns and exceptions (*la mano*, *il problema*);
   - tu vs Lei, including adjectives after Lei and imperatives (*gira/giri*).
8. **Register from Unit 1.** tu with peers, Lei in shops and services; *scusi* and *senta* as chunks. Learners also meet an older person saying tu while they answer with Lei.
9. **Grade what learners are ready for.** Controlled exercises grade taught forms. In free production, agreement after *essere* and subject–verb agreement are *developing*, and communicative tasks pass on intelligibility. Accept *Dove tu abiti?* without inversion.
10. **Words by need, then frequency.** Topics come from the syllabi; within a topic, the most frequent words first (`content suggest`). Nouns always with their article. Transparent cognates may stay untaught; false friends are taught (*parenti*, *simpatico*, *libreria*, *camera*).
11. **Hear double consonants from week 1.** Sound pairs from Unit 0 (*pena/penna*, *caro/carro*, *sete/sette*, *capello/cappello*). Hearing is tested; saying is practised but not machine-checked.
12. **The learner's own gender.** Onboarding asks which forms fit (*americano/americana*, *sono nato/nata*); answers accept both unless the learner chooses strict forms.

Also:

- **Later forms may appear in stories**, glossed and marked for recognition (the R status).
- **Stretch can-dos** (invitations, plans, tickets, past activities: A1 in the Italian syllabi, A2 in the CEFR) are taught, labelled `stretch`, and pass on intelligibility.
- **Standard Italian with neutral voices.** Open and closed e/o and s/z voicing are heard, never graded.

## Ten cohesion rules

1. **Build backward from the task.** The unit check and the unit-end conversation define the unit. Every exercise is tagged to a can-do or syllabus item, and practice matches how the goal is tested.
2. **One scene per lesson.** Practice uses the lesson's own story sentences first, then recombines them.
3. **Meaning first, form after.** Preview, then read and listen, then the note built from the story. Highlight grammar only on a second pass.
4. **Pairs, then context.** New words start as Italian–English pairs with retrieval, then appear in the story. Other words get English on tap. Stories always come with audio.
5. **Ten encounters per word.** About five retrievals in the introducing lesson, then reviews and reuse in later stories: at least ten meaningful encounters in all.
6. **Block, then mix.** A short block on a new structure, then mixed with confusable earlier ones. Errors in mixed practice are not penalised in the UI.
7. **Balance the four strands** (input, output, language focus, fluency) per unit within `checker.yaml`'s bands: input and output 15–35%, fluency 10–35%, language focus at most 60% in Units 0–2 and 50% from Unit 3 (CL21).
8. **Stepped feedback.** First error: point, hint and retry. Second: the answer and a one-line rule.
9. **Spiral.** At least 30% of each unit's content words come from earlier units, and every grammar point returns in at least two later units (or the final review).
10. **Keep the plot thin.** The story recycles language; no decorative subplots.
