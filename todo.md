Small fixes [lesson]:
- Lesson plan: duplicate <div class="lesson-overview">? (lines 27 & 30 in lezione.html)
- "Salta" should not be present in the grammar review activity

Refactoring [analyzer]:
- Shared teacher prompt across activities (currently separate per-activity prompts in analyzer.yaml)
  - duplication across grammar mistakes and tips
  - tone varies: "lo studente ha fatto qualcosa" vs "questa cosa è sbagliata"
  - mistakes should be corrected inline with footnotes to grammar rules
- Fill-in-blank LLM call passes all 231 grammar points — trim to relevant ones
- Overlap between objective_note and tips — needs clearer schema boundaries

Refactoring [planner]:
- Spaced repetition in GP selection — add cooldown/decay, not just random noise
- Topic repetition — Phase 6 scenarios will replace this

Bugs [scoring]:
- Fill-in-blank doesn't handle multiple valid synonyms (e.g. "bar" and "caffè" both valid for "cafés")
