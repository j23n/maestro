# 06 — Pedagogy: where the curriculum model comes from

Status: reference
Scope: what the spec's concepts (can-dos, grammar points, communicative
functions, scenarios, themes, vocab) are, where each derives from, how
they interlock at authoring time and at runtime, and how this compares
to the way CEFR-grounded courses are constructed in the field.

---

## 1. Where the app's inventories actually come from

**Grammar points and communicative functions come from the official
Italian Reference Level Description.** All 351 grammar points carry a
`source.descriptor_code` and a `source_url` into the *Profilo della
lingua italiana* website (Università per Stranieri di Perugia), plus a
`chunk_ref` into a reference grammar. The 465 functions are
Italian-labeled speech acts in seven macro-categories (e.g.
`interagire_opinioni_atteggiamenti` → "Esprimere un disaccordo rispetto
ad un'asserzione negativa") — the Profilo's *funzioni* inventory
structure. Both were converted from the legacy `data/it/` with IDs
preserved; `spec/it/CONVERSION.md` is the permanent record.

**The can-dos are original text written against two checklists.** The
header of `spec/it/can_do.yaml` states it: descriptor wording is
original; the *CEFR Companion Volume* (2020) and the *Profilo* were
used "as completeness checklists only" — deliberate, because the RLD
texts are copyrighted (architecture doc §2). There are 68 descriptors
across A0–A2, each tagged with one of the CEFR's five communication
modes (listening, reading, spoken interaction, spoken production,
writing — spoken interaction dominates at 38/68, faithful to how
A-level CEFR content skews) and each *decomposed* into `function_ids`,
`grammar_ids`, `scenario_ids`, and `vocab_domains`.

**"A0" is this app's name for the CEFR's Pre-A1.** The Companion
Volume formalizes Pre-A1 as "a milestone halfway to A1" — rehearsed,
formulaic language on very familiar ground. Maestro's A0 is that plus a
product decision: a linearly sequenced 13-scenario crash course (plane
→ hotel → bar → …) before phase-gated A1 material begins. Official
Pre-A1 descriptors exist for only a subset of CV scales, so an
app-defined A0 band is normal practice.

## 2. How the five concepts fit together

**Can-dos are the roof, functions are the pivot, grammar is the raw
material, scenarios are the packaging, vocab is the constraint.**

- **Can-do** — the learner-facing unit of progress ("Can order a meal
  and ask about dishes"). CEFR descriptors are deliberately
  language-neutral, so a can-do cannot be taught directly; it is
  *decomposed* into the Italian-specific inventories below it.
- **Communicative function** — a speech act ("politely request"). In
  the notional-functional tradition each function comes with
  *exponents* — the phrases that realize it — which is exactly what
  `CommunicativeFunction.patterns`/`examples` hold.
- **Grammar point** — the forms those exponents are made of, with CEFR
  level and a prerequisite DAG that drives unlocking.
- **Scenario** — situational packaging with narrative ("Al bar", depth
  1→3, recurring characters), bundling the grammar and functions it
  exercises; the session composer's first pick.
- **Theme** — two distinct things: the `theme` field on can-dos is a
  display grouping (≈ CEFR "domains": social, services, travel…); the
  `generate --theme` scope is an authoring device that drafts content
  against a free topic (e.g. Ferragosto) while pinning evidence to the
  existing grammar/function inventories.
- **Vocab** — the leveled lemma list is both SRS material (vocab
  cards) and a *constraint* the quality validator enforces (any word
  above level must be glossed).

At **runtime**, the hierarchy is operationalized through evidence:
every item carries evidence refs on the grammar / function / vocab /
cando axes; folds turn the event log into decayed grammar mastery,
function demonstration counts (≥3 correct productive uses), SM-2 vocab
state, and scenario depth. A can-do is *achieved* when ≥80% of its
grammar is mastered AND ≥80% of its functions are demonstrated AND at
least one `cando`-tagged application item was answered correctly
(decisions #10–12); the CEFR estimate is the highest level with ≥90%
of grammar and functions cleared. The same decomposition that scopes
authoring also measures progress — that closed loop is the app's
distinctive move.

## 3. How CEFR courses are constructed in the field

The standard stack, which `spec/it/` reproduces:

1. **CEFR / Companion Volume (language-neutral).** The can-do
   descriptors originate in a Swiss National Science Foundation project
   (1993–96) that Rasch-scaled ~2,000 teacher-judged descriptors into
   the A1–C2 scales; the 2020 Companion Volume extends them (~84
   scales, adding mediation, online interaction, and Pre-A1). They
   describe *what a learner can do*, never *which forms of a language*
   — so the CEFR alone cannot generate an Italian syllabus.
   - CEFR descriptors: <https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-descriptors>
   - Companion Volume 2020: <https://rm.coe.int/common-european-framework-of-reference-for-languages-learning-teaching/16809ea0d4>
   - Pre-A1 analysis: Alexiou & Stathopoulou 2021, <https://rpltl.eap.gr/images/2021/11-01-011-Alexiou-Stathopoulou.pdf>
2. **Reference Level Descriptions (language-specific).** The Council of
   Europe programme that bridges the gap: per-language inventories of
   functions (with exponents), notions, grammar, and frequency-based
   lexicon per level. For Italian: **Profilo della lingua italiana**
   (Spinelli & Parizzi, 2010; A1–B2), built by triangulating expert
   panels, CELI exam-candidate productions, and frequency lists.
   Family: Threshold/Waystage/Vantage (English, van Ek & Trim), Niveau
   Seuil (French), Profile Deutsch (German — whose CD-ROM's
   click-a-function-see-its-grammar cross-referencing is essentially
   this spec as a database), Plan Curricular del Instituto Cervantes
   (Spanish).
   - RLD programme: <https://www.coe.int/en/web/common-european-framework-reference-languages/reference-level-descriptions>
   - Profilo: <https://www.unistrapg.it/en/conoscere-l-ateneo/organi-e-strutture/center-for-language-evaluation-and-certification/progetti-cvcl/il-profilo-della-lingua-italiana-livelli-del-qcer-a1-a2-b1-b2>
3. **The notional-functional tradition.** Wilkins (*Notional
   Syllabuses*, 1976) and van Ek's *Threshold Level* organized syllabi
   by meanings — notions (time, quantity, space) and functions
   (requesting, greeting) — with grammar demoted to "exponents". That
   50-year-old pattern is the function→grammar relationship here.
   - Threshold 1990 full text: <https://ealta.eu/documents/resources/Threshold-Level_CUP.pdf>
4. **Action-oriented backward design.** Current CEFR methodology
   (Piccardo & North): choose can-dos as outcomes → build a scenario
   culminating in a task → derive the functions/exponents/grammar/
   vocab the task needs → assess with the same descriptors. Maestro's
   can-do decomposition + scenario arcs + cando-tagged application
   items is this loop, automated.
   - North, "The CV and the action-oriented approach": <https://rm.coe.int/the-cefr-companion-volume-and-the-action-oriented-approach/1680a88678>
5. **Commercial practice.** Coursebook units are scenario/topic-shaped
   with a can-do objectives box and function-led grammar presentation;
   publishers ship "CEFR correlation charts" (descriptor → unit — the
   review tool's coverage matrix is the same artifact). Duolingo
   rebuilt its path around CEFR can-dos (~800 words per A-level);
   Busuu/Babbel author against level inventories. There is no official
   "CEFR-certified" stamp — alignment is self-claimed plus external
   efficacy studies. The closest published analogue of `spec/it/` for
   English is the **British Council–EAQUALS Core Inventory** (functions
   + grammar + topics per level, with exponents).
   - Core Inventory: <https://www.eaquals.org/wp-content/uploads/EAQUALS_British_Council_Core_Curriculum_April2011.pdf>
   - Duolingo CEFR path: <https://blog.duolingo.com/how-are-duolingo-courses-evolving/>
6. **Vocabulary sizes.** The CEFR specifies none. Research bands
   (Milton & Alexiou 2009): A1 < ~1,500, A2 ~1,500–2,500 lemmas — the
   plan's ~1,500-through-A2 target is the conservative end of a
   defensible range. For the expansion, the open **KELLY project**
   Italian list (corpus-derived, CEFR-banded, ~9k items) and the
   Profilo's own lexical inventories are the sources to cross-check.
   - Milton: <http://www.eurosla.org/monographs/EM01/211-232Milton.pdf>
   - KELLY lists: <https://ssharoff.github.io/kelly/>

## 4. Deviations and cautions

- **An RLD is practitioner consensus, not ground truth.** Grammar-per-
  level tables are contested (Thornbury: publish an inventory and it
  quietly becomes a grammar syllabus again). The quality validator
  finding `ordinare` leveled A2 while the `a0_ordinare` function exists
  is exactly this class of artifact; treating spec levels as revisable
  is the right posture. The data-driven alternative for English is the
  corpus-based English Grammar/Vocabulary Profile
  (<https://englishprofile.org/>); nothing of comparable scale exists
  for Italian — the Profilo's CELI-corpus validation is the nearest.
- **Teaching-to-descriptors.** Descriptors are samples of a proficiency
  construct, not a checklist to drill verbatim. Maestro is structurally
  protected: descriptors never appear as exercises — they are
  achievement rollups over scenario/task evidence, which is what the
  action-oriented literature prescribes.
- **Genuinely missing vs the canon:** the CEFR's **notions** (general:
  time/space/quantity; specific: topic lexicons) have no explicit slot
  — `vocab_domains` is a free-form placeholder where the Profilo's
  *nozioni specifiche* would map; **mediation** and **online
  interaction** (the CV's 2020 additions) are absent — a legitimate v1
  scope cut at A-levels; and the can-do set is self-authored and
  LLM-drafted, so its pending human curation pass (flagged in the file
  header) is the one place the pedagogical foundation still rests on
  unreviewed text.
