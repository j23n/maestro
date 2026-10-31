"""Level plans, text analysis, the text checker, the coverage report and new briefs.

Level plans live in content/curriculum/<level>.md: a key: value header, a line with ---, then notes.
The grammar sequence itself comes from content/grammar (each topic's level and order).

A text's front matter can carry a brief for the checker (all optional):

    status: brief | draft | reviewed
    introduces: direct-object-pronouns     the grammar point the text teaches
    recycle: passato-prossimo, imperfetto  earlier points it must use
    newWords: prenotare:v, compleanno:n    new words it may introduce (headword:pos)
    reuse: festa:n, invitare:v             recent words it must use again
    avoid: passato-remoto                  grammar points it must not use
    words: 90-130                          length in words
    register: tu | Lei | tu, Lei
    window: 12-01..01-06 | easter-60..easter-47   when the library features it
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import frequency, grammar, packs

LEVELS = ["A1", "A2", "B1", "B2"]

# Verb form (mood.tense) -> the grammar topic that teaches it. Forms without a topic carry a level.
FORM_TOPIC = {
    "ind.pres": "presente-indicativo", "ind.pp": "passato-prossimo", "part.pass": "passato-prossimo",
    "ind.impf": "imperfetto", "imp.pres": "imperativo", "imp.neg": "imperativo", "ind.fut": "futuro-semplice",
    "cond.pres": "condizionale-presente", "ind.tpp": "trapassato-prossimo", "sub.pres": "congiuntivo-presente",
    "ind.prem": "passato-remoto", "ind.tpr": "passato-remoto", "cond.pass": "condizionale-passato",
    "ind.futa": "futuro-anteriore", "sub.pass": "congiuntivo-passato", "sub.impf": "congiuntivo-imperfetto",
    "sub.tpp": "congiuntivo-imperfetto",
}
FORM_LEVEL = {"inf.pres": "A1", "ger.pres": "A2", "inf.pass": "B1", "part.pres": "B1", "ger.pass": "B2"}
ARTICLES = {"it:il:art", "it:un:art"}  # every article counts as a use of the articles topic
PERSONS = ["1s", "2s", "3s", "1p", "2p", "3p"]
STATUSES = ("brief", "draft", "reviewed")


def level_index(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else len(LEVELS)


def form_key(tag: str) -> str:
    """ind.pp.3s+e -> ind.pp"""
    return ".".join(tag.split("+")[0].split(".")[:2])


def form_person(tag: str) -> str | None:
    parts = tag.split("+")[0].split(".")
    return parts[2] if len(parts) == 3 else None


def split_list(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def word_range(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


# --- level plans -------------------------------------------------------------------------

@dataclass
class Plan:
    level: str
    known_rank: int          # lemmas up to this frequency rank count as known at the level
    core_rank: int           # the level's core vocabulary: ranks up to this
    known_share: float       # share of running words a text's reader should know
    new_words: int           # new lemmas a text may introduce
    words: tuple[int, int]   # text length in words
    sentence_words: float    # highest mean words per sentence
    persons: list[str]       # persons the level's texts must use, together
    blocks: list[str]        # block types the level must have
    registers: list[str]     # registers the level must have (tu, Lei)
    topic_share: float       # largest share of the level's texts one topic may take
    tense_share: float       # largest share of a collection's finite verbs one past tense may take
    recurrence: int          # later texts a new word must reappear in ...
    recurrence_window: int   # ... out of this many
    notes: str = ""


def parse_plan(path: str) -> Plan:
    with open(path, encoding="utf-8") as fh:
        header, _, notes = fh.read().partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    try:
        words = word_range(meta["words"])
        if words is None:
            raise ValueError("words must be like 60-120")
        return Plan(
            level=meta["level"], known_rank=int(meta["knownRank"]), core_rank=int(meta["coreRank"]),
            known_share=float(meta["knownShare"]), new_words=int(meta["newWords"]), words=words,
            sentence_words=float(meta["sentenceWords"]), persons=split_list(meta.get("persons", "")),
            blocks=split_list(meta.get("blocks", "")), registers=split_list(meta.get("registers", "")),
            topic_share=float(meta.get("topicShare", "1")), tense_share=float(meta.get("tenseShare", "1")),
            recurrence=int(meta.get("recurrence", "0")), recurrence_window=int(meta.get("recurrenceWindow", "10")),
            notes=notes.strip())
    except KeyError as exc:
        raise ValueError(f"{path}: missing {exc.args[0]}") from None


def load_plans(directory: str) -> dict[str, Plan]:
    plans = {}
    for f in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        if f.endswith(".md") and f != "README.md":
            plan = parse_plan(os.path.join(directory, f))
            plans[plan.level] = plan
    return plans


# --- text analysis -----------------------------------------------------------------------

@dataclass
class Word:
    key: str                # lemma ID, or "form:<surface>" when the token has no lemma
    surface: str
    rank: int | None        # frequency rank of the lemma, else of the surface form
    proper: bool


@dataclass
class TextFacts:
    id: str
    path: str
    title: str
    level: str
    collection: str
    order: int
    meta: dict[str, str]
    words: list[Word] = field(default_factory=list)
    sentence_lengths: list[int] = field(default_factory=list)
    block_types: set[str] = field(default_factory=set)
    forms: Counter = field(default_factory=Counter)        # mood.tense -> count, finite and non-finite
    persons: Counter = field(default_factory=Counter)
    grammar_tags: Counter = field(default_factory=Counter)  # topics named by tokens and units
    lemma_counts: Counter = field(default_factory=Counter)
    sentences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.meta.get("status", "reviewed")

    @property
    def topics(self) -> list[str]:
        return split_list(self.meta.get("topics", ""))

    @property
    def registers(self) -> list[str]:
        return split_list(self.meta.get("register", ""))

    def uses(self, topic: str) -> int:
        """How often the text uses a grammar topic: marked tokens and units, plus verb forms."""
        return self.grammar_tags[topic] + sum(n for f, n in self.forms.items() if FORM_TOPIC.get(f) == topic)

    def word_keys(self) -> set[str]:
        return {w.key for w in self.words if not w.proper}


class Ranks:
    def __init__(self, conn: sqlite3.Connection, form_counts: dict[str, int]):
        self.lemma = {lid: r for lid, r in conn.execute("SELECT id, freq_rank FROM lemma WHERE freq_rank IS NOT NULL")}
        self.form = frequency.form_ranks(form_counts)

    def of(self, lemma_id: str | None, surface: str) -> int | None:
        if lemma_id and lemma_id in self.lemma:
            return self.lemma[lemma_id]
        return self.form.get(surface.lower())


def analyse(lex: packs.Lexicon, ranks: Ranks, path: str) -> TextFacts:
    src = packs.parse_source(path)
    meta = _front_matter(path)
    text, warnings = packs.build_text(lex, src)
    facts = TextFacts(id=src.id, path=path, title=src.title, level=src.level, collection=src.collection,
                      order=src.order, meta=meta, warnings=warnings, lemma_counts=packs.text_lemmas(text))
    for block in text["blocks"]:
        facts.block_types.add(block["type"])
        for s in block["sentences"]:
            facts.sentences.append(s["text"])
            covered: set[int] = set()
            for u in s.get("units", []):
                covered.update(u["tokens"])
                if u.get("form"):
                    _count_form(facts, u["form"])
                for g in u.get("grammar", []):
                    facts.grammar_tags[g] += 1
            n = 0
            for i, tok in enumerate(s["tokens"]):
                if tok.get("pos") in ("PUNCT", "NUM"):
                    continue
                n += 1
                for g in tok.get("grammar", []):
                    facts.grammar_tags[g] += 1
                if tok.get("form") and i not in covered:
                    _count_form(facts, tok["form"])
                proper = tok.get("pos") == "PROPN"
                parts = tok.get("parts") or [tok]
                for p in parts:
                    lemma_id = p.get("lemmaID")
                    if lemma_id in ARTICLES:
                        facts.grammar_tags["articles"] += 1
                    key = lemma_id or f"form:{p['t'].lower()}"
                    facts.words.append(Word(key=key, surface=p["t"], rank=ranks.of(lemma_id, p["t"]), proper=proper))
            facts.sentence_lengths.append(n)
    return facts


def _count_form(facts: TextFacts, tag: str) -> None:
    facts.forms[form_key(tag)] += 1
    person = form_person(tag)
    if person:
        facts.persons[person] += 1


def _front_matter(path: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for line in lines[1:]:
        if not line.strip():
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def source_files(directory: str) -> list[str]:
    out = []
    for root, _, files in os.walk(directory):
        out.extend(os.path.join(root, f) for f in files if f.endswith(".md"))
    return sorted(out)


def is_brief(path: str) -> bool:
    return _front_matter(path).get("status") == "brief"


def sequence(texts: list[TextFacts]) -> list[TextFacts]:
    """The order a learner meets texts in: by level, then by position in the collection."""
    return sorted(texts, key=lambda t: (level_index(t.level), t.order, t.collection, t.id))


# --- the library -------------------------------------------------------------------------

@dataclass
class Library:
    texts: list[TextFacts]               # in sequence order
    plans: dict[str, Plan]
    topics: dict[str, grammar.Topic]
    ranks: Ranks
    lex: packs.Lexicon

    def topic_level(self, topic: str) -> str | None:
        t = self.topics.get(topic)
        return t.level if t else None

    def form_level(self, form: str) -> str | None:
        topic = FORM_TOPIC.get(form)
        return self.topic_level(topic) if topic else FORM_LEVEL.get(form)

    def before(self, text: TextFacts) -> list[TextFacts]:
        """Texts a reader of this text has met: lower levels, and earlier texts at its level."""
        out = []
        for t in self.texts:
            if t.id == text.id:
                continue
            if level_index(t.level) < level_index(text.level) or (
                    t.level == text.level and (t.order, t.collection, t.id) < (text.order, text.collection, text.id)):
                out.append(t)
        return out

    def known(self, text: TextFacts) -> set[str]:
        known = set()
        for t in self.before(text):
            known |= t.word_keys()
        return known

    def new_words(self, text: TextFacts) -> dict[str, Word]:
        """Words in the text that are neither in the level's known band nor in an earlier text."""
        plan = self.plans.get(text.level)
        known = self.known(text)
        out: dict[str, Word] = {}
        for w in text.words:
            if w.proper or w.key in known:
                continue
            if plan and w.rank is not None and w.rank <= plan.known_rank:
                continue
            out.setdefault(w.key, w)
        return out

    def lemma_for(self, spec: str) -> str | None:
        headword, _, pos = spec.partition(":")
        return self.lex.lemma(headword.strip(), (pos or "n").strip())


