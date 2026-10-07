# Style guide for Italian content

## Language

- **Standard, neutral Italian** as spoken by educated people in northern and central Italy. No dialect words. Bologna culture (portici, tortellini, the market) is welcome as content, not as dialect.
- **Short sentences:** ≤ 12 words in Units 0–4, ≤ 18 later. One idea per sentence. Dialogue sounds like speech: short turns, real fillers (*allora*, *dunque*) only once taught.
- **No irony, puns or idioms** unless an idiom is itself the item being taught.
- **Topics to avoid:** politics, religion, health scares, drinking as a theme, brand names, real living people, stereotypes.

## Register and forms

- **Formal you:** capitalised `Lei`, `La`, `Le`, `Suo`. Follow the story bible's matrix for every line with an addressee.
- Use *scusi* and *senta* (Lei) or *scusa* and *senti* (tu) to get attention.
- *Signora Rossi* says tu to Marco and to you; you both answer with Lei.

## Spelling and typography

- **Accents:**
  - Grave: à è ì ò ù.
  - Acute: é in *perché, né, sé, poiché, affinché, ventitré*.
  - *è* (is) vs *e* (and); *sì* (yes) vs *si*; *là, lì, più, può, già, città, caffè, tè*.
- **Apostrophes:**
  - *po'* (not *pò*); *qual è* (no apostrophe); *un'amica* but *un amico*; *l'amico, dell'acqua, c'è, dov'è, quant'è*.
  - Source files use the straight apostrophe `'`; the normaliser accepts typographic ones.
- **Quotes:** straight double quotes in source; the app renders « » for Italian.
- **Voiced text:**
  - Numbers in words: *sei euro e venti*, *alle otto*, *il tre ottobre*, *nel millenovecentonovanta*.
  - 24-hour times only from Unit 11 (*alle quindici e trenta*).
  - Real-world layouts may use digits (*1,60 €*, *9:00–13:00*).
- **Capitals:** days and months are lowercase (*lunedì*, *maggio*); nationalities lowercase (*canadese*); languages lowercase (*l'italiano*).

## English (learner-facing)

- American spelling (Q13): color, favorite, practice.
- **Glosses:** the sense in context, short; no article for nouns (*croissant*); `to` + verb (*to take*); add "(formal)" or "(informal)" where register matters.
- **Translations:** natural, not word-for-word; keep the speaker's tone. Prices with cents as figures (*Sei euro e venti* → "€6.20."); round amounts may be words (*Tre euro* → "Three euros").
- **One rendering per item:** use the same English for an item everywhere (*spremuta* is always "a fresh orange juice" in prompts and options).
- **Prompts:** say what to do in one sentence. Never reveal the answer in the prompt.

## Answers

- **The model answer** (first expansion) is short, natural and uses only what has been taught for production.
- **Accept** every correct variant a learner at this point might produce:
  - with or without *per favore* or *grazie*;
  - *vorrei* or *prendo* once both are taught;
  - both word orders where Italian allows it;
  - the learner's own gender forms.
  The beta adds the ones you missed.
- **Near-misses** (`near`) target the likely errors with a specific hint: wrong gender, missing accent on *è*, tu instead of Lei, the infinitive instead of the conjugated form.
