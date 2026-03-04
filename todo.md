Figure out exactly how good local teacher model is -> write test corpus?


Small fixes [lesson]:
- "salta" in lesson should be part of the card, right aligned on the same line as "submit"
- lessons should cover multiple grammar points because they are now so specific. Perhaps we can link multiple grammar points to ItalianChunk in our RAG and have a single lesson cover one ItalianChunk? TO EXPLORE
- remove grammatica da praticare - this should be handled automatically
- Lesson plan: duplicate <div class="lesson-overview">?
- Lesson plan: materializing 0 drills (0 returned by LLM)

Small fixes [dict]:
- "molto": POS bleeds into sense "." and example "indef"
- "momento": POS bleeds into sense "" and example "m"


Features:
- conversation TTS STT


Fixes prompts [lesson]
---
here, the correct word IS bar 
10
I ___ vicino al Colosseo sono pieni di turisti. (cafés)
bar
caffè
Lo studente ha scritto 'bar' invece di 'caffè': il plurale richiesto per 'cafés' è 'caffè', che è invariabile al plurale.
---