def load_library(conn: sqlite3.Connection, texts_dir: str, curriculum_dir: str, grammar_dir: str,
                 frequency_path: str, extra: list[str] | None = None) -> Library:
    lex = packs.Lexicon(conn)
    ranks = Ranks(conn, frequency.load(frequency_path))
    paths = [p for p in source_files(texts_dir) if not is_brief(p)]
    for p in extra or []:
        if os.path.abspath(p) not in {os.path.abspath(x) for x in paths} and not is_brief(p):
            paths.append(p)
    texts = sequence([analyse(lex, ranks, p) for p in paths])
    topics = {t.id: t for t in grammar.load_all(grammar_dir)}
    return Library(texts=texts, plans=load_plans(curriculum_dir), topics=topics, ranks=ranks, lex=lex)


# --- the checker -------------------------------------------------------------------------

@dataclass
class Finding:
    text: str
    check: str
    message: str
    error: bool = True

    def __str__(self) -> str:
        return f"{'error' if self.error else 'warning'}: {self.text}: {self.check}: {self.message}"


def check_text(lib: Library, text: TextFacts) -> list[Finding]:
    out: list[Finding] = []

    def add(check: str, message: str, error: bool = True) -> None:
        out.append(Finding(text.id, check, message, error))

    plan = lib.plans.get(text.level)
    if plan is None:
        add("plan", f"no level plan for {text.level} in content/curriculum")
        return out
    meta = text.meta
    if text.status not in STATUSES:
        add("status", f"status must be one of {', '.join(STATUSES)}")

    # New words: the brief's list counts as allowed; without a brief, the most used ones up to the limit.
    new = lib.new_words(text)
    allowed: set[str] = set()
    for spec in split_list(meta.get("newWords", "")):
        lemma_id = lib.lemma_for(spec)
        if lemma_id is None:
            add("brief", f"new word {spec!r} is not in the dictionary")
        else:
            allowed.add(lemma_id)
    extra = [k for k in new if k not in allowed]
    uses = Counter(w.key for w in text.words)
    if not meta.get("newWords"):
        extra.sort(key=lambda k: -uses[k])
        allowed |= set(extra[:plan.new_words])
        extra = extra[plan.new_words:]
    limit = 2 if meta.get("newWords") else 0
    if len(extra) > limit:
        names = ", ".join(sorted(new[k].surface.lower() for k in extra))
        if meta.get("newWords"):
            add("new words", f"{len(extra)} new words that aren't in the brief (at most {limit}): {names}")
        else:
            add("new words", f"{len(new)} new words, more than the {plan.new_words} a {text.level} text may "
                             f"introduce; the least used: {names}")
    beyond = sorted({new[k].surface.lower() for k in new
                     if new[k].rank is None or new[k].rank > plan.core_rank})
    if beyond:
        add("beyond level", f"words outside the {text.level} core: {', '.join(beyond)}; gloss or replace them",
            error=False)

    content = [w for w in text.words if not w.proper]
    if content:
        unknown = sum(1 for w in content if w.key in new and w.key not in allowed)
        share = 1 - unknown / len(content)
        if share < plan.known_share:
            add("known words", f"{share:.0%} known, below the {plan.known_share:.0%} target")

    # Grammar above the level, unless a note explains it.
    explained = set(text.grammar_tags)
    for form, n in sorted(text.forms.items()):
        level = lib.form_level(form)
        topic = FORM_TOPIC.get(form)
        if level and level_index(level) > level_index(text.level) and topic not in explained:
            add("above-level grammar", f"{form} ({topic or level}) used {n} times; it is taught at {level}")
    for topic in split_list(meta.get("avoid", "")):
        if text.uses(topic):
            add("brief", f"uses {topic}, which the brief avoids")

    # Brief targets.
    for topic in split_list(meta.get("introduces", "")):
        if topic not in lib.topics:
            add("brief", f"unknown grammar topic {topic!r}")
            continue
        need = 3 if any(t == topic for t in FORM_TOPIC.values()) else 1
        if text.uses(topic) < need:
            add("brief", f"introduces {topic} but uses it {text.uses(topic)} times (needs {need})")
    for topic in split_list(meta.get("recycle", "")):
        if topic not in lib.topics:
            add("brief", f"unknown grammar topic {topic!r}")
        elif not text.uses(topic):
            add("brief", f"must recycle {topic}")
    keys = text.word_keys()
    for spec in split_list(meta.get("reuse", "")):
        lemma_id = lib.lemma_for(spec)
        if lemma_id is None:
            add("brief", f"reuse word {spec!r} is not in the dictionary")
        elif lemma_id not in keys:
            add("brief", f"must reuse {spec}")
    for spec in split_list(meta.get("newWords", "")):
        lemma_id = lib.lemma_for(spec)
        if lemma_id and uses[lemma_id] < 2:
            add("recycling", f"new word {spec} appears {uses[lemma_id]} times; use it at least twice", error=False)

    # Length.
    n_words = len(text.words)
    lo, hi = word_range(meta.get("words", "")) or plan.words
    if not lo <= n_words <= hi:
        add("length", f"{n_words} words, outside {lo}-{hi}")
    if text.sentence_lengths:
        mean = sum(text.sentence_lengths) / len(text.sentence_lengths)
        if mean > plan.sentence_words:
            add("length", f"{mean:.1f} words per sentence, above {plan.sentence_words:g}")

    # Register and feature window.
    for r in text.registers:
        if r not in ("tu", "Lei"):
            add("register", f"register must be tu or Lei, not {r!r}")
    window = meta.get("window")
    if window and not packs.window_valid(window):
        add("window", f"window {window!r} must look like 12-01..01-06 or easter-60..easter-47")

    # Near duplicates.
    mine = _shingles(text)
    for other in lib.texts:
        if other.id == text.id:
            continue
        theirs = _shingles(other)
        if mine and theirs:
            overlap = len(mine & theirs) / min(len(mine), len(theirs))
            if overlap > 0.15:
                add("duplicate", f"{overlap:.0%} of its four-word runs also appear in {other.id}", error=False)
        if other.title.strip().lower() == text.title.strip().lower():
            add("duplicate", f"same title as {other.id}", error=False)

    # Linker warnings go to the reviewer.
    if text.warnings:
        add("linking", f"{len(text.warnings)} tokens the linker could not resolve; the reviewer checks them",
            error=False)
    return out


