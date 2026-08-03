"""Content-quality validators (`maestro-pack validate --quality`).

Everything beyond schema shape and referential integrity: the checks
that defend an LLM-drafted bank at volume (plan §5 Phase 2, audit item
B2). All checks return *warnings* keyed by item id — the reviewer
decides; only schema/ref problems hard-fail a build.

- vocab level: every Italian content word must lemmatize into the
  leveled vocab list (at or below the item's level) or be glossed
- solvability: cloze has a blank, distractors don't collide with
  accepted answers, MC feedback keys are actual choices, passage
  questions are answerable from the passage
- near-duplicates: same-scope drills with nearly identical prompts
- orthography: high-precision Italian elision rules (la/lo/una + vowel,
  un' + consonant)
- adversarial answer pass: a second model tries to find defensible
  answers the key doesn't accept (API or any injected completion fn)

Lemmatization is simplemma (pure Python, offline). Warnings are tuned
for precision over recall: a noisy checker trains reviewers to ignore
it (decisions.md #18).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable

import yaml

from authoring.pack_schemas import (
    DrillItem,
    GrammarRefItem,
    ListeningItem,
    ReadingItem,
    SpeakingPromptItem,
    VocabCardItem,
    TaskItem,
    WritingPromptItem,
)
from authoring.spec_schemas import Spec
from authoring import vocab_link

_LEVEL_ORDER = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]

# Closed-class words that don't belong in a lemma list but are always
# allowed: articles, clitics, common prepositions (incl. articulated),
# conjunctions, question words, pronouns, numbers 1-10.
_FUNCTION_WORDS = set(
    """
    il lo la i gli le l un uno una
    di a da in con su per tra fra
    del dello della dei degli delle al allo alla ai agli alle
    dal dallo dalla dai dagli dalle nel nello nella nei negli nelle
    sul sullo sulla sui sugli sulle
    e o ma anche non più meno molto poco tanto troppo
    che chi cosa come dove quando quanto quale perché
    io tu lui lei noi voi loro
    mi ti si ci vi ne
    me te sé
    mio mia miei mie tuo tua tuoi tue suo sua suoi sue
    nostro nostra nostri nostre vostro vostra vostri vostre
    questo questa questi queste quello quella quelli quelle
    c ecco po ogni
    dov all dell nell sull dall quell cos anch d
    zero uno due tre quattro cinque sei sette otto nove dieci
    undici dodici tredici quattordici quindici sedici diciassette
    diciotto diciannove venti trenta quaranta cinquanta sessanta
    settanta ottanta novanta cento mille
    essere avere
    """.split()
)

# Apostrophes split tokens, so an elided form leaves a bare stem behind
# («dov'è» -> dov, «l'acqua» -> l, «all'una» -> all). Those stems are listed
# among the function words above; they are elisions of words already there,
# not extra vocabulary.
_WORD_RE = re.compile(r"[a-zA-ZàèéìíòóùúÀÈÉÌÍÒÓÙÚ]+")

# High-frequency irregular forms simplemma mis-lemmatizes; the small map
# that rescues them beats flagging «vai» as noise.
_IRREGULAR = {
    "vado": "andare",
    "vai": "andare",
    "va": "andare",
    "vanno": "andare",
    "faccio": "fare",
    "fai": "fare",
    "fa": "fare",
    "fanno": "fare",
    "do": "dare",
    "dai": "dare",
    "dà": "dare",
    "danno": "dare",
    "sto": "stare",
    "stai": "stare",
    "sta": "stare",
    "stanno": "stare",
    "dico": "dire",
    "dici": "dire",
    "dice": "dire",
    "dica": "dire",
    "bevo": "bere",
    "bevi": "bere",
    "beve": "bere",
    "posso": "potere",
    "puoi": "potere",
    "può": "potere",
    "voglio": "volere",
    "vuoi": "volere",
    "vuole": "volere",
    "devo": "dovere",
    "devi": "dovere",
    "deve": "dovere",
    "so": "sapere",
    "sai": "sapere",
    "sa": "sapere",
    "vengo": "venire",
    "vieni": "venire",
    "viene": "venire",
    "esco": "uscire",
    "esci": "uscire",
    "esce": "uscire",
}


def _levels_upto(level: str) -> set[str]:
    return set(_LEVEL_ORDER[: _LEVEL_ORDER.index(level) + 1])


def italian_texts(item) -> list[str]:
    """The item's learner-facing Italian text fields, unprocessed."""
    texts: list[str] = []
    if isinstance(item, DrillItem):
        # Authoring convention: when a drill prompt mixes an English
        # instruction with Italian material, the Italian sits in
        # «guillemets» — check only that part then.
        quoted = re.findall(r"«([^»]*)»", item.prompt)
        prompt_text = " ".join(quoted) if quoted else item.prompt
        texts = [prompt_text, *(a.text for a in item.answers), *item.choices]
    elif isinstance(item, ReadingItem):
        texts = [item.text, *(q.prompt for q in item.questions)]
    elif isinstance(item, ListeningItem):
        texts = [
            *(t.text for t in item.turns),
            *(q.prompt for q in item.questions),
        ]
    elif isinstance(item, VocabCardItem):
        texts = [item.front, item.example or ""]
    elif isinstance(item, SpeakingPromptItem):
        texts = [item.prompt, item.target_text, *item.variants]
    elif isinstance(item, WritingPromptItem):
        texts = [item.prompt, item.model_answer or ""]
    elif isinstance(item, TaskItem):
        # The rubric is English by design — it is what the learner is
        # measured against, not what they are asked to produce.
        texts = [item.target_text or "", *item.variants]
    elif isinstance(item, GrammarRefItem):
        texts = list(item.examples)
    return [t for t in texts if t]


