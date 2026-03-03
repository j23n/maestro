Figure out exactly how good local teacher model is -> write test corpus?


Small fixes:
- in the lesson review page: The feedback contains the "# Feedback" string from the LLM output.
- dict parse: il mare POS is split into "s" and "sense 1: m"
- dict parse: la mattina POS is split into "s" and "example of sense 1"
- grammar overview: "why this matters" should be in the language of the grammarpoint (english in A1, IT/EN later)
- vocab discover on lesson contents missing (at least in lettura, no words are highlighted, also in the error correction prompts). discover should take into account whether a word has been learned or not. 
- need UX feedback when sutmitting drills. (missing in reading comprehension). Should disable button like in lesson planning.
- no feedback give on reading comprehension.
- remove preferences from profile, pre-fill topics in the lesson planner based on CEFR, but allow student to change it.
- "salta" in lesson should be part of the card, right aligned on the same line as "submit"
- feedback on free form -> surface any errors encounted. This should be the same across all drills. Anywhere the student enters text freely, any error made should be surface in the feedback, even if the drill itself is graded as correct.
- keep track of the lessons' contents - there should not be two lessons that both cover "roma antica was founded in 753 AD" etc.
- there are grammar mistakes in the lesson reading. e.g. "e loro strade sono dritte e veloci". prompt engineering and eval to make sure the language is correct.
- reading comprehension: feedback is doubled on wrong answer:
        <div class="item-row-body">
          <div class="item-prompt-text">Roma è fondata nell'___ a.C. (753). Scrivi il numero in lettere: ___</div>
          
            <div class="item-student-wrong">settacento cinquanta tre</div>
            <div class="item-correct-answer">settecentocinquantatré</div>
            
            <div class="item-explanation">Il numero 753 si scrive 'settecentocinquantatré', non 'settacento cinquanta tre' (deve essere scritto come una parola unica e la forma corretta è 'sette-' non 'setta-').</div>
            
          
          
          <div class="item-secondary">
            
            
            <div class="item-tip">settecentocinquantatré, non 'settacento cinquanta tre' — i numeri composti si scrivono uniti e la radice è 'sette-' non 'setta-'</div>
            
          </div>
          
        </div>


Features:
- conversation TTS STT