WINDOW_RE = packs.WINDOW_RE


def _shingles(text: TextFacts) -> set[tuple[str, ...]]:
    words = [w.surface.lower() for w in text.words]
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)}


# --- coverage ----------------------------------------------------------------------------

@dataclass
class LevelCoverage:
    level: str
    texts: list[TextFacts]
    core_met: int = 0
    core_size: int = 0
    new_words: dict[str, tuple[TextFacts, Word]] = field(default_factory=dict)   # key -> introducing text
    recurrence: dict[str, int] = field(default_factory=dict)                      # key -> later texts using it
    in_text_twice: int = 0
    grammar: dict[str, tuple[list[str], int]] = field(default_factory=dict)      # topic -> (introduced by, used in)
    tenses: dict[str, Counter] = field(default_factory=dict)                     # collection -> form counts
    persons: Counter = field(default_factory=Counter)
    blocks: Counter = field(default_factory=Counter)
    registers: Counter = field(default_factory=Counter)
    topics: Counter = field(default_factory=Counter)
    above: list[Finding] = field(default_factory=list)


FINITE_MOODS = ("ind.", "sub.", "cond.", "imp.")


def coverage(lib: Library, conn: sqlite3.Connection) -> dict[str, LevelCoverage]:
    result: dict[str, LevelCoverage] = {}
    for level in LEVELS:
        plan = lib.plans.get(level)
        texts = [t for t in lib.texts if t.level == level]
        cov = LevelCoverage(level=level, texts=texts)
        result[level] = cov
        if plan is None:
            continue
        up_to = [t for t in lib.texts if level_index(t.level) <= level_index(level)]
        used = set().union(*(t.word_keys() for t in up_to)) if up_to else set()
        core = {lid for lid, r in lib.ranks.lemma.items() if r <= plan.core_rank}
        cov.core_size = len(core)
        cov.core_met = len(core & used)

        later_pool = [t for t in lib.texts if t.level in (level, _next_level(level))]
        for t in texts:
            for key, w in lib.new_words(t).items():
                cov.new_words.setdefault(key, (t, w))
        for key, (t, _) in cov.new_words.items():
            idx = later_pool.index(t)
            window = later_pool[idx + 1: idx + 1 + plan.recurrence_window]
            cov.recurrence[key] = sum(1 for x in window if key in x.word_keys())
            if sum(1 for w in t.words if w.key == key) >= 2:
                cov.in_text_twice += 1

        for topic in sorted(lib.topics.values(), key=lambda x: x.order):
            if topic.level != level:
                continue
            introduced = [t.id for t in lib.texts if topic.id in split_list(t.meta.get("introduces", ""))]
            used_in = sum(1 for t in lib.texts if level_index(t.level) >= level_index(level) and t.uses(topic.id))
            cov.grammar[topic.id] = (introduced, used_in)

        for t in texts:
            tenses = cov.tenses.setdefault(t.collection, Counter())
            for form, n in t.forms.items():
                if form.startswith(FINITE_MOODS):
                    tenses[form] += n
            cov.persons.update(t.persons)
            cov.blocks.update(t.block_types)
            cov.registers.update(t.registers)
            cov.topics.update(t.topics)
            cov.above.extend(f for f in check_text(lib, t) if f.check == "above-level grammar")
    return result