def _italian_fields(item) -> list[str]:
    """Raw texts with parenthesized spans dropped: they hold verb hints
    in cloze prompts and English glosses/hints by authoring convention."""
    return [re.sub(r"\([^)]*\)", " ", t) for t in italian_texts(item)]


def _glossed_words(item) -> set[str]:
    """Glossary keys plus inline-glossed words («parola (gloss)»)."""
    glossary = getattr(item, "glossary", None) or {}
    glossed = {w.lower() for w in glossary}
    for text in italian_texts(item):
        for m in re.finditer(r"([\w'àèéìíòóùú]+)\s*\([^)]*\)", text):
            glossed.add(m.group(1).lower())
    return glossed


class Lemmatizer:
    """Thin wrapper so tests can inject a fake and simplemma stays lazy."""

    def __init__(self, fn: Callable[[str], str] | None = None):
        if fn is None:
            import simplemma

            fn = lambda w: simplemma.lemmatize(w, lang="it")  # noqa: E731
        self.fn = fn

    def __call__(self, word: str) -> str:
        return self.fn(word)


def _candidates(low: str, lemmatize: Lemmatizer) -> set[str]:
    """Everything a token might be listed under in the lemma list.

    Deliberately generous: extra candidates can only *accept* more words
    (never produce a false warning), so each rule trades recall for
    nothing. Covers feminine/plural endings the lemma list stores as
    masculine singular, first-conjugation verb forms, -essa nouns, and
    reflexive infinitives.
    """
    cands = {low}
    if low in _IRREGULAR:
        cands.add(_IRREGULAR[low])
    if low.endswith("essa"):
        cands.add(low[:-4] + "e")  # studentessa -> studente
    if low.endswith("a"):
        cands.add(low[:-1] + "o")  # italiana -> italiano
        cands.add(low[:-1] + "are")  # ordina -> ordinare
    if low.endswith("e"):
        cands.add(low[:-1] + "a")  # pizze -> pizza
        cands.add(low[:-1] + "o")
    if low.endswith("i"):
        cands.update({low[:-1] + "o", low[:-1] + "e", low[:-1] + "a"})
    cands |= {lemmatize(c) for c in set(cands)}
    # Reflexive infinitive: svegliare -> svegliarsi.
    cands |= {c[:-1] + "si" for c in set(cands) if c.endswith(("are", "ere", "ire"))}
    return cands


