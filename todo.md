Figure out exactly how good local teacher model is -> write test corpus?

Small fixes [lesson]:
- remove grammatica da praticare - this should be handled automatically
- Lesson plan: duplicate <div class="lesson-overview">?
- refactor templates to use the same "card" with "next/submit" and "Salta" button.
  - "salta" should not be present in the grammar review.

Refactoring [analyzer]:
- the teacher prompt should be shared across activities, as should the response template.
  - there is sometimes duplication across grammar mistakes and tips
  - the activity feedback template should be largely shared
  - the tone of the feedback varies across activities: lo studente ha fatto qualcosa vs questa cosa e sbagliata.
  - mistakes should be corrected inline, as a teacher would cross out mistakes on paper and annotate the correct response, with a footnote refering to the grammar rule being broken, or clarification for some other mistake.
Bugs [analyzer]:
- fill in blank
  - LLM call has too much context (all grammarpoints?)
  - overlap between objective_note and tips.

Refactoring [grammar]:
- GrammarPoints are taken from the scraped grammar_points.json but should link back to the ItalianChunks full grammar rules.
- Activity feedback should always include a link to the grammar detail of the rule in question

Refactoring [planner]:
- Grammar overview should pull in ItalianChunk Rule, in addition to the concrete GrammarPoint
- more temperature in grammarpoint selection - if the student makes a mistake, revisit the topic after a few days, not immediately.
- more temperature in topics - I keep getting things about Rome and various villas. There's also duplication (twice covered Villa d'Este)


Fixes prompts [lesson]
---
here, the correct word IS bar 
10
I ___ vicino al Colosseo sono pieni di turisti. (cafés)
bar
caffè
Lo studente ha scritto 'bar' invece di 'caffè': il plurale richiesto per 'cafés' è 'caffè', che è invariabile al plurale.
---