def _next_level(level: str) -> str | None:
    i = level_index(level)
    return LEVELS[i + 1] if i + 1 < len(LEVELS) else None


def report(lib: Library, cov: dict[str, LevelCoverage], sample: bool) -> str:
    out = ["# Coverage report", ""]
    if sample:
        out += ["Built from the sample dictionary, so most words aren't linked and the numbers are rough. "
                "Run `make content CONTENT=full` first for real numbers.", ""]
    out += ["| Level | Texts | Drafts | Words | Core words met |", "| --- | --- | --- | --- | --- |"]
    for level in LEVELS:
        c = cov[level]
        drafts = sum(1 for t in c.texts if t.status != "reviewed")
        met = f"{c.core_met} of {c.core_size}" if c.core_size else "n/a"
        out.append(f"| {level} | {len(c.texts)} | {drafts} | {sum(len(t.words) for t in c.texts)} | {met} |")
    for level in LEVELS:
        c, plan = cov[level], lib.plans.get(level)
        if plan is None:
            continue
        out += ["", f"## {level}", ""]
        if not c.texts:
            out += ["No texts yet.", ""]
        # Grammar
        out += ["### Grammar", "", "| Topic | Introduced by | Texts using it | Status |", "| --- | --- | --- | --- |"]
        for topic, (by, used_in) in c.grammar.items():
            status = "missing" if not by else ("recycle more" if used_in < 4 else "ok")
            out.append(f"| {topic} | {', '.join(by) or '-'} | {used_in} | {status} |")
        # Vocabulary
        met = [k for k, n in c.recurrence.items() if n >= plan.recurrence]
        out += ["", "### New words", "",
                f"{len(c.new_words)} new words; {len(met)} reappear in {plan.recurrence} of the next "
                f"{plan.recurrence_window} texts; {c.in_text_twice} are used twice in the text that introduces them."]
        low = sorted((k for k in c.recurrence if c.recurrence[k] < plan.recurrence),
                     key=lambda k: (lib.texts.index(c.new_words[k][0]), k), reverse=True)[:20]
        if low:
            out.append("Most recent words below the target: " + ", ".join(
                f"{c.new_words[k][1].surface.lower()} ({c.new_words[k][0].id}, {c.recurrence[k]})" for k in low) + ".")
        # Tenses
        out += ["", "### Tenses", ""]
        forms = sorted({f for counts in c.tenses.values() for f in counts})
        if forms:
            out += ["| Collection | " + " | ".join(forms) + " |", "| --- |" + " --- |" * len(forms)]
            for coll, counts in sorted(c.tenses.items()):
                total = sum(counts.values()) or 1
                cells = []
                for f in forms:
                    share = counts[f] / total
                    flag = " (high)" if f != "ind.pres" and share > plan.tense_share else ""
                    cells.append(f"{share:.0%}{flag}" if counts[f] else "-")
                out.append(f"| {coll} | " + " | ".join(cells) + " |")
        missing = [p for p in plan.persons if not c.persons[p]]
        out += ["", "Persons: " + ", ".join(f"{p} {c.persons[p]}" for p in PERSONS) +
                (f". Missing: {', '.join(missing)}." if missing else ".")]
        # Variety
        missing_blocks = [b for b in plan.blocks if not c.blocks[b]]
        missing_registers = [r for r in plan.registers if not c.registers[r]]
        out += ["", "### Variety", "",
                "Blocks: " + (", ".join(f"{b} {n}" for b, n in sorted(c.blocks.items())) or "none") +
                (f". Missing: {', '.join(missing_blocks)}." if missing_blocks else "."),
                "Register: " + (", ".join(f"{r} {n}" for r, n in sorted(c.registers.items())) or "not marked") +
                (f". Missing: {', '.join(missing_registers)}." if missing_registers else ".")]
        if c.texts:
            # Shares mean little in a handful of texts.
            heavy = [t for t, n in c.topics.items() if len(c.texts) >= 5 and n / len(c.texts) > plan.topic_share]
            out.append("Topics: " + (", ".join(f"{t} {n}" for t, n in c.topics.most_common()) or "none") +
                       (f". Over-used: {', '.join(heavy)}." if heavy else "."))
        if c.above:
            out += ["", "### Above-level grammar", ""] + [f"- {f.text}: {f.message}" for f in c.above]
    return "\n".join(out) + "\n"