def check_vocab_level(
    items: list, spec: Spec, lemmatize: Lemmatizer | None = None
) -> dict[str, list[str]]:
    lemmatize = lemmatize or Lemmatizer()
    warnings: dict[str, list[str]] = {}
    by_level: dict[str, set[str]] = {}
    # Surface -> lemma, generated forward from the same list. simplemma
    # cannot get from "studio" back to "studiare", so a first-person verb
    # of a perfectly in-level word reads as above-level; the linker's own
    # index is the authority on which surfaces the list can produce.
    surfaces: dict[str, dict[str, str]] = {}
    phrase_words = {w for v in spec.vocab for w in v.id.split() if " " in v.id}
    for item in items:
        levels = _levels_upto(item.cefr_level)
        key = "".join(sorted(levels))
        if key not in by_level:
            entries = [v for v in spec.vocab if v.cefr_level in levels]
            by_level[key] = {v.id for v in entries}
            surfaces[key] = vocab_link.build_index(entries)[0]
        allowed = by_level[key]
        glossed = _glossed_words(item)
        flagged: set[str] = set()
        for text in _italian_fields(item):
            for token in _WORD_RE.findall(text):
                low = token.lower()
                if (
                    low in flagged
                    or low in _FUNCTION_WORDS
                    or low in phrase_words
                    or low in glossed
                    or low in allowed
                    or low in surfaces[key]
                ):
                    continue
                cands = _candidates(low, lemmatize)
                if cands & allowed or cands & _FUNCTION_WORDS or cands & glossed:
                    continue
                if token[0].isupper():
                    continue  # assume proper noun (Anna, Roma) — precision
                flagged.add(low)
                warnings.setdefault(item.id, []).append(
                    f"vocab: «{token}» (lemma «{lemmatize(low)}») is above "
                    f"{item.cefr_level} or missing from the vocab list — "
                    "gloss it or swap it"
                )
    return warnings


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\sàèéìíòóùú']", " ", s.lower()).split())


def check_solvability(items: list) -> dict[str, list[str]]:
    warnings: dict[str, list[str]] = {}

    def warn(item_id: str, msg: str) -> None:
        warnings.setdefault(item_id, []).append(msg)

    for item in items:
        if isinstance(item, DrillItem):
            accepted = {_norm(a.text) for a in item.answers}
            if item.item_type == "drill_cloze" and "___" not in item.prompt:
                warn(item.id, "solvability: cloze prompt has no ___ blank")
            if item.item_type == "drill_transform":
                canonical = next(a.text for a in item.answers if a.canonical)
                if _norm(canonical) == _norm(item.prompt):
                    warn(item.id, "solvability: transform answer equals the prompt")
            if item.item_type == "drill_multiple_choice":
                if len(set(item.choices)) < len(item.choices):
                    warn(item.id, "solvability: duplicate choices")
                for k in item.distractor_feedback:
                    if k not in item.choices:
                        warn(
                            item.id,
                            f"solvability: feedback for «{k}» which is not a choice",
                        )
            for k in item.distractor_feedback:
                if _norm(k) in accepted:
                    warn(
                        item.id,
                        f"solvability: «{k}» has distractor feedback but is "
                        "an accepted answer",
                    )
        elif isinstance(item, (ReadingItem, ListeningItem)):
            passage = _norm(
                item.text
                if isinstance(item, ReadingItem)
                else " ".join(t.text for t in item.turns)
            )
            for n, q in enumerate(item.questions, 1):
                canonical = next(a.text for a in q.answers if a.canonical)
                tokens = [t for t in _norm(canonical).split() if len(t) > 2]
                if tokens and not any(t in passage for t in tokens):
                    warn(
                        item.id,
                        f"solvability: q{n} answer «{canonical}» not found in "
                        "the passage",
                    )
        elif isinstance(item, SpeakingPromptItem):
            if any(_norm(v) == _norm(item.target_text) for v in item.variants):
                warn(item.id, "solvability: variant duplicates target_text")
        elif isinstance(item, WritingPromptItem) and item.model_answer:
            if len(item.model_answer.split()) < item.min_words:
                warn(
                    item.id,
                    f"solvability: model_answer is under min_words "
                    f"({len(item.model_answer.split())} < {item.min_words})",
                )
    return warnings