# --- briefs ------------------------------------------------------------------------------

def propose_brief(lib: Library, conn: sqlite3.Connection, level: str, collection: str, title: str,
                  window: str = "") -> tuple[str, str]:
    """(path, content) of a new brief aimed at the level's gaps."""
    plan = lib.plans[level]
    cov = coverage(lib, conn)[level]
    in_collection = [t for t in lib.texts if t.collection == collection]
    order = max((t.order for t in in_collection), default=0) + 1
    text_id = f"{collection}-{order:02d}"

    # The next grammar point in the sequence, else the least used one at the level.
    topics = [t for t in sorted(lib.topics.values(), key=lambda x: x.order) if t.level == level]
    missing = [t.id for t in topics if not cov.grammar.get(t.id, ([], 0))[0]]
    introduces = missing[0] if missing else min(topics, key=lambda t: cov.grammar[t.id][1]).id if topics else ""
    # Two earlier points due for recycling: introduced, at or below the level, least used.
    earlier = [t for t in lib.topics.values()
               if level_index(t.level) <= level_index(level) and t.id != introduces
               and t.order < (lib.topics[introduces].order if introduces else 10**6)]
    usage = {t.id: sum(1 for x in lib.texts if x.uses(t.id)) for t in earlier}
    recycle = sorted(usage, key=lambda k: (usage[k], -lib.topics[k].order))[:2]

    # New words: the level's core band, not yet met at or below the level, most frequent first.
    used = set().union(*(t.word_keys() for t in lib.texts if level_index(t.level) <= level_index(level))) \
        if lib.texts else set()
    candidates = conn.execute(
        "SELECT id, headword, pos FROM lemma WHERE freq_rank > ? AND freq_rank <= ? AND pos IN ('n','v','adj','adv') "
        "ORDER BY freq_rank LIMIT 400", (plan.known_rank, plan.core_rank)).fetchall()
    new = [f"{h}:{p}" for lid, h, p in candidates if lid not in used][:plan.new_words]
    # Reuse: the most recent new words below their recurrence target.
    low = sorted((k for k, n in cov.recurrence.items() if n < plan.recurrence and not k.startswith("form:")),
                 key=lambda k: lib.texts.index(cov.new_words[k][0]), reverse=True)
    reuse = []
    for key in low:
        row = conn.execute("SELECT headword, pos FROM lemma WHERE id = ?", (key,)).fetchone()
        if row:
            reuse.append(f"{row[0]}:{row[1]}")
        if len(reuse) == 4:
            break
    blocks = sorted(plan.blocks, key=lambda b: cov.blocks[b])
    persons = [p for p in plan.persons if not cov.persons[p]]
    registers = sorted(plan.registers, key=lambda r: cov.registers[r])

    lines = [f"# {title}", f"level: {level}", f"collection: {collection}", f"order: {order}", "status: brief",
             "topics: ", f"introduces: {introduces}", f"recycle: {', '.join(recycle)}",
             f"newWords: {', '.join(new)}", f"reuse: {', '.join(reuse)}",
             f"words: {plan.words[0]}-{plan.words[1]}", f"register: {registers[0] if registers else 'tu'}"]
    if blocks:
        lines.append(f"blocks: {blocks[0]}")
    if persons:
        lines.append(f"persons: {', '.join(persons)}")
    if window:
        lines.append(f"window: {window}")
    path = os.path.join(collection, f"{text_id}.md")
    return path, "\n".join(lines) + "\n"