def check_near_duplicates(items: list, threshold: float = 0.88) -> dict[str, list[str]]:
    warnings: dict[str, list[str]] = {}
    drills = [i for i in items if isinstance(i, DrillItem)]
    by_scope: dict[str, list[DrillItem]] = {}
    for d in drills:
        for ev in d.evidence:
            if ev.axis == "grammar":
                by_scope.setdefault(ev.id, []).append(d)
                break
    for group in by_scope.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                ratio = difflib.SequenceMatcher(
                    None, _norm(a.prompt), _norm(b.prompt)
                ).ratio()
                if ratio >= threshold:
                    warnings.setdefault(b.id, []).append(
                        f"near-duplicate of {a.id} (similarity {ratio:.2f})"
                    )
    return warnings


_VOWEL = "aeiouàèéìíòóùú"


def check_orthography(items: list) -> dict[str, list[str]]:
    """High-precision elision rules; anything noisier stays out."""
    warnings: dict[str, list[str]] = {}
    for item in items:
        found: set[str] = set()
        for text in _italian_fields(item):
            for m in re.finditer(rf"\b(la|una)\s+([{_VOWEL}]\w*)", text, re.IGNORECASE):
                found.add(
                    f"orthography: «{m.group(0)}» — elide to "
                    f"«{'un' if m.group(1).lower() == 'una' else 'l'}'"
                    f"{m.group(2)}»"
                )
            for m in re.finditer(rf"\bun'\s*([^{_VOWEL}\W]\w*)", text, re.IGNORECASE):
                found.add(
                    f"orthography: «un'{m.group(1)}» — un' only elides before vowels"
                )
        if found:
            warnings.setdefault(item.id, []).extend(sorted(found))
    return warnings


ADVERSARIAL_PROMPT = """\
You are an adversarial reviewer for Italian drill answer keys. For each
numbered item, decide whether a competent Italian speaker could give a
DIFFERENT answer that is fully correct in context but is NOT in the
accepted list. Be strict: only flag genuinely defensible alternatives
(register variants, equally valid forms), not typos or wrong grammar.

Items:
{items}

Output ONLY a YAML list, one entry per flagged item (omit items with no
defensible alternative):

- index: 1
  alternates: ["the defensible answer(s)"]
  note: "why it is defensible"
"""


def check_adversarial(
    items: list, complete: Callable[[str], str], batch_size: int = 20
) -> dict[str, list[str]]:
    """Second-model pass over drills: defensible answers the key misses.

    ``complete`` is any prompt->text function (the Anthropic call in API
    mode, a canned function in tests). Hits become review-queue warnings.
    """
    warnings: dict[str, list[str]] = {}
    drills = [i for i in items if isinstance(i, DrillItem)]
    for start in range(0, len(drills), batch_size):
        batch = drills[start : start + batch_size]
        listing = "\n".join(
            f"{n}. [{d.item_type}] {d.prompt}\n   accepted: "
            + "; ".join(a.text for a in d.answers)
            + (f"\n   choices: {', '.join(d.choices)}" if d.choices else "")
            for n, d in enumerate(batch, 1)
        )
        text = complete(ADVERSARIAL_PROMPT.format(items=listing))
        m = re.search(r"```(?:yaml)?\n(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1)
        hits = yaml.safe_load(text) or []
        if not isinstance(hits, list):
            continue
        for hit in hits:
            idx = hit.get("index")
            if not isinstance(idx, int) or not (1 <= idx <= len(batch)):
                continue
            d = batch[idx - 1]
            alts = ", ".join(map(str, hit.get("alternates", [])))
            warnings.setdefault(d.id, []).append(
                f"adversarial: defensible alternative(s) not in key: {alts}"
                + (f" — {hit['note']}" if hit.get("note") else "")
            )
    return warnings


def validate_quality(
    items: list, spec: Spec, lemmatize: Lemmatizer | None = None
) -> dict[str, list[str]]:
    """All offline quality checks, merged per item id."""
    merged: dict[str, list[str]] = {}
    for part in (
        check_vocab_level(items, spec, lemmatize),
        check_solvability(items),
        check_near_duplicates(items),
        check_orthography(items),
    ):
        for k, v in part.items():
            merged.setdefault(k, []).extend(v)
    return merged
