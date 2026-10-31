"""Text packs: parse authored sources, tokenise, link tokens to the content DB, validate, write.

Source format (content/texts/<collection>/<nn>-<slug>.md):

    # Il treno per Bologna
    level: B1
    collection: racconti-brevi
    order: 3
    topics: family, travel

    Quando eravamo ragazzi, andavamo ogni estate dai nonni. || When we were kids, ...
    L'anno in cui compii sedici anni, però, mio padre decise ... || The year I turned ...
    @unit saremmo andati | grammar=future-in-the-past | gloss=we would go | note=Future in the past: ...
    @gloss compii = turned (an age)

    > Madre: «Hai portato i panini?» || "Did you bring the sandwiches?"

    ?? Dove andavano ogni estate? || Where did they go every summer? @s1
    - Al mare || To the seaside
    * Dai nonni || To their grandparents'
    ?? La madre era d'accordo? || Did the mother agree? @s4 = no

One line is one sentence, written as Italian || English. Consecutive lines form a prose block and a
blank line ends it. A line starting with "> Speaker:" is its own dialogue block. A word can carry a
hint for the linker: la{pron}, estate{estate:n}. Hints are removed from the text.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from .normalize import apostrophes, nfc, utf16_len, utf16_slice

# --- linguistic tables --------------------------------------------------------------------

# Articulated prepositions: surface -> (preposition, article, gender-number of the article)
_ART = {"il": "ms", "lo": "ms", "l'": "s", "la": "fs", "i": "mp", "gli": "mp", "le": "fp"}
_PREP_STEMS = {"a": "a", "da": "da", "di": "de", "in": "ne", "su": "su"}
CONTRACTIONS: dict[str, tuple[str, str, str]] = {}
for _prep, _stem in _PREP_STEMS.items():
    for _art, _gn in _ART.items():
        if _art == "il":
            _surface = {"a": "al", "da": "dal", "di": "del", "in": "nel", "su": "sul"}[_prep]
        elif _art == "i":
            _surface = {"a": "ai", "da": "dai", "di": "dei", "in": "nei", "su": "sui"}[_prep]
        elif _art == "l'":
            _surface = {"a": "all'", "da": "dall'", "di": "dell'", "in": "nell'", "su": "sull'"}[_prep]
        else:
            _surface = {"a": "a", "da": "da", "di": "de", "in": "ne", "su": "su"}[_prep] + "l" + _art
        CONTRACTIONS[_surface] = (_prep, _art, _gn)
CONTRACTIONS["col"] = ("con", "il", "ms")
CONTRACTIONS["coi"] = ("con", "i", "mp")

# Function words the dictionary can't disambiguate reliably: surface -> (lemma headword, pos, extra)
FUNCTION: dict[str, tuple[str, str, dict]] = {
    "il": ("il", "art", {"gn": "ms"}), "lo": ("il", "art", {"gn": "ms"}), "la": ("il", "art", {"gn": "fs"}),
    "l'": ("il", "art", {}), "i": ("il", "art", {"gn": "mp"}), "gli": ("il", "art", {"gn": "mp"}),
    "le": ("il", "art", {"gn": "fp"}), "un": ("un", "art", {"gn": "ms"}), "uno": ("un", "art", {"gn": "ms"}),
    "una": ("un", "art", {"gn": "fs"}), "un'": ("un", "art", {"gn": "fs"}),
    "di": ("di", "prep", {}), "d'": ("di", "prep", {}), "a": ("a", "prep", {}), "ad": ("a", "prep", {}),
    "da": ("da", "prep", {}), "in": ("in", "prep", {}), "con": ("con", "prep", {}), "su": ("su", "prep", {}),
    "per": ("per", "prep", {}), "tra": ("tra", "prep", {}), "fra": ("fra", "prep", {}),
    "e": ("e", "conj", {}), "ed": ("e", "conj", {}), "o": ("o", "conj", {}), "ma": ("ma", "conj", {}),
    "che": ("che", "conj", {}), "se": ("se", "conj", {}), "perché": ("perché", "conj", {}),
    "quando": ("quando", "conj", {}), "come": ("come", "adv", {}), "mentre": ("mentre", "conj", {}),
    "non": ("non", "adv", {}), "io": ("io", "pron", {}), "tu": ("tu", "pron", {}), "lui": ("lui", "pron", {}),
    "lei": ("lei", "pron", {}), "noi": ("noi", "pron", {}), "voi": ("voi", "pron", {}),
    "loro": ("loro", "pron", {}), "mi": ("mi", "pron", {}), "ti": ("ti", "pron", {}), "si": ("si", "pron", {}),
    "ci": ("ci", "pron", {}), "c'": ("ci", "pron", {}), "vi": ("vi", "pron", {}), "ne": ("ne", "pron", {}),
    "po'": ("poco", "adv", {}), "è": ("essere", "v", {"form": "ind.pres.3s"}),
}

CCONJ = {"e", "ed", "o", "ma", "né", "oppure", "però"}
UPOS = {"v": "VERB", "n": "NOUN", "adj": "ADJ", "adv": "ADV", "prep": "ADP", "art": "DET", "det": "DET",
        "pron": "PRON", "num": "NUM", "intj": "INTJ", "propn": "PROPN", "phr": "X", "contr": "ADP"}
AUXILIARIES = {"essere", "avere"}
INTERVENING = {"già", "mai", "ancora", "sempre", "appena", "più", "anche", "proprio", "ben", "bene", "davvero",
               "poi", "subito", "spesso", "tutto", "tutti"}
COMPOUND = {"ind.pres": "ind.pp", "ind.impf": "ind.tpp", "ind.prem": "ind.tpr", "ind.fut": "ind.futa",
            "sub.pres": "sub.pass", "sub.impf": "sub.tpp", "cond.pres": "cond.pass"}
COMPOUND_TOPIC = {"ind.pp": "passato-prossimo", "ind.tpp": "trapassato-prossimo", "cond.pass": "condizionale-passato",
                  "ind.futa": "futuro-anteriore", "sub.pass": "congiuntivo-passato"}

_TOKEN_RE = re.compile(
    r"(?P<el>[^\W\d_]+')(?![^\W\d_])|(?P<el2>[^\W\d_]+')(?=[^\W\d_])|(?P<w>[^\W\d_]+(?:-[^\W\d_]+)*)"
    r"|(?P<n>\d+(?:[.,:]\d+)*)|(?P<p>[^\s\w])"
)
_HINT_RE = re.compile(r"\{([^{}]*)\}")


class PackError(ValueError):
    pass


# --- source parsing ----------------------------------------------------------------------

@dataclass
class SourceSentence:
    text: str
    translation: str
    hints: dict[int, str] = field(default_factory=dict)  # char offset of the hinted word -> hint
    units: list[dict] = field(default_factory=list)
    glosses: dict[str, str] = field(default_factory=dict)


@dataclass
class SourceBlock:
    type: str
    speaker: str | None
    sentences: list[SourceSentence] = field(default_factory=list)


@dataclass
class SourceText:
    id: str
    title: str
    level: str
    collection: str
    order: int
    topics: list[str]
    blocks: list[SourceBlock]
    questions: list[dict]
    introduces: list[str] = field(default_factory=list)


def _strip_hints(text: str) -> tuple[str, dict[int, str]]:
    hints: dict[int, str] = {}
    out = []
    pos = 0
    for m in _HINT_RE.finditer(text):
        out.append(text[pos:m.start()])
        offset = sum(len(x) for x in out)
        hints[offset] = m.group(1)  # offset = end of the hinted word in the clean text
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), hints


def parse_source(path: str) -> SourceText:
    text_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding="utf-8") as fh:
        lines = [nfc(apostrophes(l.rstrip("\n"))) for l in fh]
    if not lines or not lines[0].startswith("# "):
        raise PackError(f"{path}: first line must be '# Title'")
    title = lines[0][2:].strip()
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip():
        key, _, value = lines[i].partition(":")
        meta[key.strip()] = value.strip()
        i += 1
    for key in ("level", "collection", "order"):
        if key not in meta:
            raise PackError(f"{path}: missing '{key}:'")

    blocks: list[SourceBlock] = []
    questions: list[dict] = []
    current: SourceBlock | None = None
    last_sentence: SourceSentence | None = None
    question: dict | None = None

    def sentence_from(raw: str, where: str) -> SourceSentence:
        if "||" not in raw:
            raise PackError(f"{where}: sentence without '|| translation': {raw!r}")
        it, en = (x.strip() for x in raw.split("||", 1))
        clean, hints = _strip_hints(it)
        return SourceSentence(text=clean, translation=en, hints=hints)

    for n, line in enumerate(lines[i:], start=i + 1):
        where = f"{path}:{n}"
        stripped = line.strip()
        if not stripped:
            current = None
            continue
        if stripped.startswith("??"):
            current = None
            body = stripped[2:].strip()
            m = re.match(r"(.+?)\|\|(.+?)@(\S+)(?:\s*=\s*(\S+))?\s*$", body)
            if not m:
                raise PackError(f"{where}: question must be '?? prompt || English @sN [= yes|no|notStated]'")
            prompt, prompt_en, refs, value = (x.strip() if x else x for x in m.groups())
            question = {"id": f"q{len(questions) + 1}", "prompt": prompt, "promptEN": prompt_en,
                        "answerSentences": refs.split(",")}
            if value:
                if value not in ("yes", "no", "notStated"):
                    raise PackError(f"{where}: answer must be yes, no or notStated")
                question.update({"type": "yesNoNotStated", "answer": value})
            else:
                question.update({"type": "choice", "options": [], "optionsEN": [], "answer": None})
            questions.append(question)
            continue
        if stripped[:2] in ("- ", "* ") and question is not None and question["type"] == "choice":
            it, _, en = stripped[2:].partition("||")
            if stripped.startswith("* "):
                question["answer"] = len(question["options"])
            question["options"].append(it.strip())
            question["optionsEN"].append(en.strip())
            continue
        question = None
        if stripped.startswith("@"):
            if last_sentence is None:
                raise PackError(f"{where}: annotation before any sentence")
            kind, _, rest = stripped[1:].partition(" ")
            if kind == "unit":
                fields = [f.strip() for f in rest.split("|")]
                unit = {"surface": fields[0]}
                for f in fields[1:]:
                    key, _, value = f.partition("=")
                    unit[key.strip()] = value.strip()
                if "grammar" in unit:
                    unit["grammar"] = [g.strip() for g in unit["grammar"].split(",") if g.strip()]
                last_sentence.units.append(unit)
            elif kind == "gloss":
                word, _, gloss = rest.partition("=")
                last_sentence.glosses[word.strip()] = gloss.strip()
            else:
                raise PackError(f"{where}: unknown annotation @{kind}")
            continue
        if stripped.startswith(">"):
            speaker, _, rest = stripped[1:].partition(":")
            block = SourceBlock(type="dialogue", speaker=speaker.strip())
            last_sentence = sentence_from(rest.strip(), where)
            block.sentences.append(last_sentence)
            blocks.append(block)
            current = None
            continue
        if current is None:
            current = SourceBlock(type=meta.get("type", "prose"), speaker=None)
            blocks.append(current)
        last_sentence = sentence_from(stripped, where)
        current.sentences.append(last_sentence)

    for q in questions:
        if q["type"] == "choice" and (q["answer"] is None or len(q["options"]) < 2):
            raise PackError(f"{path}: question {q['id']} needs options and one marked with '*'")
    return SourceText(
        id=text_id, title=title, level=meta["level"], collection=meta["collection"], order=int(meta["order"]),
        topics=[t.strip() for t in meta.get("topics", "").split(",") if t.strip()], blocks=blocks,
        questions=questions, introduces=[t.strip() for t in meta.get("introduces", "").split(",") if t.strip()],
    )


# --- linking ----------------------------------------------------------------------------

class Lexicon:
    """Read access to the content DB for the linker."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._sense: dict[str, str | None] = {}

    def lemma(self, headword: str, pos: str) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM lemma WHERE headword = ? AND pos = ? AND retired = 0 ORDER BY length(id) LIMIT 1",
            (headword, pos)).fetchone()
        return row[0] if row else None

    def first_sense(self, lemma_id: str) -> str | None:
        if lemma_id not in self._sense:
            row = self.conn.execute(
                "SELECT id FROM sense WHERE lemma_id = ? AND retired = 0 ORDER BY ord LIMIT 1", (lemma_id,)).fetchone()
            self._sense[lemma_id] = row[0] if row else None
        return self._sense[lemma_id]

    def auxiliary(self, lemma_id: str) -> str | None:
        row = self.conn.execute("SELECT auxiliary FROM lemma WHERE id = ?", (lemma_id,)).fetchone()
        return row[0] if row else None

    def candidates(self, form: str) -> list[tuple[str, str, str, str]]:
        """(lemma_id, tag, pos, headword) for a surface form, exact case first, then lowercase."""
        rows = self.conn.execute(
            "SELECT f.lemma_id, f.tag, l.pos, l.headword FROM form f JOIN lemma l ON l.id = f.lemma_id "
            "WHERE f.form = ? AND l.retired = 0", (form,)).fetchall()
        if not rows and form != form.lower():
            rows = self.conn.execute(
                "SELECT f.lemma_id, f.tag, l.pos, l.headword FROM form f JOIN lemma l ON l.id = f.lemma_id "
                "WHERE f.form = ? AND l.retired = 0", (form.lower(),)).fetchall()
        return rows

    def exists(self, lemma_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM lemma WHERE id = ?", (lemma_id,)).fetchone() is not None


_NOUN_CONTEXT = {"art", "det", "contr", "adj"}
_VERB_CONTEXT = {"pron"}
_POS_ORDER = {"v": 0, "n": 1, "adj": 2, "adv": 3, "pron": 4, "prep": 5, "conj": 6, "det": 7, "art": 8,
              "num": 9, "intj": 10, "propn": 11, "phr": 12, "contr": 13}


def _choose(cands: list[tuple[str, str, str, str]], surface: str, prev_pos: str | None,
            sentence_start: bool) -> tuple[str, str, str, str] | None:
    if not cands:
        return None

    def score(c: tuple[str, str, str, str]) -> tuple:
        lemma_id, tag, pos, headword = c
        s = 0
        if prev_pos in _NOUN_CONTEXT and pos in ("n", "adj"):
            s -= 3
        if prev_pos in _VERB_CONTEXT and pos == "v":
            s -= 3
        if prev_pos == "adv" and pos == "v":
            s -= 1
        if surface[:1].isupper() and not sentence_start and pos == "propn":
            s -= 4
        if pos == "propn" and (sentence_start or surface[:1].islower()):
            s += 2
        if headword.lower() == surface.lower():
            s -= 1
        if lemma_id.count(":") > 2:  # later homographs
            s += 1
        return (s, _POS_ORDER.get(pos, 20), len(lemma_id), lemma_id, tag)

    return sorted(cands, key=score)[0]


def tokenize(text: str) -> list[tuple[str, int, int, str]]:
    """(token, start, end, kind) in code points; kind is el (elided), w, n or p."""
    out = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup or "p"
        if kind == "el2":
            kind = "el"
        out.append((m.group(0), m.start(), m.end(), kind))
    return out


def _lemma_for_hint(lex: Lexicon, hint: str, surface: str) -> tuple[str | None, str | None]:
    if ":" in hint:
        headword, pos = hint.split(":", 1)
        return lex.lemma(headword, pos), pos
    for lemma_id, tag, pos, _ in lex.candidates(surface):
        if pos == hint:
            return lemma_id, pos
    return None, hint


def link_sentence(lex: Lexicon, sentence: SourceSentence) -> tuple[list[dict], list[dict], list[str]]:
    """Tokens, units and warnings for one sentence."""
    raw = tokenize(sentence.text)
    tokens: list[dict] = []
    meta: list[dict] = []  # per token: lemma pos and tag for the unit pass
    warnings: list[str] = []
    prev_pos: str | None = None
    for idx, (surface, start, end, kind) in enumerate(raw):
        tok: dict = {"t": surface, "r": [utf16_len(sentence.text[:start]), utf16_len(surface)]}
        info = {"pos": None, "tag": "", "lemma": None}
        lower = surface.lower()
        hint = sentence.hints.get(end)
        sentence_start = idx == 0 or raw[idx - 1][0] in (".", "!", "?", "«", "\"", "—", ":")
        if kind == "p":
            tok["pos"] = "PUNCT"
            tokens.append(tok)
            meta.append(info)
            continue
        if kind == "n":
            tok["pos"] = "NUM"
            tokens.append(tok)
            meta.append({"pos": "num", "tag": "", "lemma": None})
            prev_pos = "num"
            continue
        if hint:
            lemma_id, pos = _lemma_for_hint(lex, hint, surface)
            if lemma_id:
                tok.update({"pos": UPOS.get(pos or "", "X"), "lemmaID": lemma_id})
                sid = lex.first_sense(lemma_id)
                if sid:
                    tok["senseID"] = sid
                info = {"pos": pos, "tag": "", "lemma": lemma_id, "headword": hint.split(":")[0] if ":" in hint else None}
                for c in lex.candidates(surface):
                    if c[0] == lemma_id and c[1]:
                        _apply_tag(tok, c[1], pos)
                        info["tag"] = c[1]
                        break
            else:
                warnings.append(f"hint {hint!r} on {surface!r} did not resolve")
        elif lower in CONTRACTIONS:
            prep, art, gn = CONTRACTIONS[lower]
            parts = []
            p_id, a_id = lex.lemma(prep, "prep"), lex.lemma("il", "art")
            parts.append({"t": prep if lower[0] == surface[0] else prep.capitalize(), "pos": "ADP",
                          **({"lemmaID": p_id} if p_id else {})})
            art_part = {"t": art, "pos": "DET", **({"lemmaID": a_id} if a_id else {})}
            if len(gn) == 2:
                art_part["gn"] = gn
            parts.append(art_part)
            tok["parts"] = parts
            tok["grammar"] = ["preposition-contractions"]
            info = {"pos": "contr", "tag": "", "lemma": None}
        elif lower in FUNCTION:
            headword, pos, extra = FUNCTION[lower]
            lemma_id = lex.lemma(headword, pos)
            upos = UPOS.get(pos, "X")
            if pos == "conj":
                upos = "CCONJ" if lower in CCONJ else "SCONJ"
            if pos == "v" and headword in AUXILIARIES:
                upos = "AUX"
            tok["pos"] = upos
            if lemma_id:
                tok["lemmaID"] = lemma_id
                if pos not in ("art", "prep", "conj"):
                    sid = lex.first_sense(lemma_id)
                    if sid:
                        tok["senseID"] = sid
            if "gn" in extra:
                tok["gn"] = extra["gn"]
            if "form" in extra:
                tok["form"] = extra["form"]
            info = {"pos": pos, "tag": extra.get("form", ""), "lemma": lemma_id, "headword": headword}
        else:
            choice = _choose(lex.candidates(surface), surface, prev_pos, sentence_start)
            if choice is None and kind == "el":
                choice = _choose(lex.candidates(surface[:-1] + "o"), surface, prev_pos, sentence_start) or \
                         _choose(lex.candidates(surface[:-1] + "a"), surface, prev_pos, sentence_start) or \
                         _choose(lex.candidates(surface[:-1] + "e"), surface, prev_pos, sentence_start)
            if choice is None:
                warnings.append(f"no dictionary match for {surface!r}")
                tok["pos"] = "PROPN" if surface[:1].isupper() and not sentence_start else "X"
            else:
                lemma_id, tag, pos, headword = choice
                upos = UPOS.get(pos, "X")
                if pos == "v" and headword in AUXILIARIES:
                    upos = "AUX"
                if pos == "conj":
                    upos = "CCONJ" if lower in CCONJ else "SCONJ"
                tok.update({"pos": upos, "lemmaID": lemma_id})
                sid = lex.first_sense(lemma_id)
                if sid:
                    tok["senseID"] = sid
                _apply_tag(tok, tag, pos)
                info = {"pos": pos, "tag": tag, "lemma": lemma_id, "headword": headword}
        gloss = sentence.glosses.get(surface)
        if gloss:
            tok["gloss"] = gloss
        tokens.append(tok)
        meta.append(info)
        prev_pos = info["pos"]

    units = _compound_units(lex, tokens, meta)
    units = _apply_manual_units(lex, sentence, tokens, units, warnings)
    return tokens, units, warnings


def _apply_tag(tok: dict, tag: str, pos: str | None) -> None:
    if not tag:
        return
    if pos == "v":
        tok["form"] = tag
    elif len(tag) == 2:
        tok["gn"] = tag


def _compound_units(lex: Lexicon, tokens: list[dict], meta: list[dict]) -> list[dict]:
    units: list[dict] = []
    for i, info in enumerate(meta):
        headword = info.get("headword")
        if info["pos"] != "v" or headword not in AUXILIARIES:
            continue
        prefix = ".".join(info["tag"].split(".")[:2]) if info["tag"] else ""
        if prefix not in COMPOUND:
            continue
        j = i + 1
        while j < len(tokens) and j <= i + 3 and tokens[j]["t"].lower() in INTERVENING:
            j += 1
        if j >= len(tokens) or meta[j]["pos"] != "v" or meta[j]["tag"] != "part.pass":
            continue
        participle_lemma = meta[j]["lemma"]
        if headword == "essere" and participle_lemma and lex.auxiliary(participle_lemma) == "avere":
            continue  # passive, not a compound tense
        person = info["tag"].split(".")[2] if info["tag"].count(".") == 2 else None
        if not person:
            continue
        tag = f"{COMPOUND[prefix]}.{person}"
        aux_of_verb = lex.auxiliary(participle_lemma) if participle_lemma else None
        if aux_of_verb == "both":
            tag += "+e" if headword == "essere" else "+a"
        surface = f"{tokens[i]['t']} {tokens[j]['t']}" if j == i + 1 else f"{tokens[i]['t']} … {tokens[j]['t']}"
        unit = {"tokens": [i, j], "surface": surface, "form": tag}
        if participle_lemma:
            unit["lemmaID"] = participle_lemma
            sid = lex.first_sense(participle_lemma)
            if sid:
                unit["senseID"] = sid
        if headword == "essere":
            ending = tokens[j]["t"][-1:].lower()
            agree = {"o": "ms", "a": "fs", "i": "mp", "e": "fp"}.get(ending)
            if agree:
                unit["agree"] = agree
        topic = COMPOUND_TOPIC.get(COMPOUND[prefix])
        if topic:
            unit["grammar"] = [topic]
        units.append(unit)
    return units


def _find_tokens(tokens: list[dict], surface: str) -> list[int] | None:
    """Indices of the tokens a unit names; '…' allows a gap."""
    pieces = [p.strip().split() for p in surface.split("…")]
    words = [t["t"] for t in tokens]
    for start in range(len(words)):
        idx: list[int] = []
        pos = start
        ok = True
        for n, piece in enumerate(pieces):
            if n > 0:
                while pos < len(words) and words[pos:pos + len(piece)] != piece:
                    pos += 1
            if words[pos:pos + len(piece)] != piece:
                ok = False
                break
            idx.extend(range(pos, pos + len(piece)))
            pos += len(piece)
        if ok:
            return idx
    return None


def _apply_manual_units(lex: Lexicon, sentence: SourceSentence, tokens: list[dict], units: list[dict],
                        warnings: list[str]) -> list[dict]:
    for manual in sentence.units:
        idx = _find_tokens(tokens, manual["surface"])
        if idx is None:
            warnings.append(f"@unit {manual['surface']!r} not found in sentence")
            continue
        target = next((u for u in units if set(u["tokens"]) == set(idx)), None)
        if target is None:
            units = [u for u in units if not set(u["tokens"]) & set(idx)]
            target = {"tokens": idx, "surface": manual["surface"]}
            verb = next((tokens[i] for i in reversed(idx) if tokens[i].get("pos") in ("VERB", "AUX")), None)
            if verb and verb.get("lemmaID"):
                target["lemmaID"] = verb["lemmaID"]
                if verb.get("senseID"):
                    target["senseID"] = verb["senseID"]
            units.append(target)
        if "lemma" in manual:
            headword, _, pos = manual["lemma"].partition(":")
            lemma_id = lex.lemma(headword, pos or "v")
            if lemma_id:
                target["lemmaID"] = lemma_id
                sid = lex.first_sense(lemma_id)
                if sid:
                    target["senseID"] = sid
            else:
                warnings.append(f"@unit lemma {manual['lemma']!r} not found")
        for key in ("form", "gloss", "note", "agree"):
            if key in manual:
                target[key] = manual[key]
        if "grammar" in manual:
            target["grammar"] = manual["grammar"]
    return sorted(units, key=lambda u: u["tokens"][0])


# --- building ----------------------------------------------------------------------------

def build_text(lex: Lexicon, src: SourceText) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    blocks = []
    n = 0
    for block in src.blocks:
        texts = [s.text for s in block.sentences]
        block_text = " ".join(texts)
        sentences = []
        offset = 0
        for s in block.sentences:
            n += 1
            tokens, units, w = link_sentence(lex, s)
            warnings.extend(f"{src.id} s{n}: {x}" for x in w)
            entry = {"id": f"s{n}", "r": [offset, utf16_len(s.text)], "text": s.text,
                     "translation": s.translation, "tokens": tokens}
            if units:
                entry["units"] = units
            sentences.append(entry)
            offset += utf16_len(s.text) + 1
        b = {"type": block.type, "text": block_text, "sentences": sentences}
        if block.speaker:
            b["speaker"] = block.speaker
        blocks.append(b)
    text = {"id": src.id, "title": src.title, "level": src.level, "collection": src.collection,
            "blocks": blocks, "questions": src.questions}
    return text, warnings


def text_lemmas(text: dict) -> Counter:
    counts: Counter = Counter()
    for block in text["blocks"]:
        for s in block["sentences"]:
            covered = set()
            for u in s.get("units", []):
                if u.get("lemmaID"):
                    counts[u["lemmaID"]] += 1
                    covered.update(u["tokens"][1:])  # the participle; the auxiliary still counts
            for i, tok in enumerate(s["tokens"]):
                if i in covered:
                    continue
                if tok.get("lemmaID"):
                    counts[tok["lemmaID"]] += 1
                for p in tok.get("parts", []):
                    if p.get("lemmaID"):
                        counts[p["lemmaID"]] += 1
    return counts


def word_count(text: dict) -> int:
    return sum(1 for b in text["blocks"] for s in b["sentences"] for t in s["tokens"] if t.get("pos") != "PUNCT")


def validate_text(text: dict, lex: Lexicon | None = None) -> list[str]:
    """Errors that must fail the build (HANDOFF.md 6.3)."""
    errors = []
    sentence_ids = set()
    for b in text["blocks"]:
        if nfc(b["text"]) != b["text"]:
            errors.append(f"{text['id']}: block text is not NFC")
        if b["type"] == "dialogue" and not b.get("speaker"):
            errors.append(f"{text['id']}: dialogue block without speaker")
        for s in b["sentences"]:
            sentence_ids.add(s["id"])
            if utf16_slice(b["text"], *s["r"]) != s["text"]:
                errors.append(f"{text['id']} {s['id']}: sentence range does not match its text")
            if s["text"] != s["text"].strip():
                errors.append(f"{text['id']} {s['id']}: leading or trailing whitespace")
            for tok in s["tokens"]:
                if utf16_slice(s["text"], *tok["r"]) != tok["t"]:
                    errors.append(f"{text['id']} {s['id']}: range of {tok['t']!r} does not match")
                if lex is not None and tok.get("lemmaID") and not lex.exists(tok["lemmaID"]):
                    errors.append(f"{text['id']} {s['id']}: unknown lemma {tok['lemmaID']}")
            used: set[int] = set()
            for u in s.get("units", []):
                if used & set(u["tokens"]):
                    errors.append(f"{text['id']} {s['id']}: overlapping units")
                used |= set(u["tokens"])
                if max(u["tokens"]) >= len(s["tokens"]):
                    errors.append(f"{text['id']} {s['id']}: unit token index out of range")
    for q in text.get("questions", []):
        for ref in q["answerSentences"]:
            if ref not in sentence_ids:
                errors.append(f"{text['id']} {q['id']}: answer sentence {ref} not in text")
    return errors


def build_all(conn: sqlite3.Connection, source_dir: str, out_dir: str, min_content_db: str,
              bundled: bool = True) -> tuple[list[str], list[str]]:
    """Build every pack under source_dir into out_dir/<collection>/. Returns (warnings, errors)."""
    lex = Lexicon(conn)
    warnings: list[str] = []
    errors: list[str] = []
    collections: dict[str, list[tuple[SourceText, dict]]] = {}
    for root, _, files in os.walk(source_dir):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            src = parse_source(os.path.join(root, f))
            text, w = build_text(lex, src)
            warnings.extend(w)
            errors.extend(validate_text(text, lex))
            collections.setdefault(src.collection, []).append((src, text))

    for collection, items in sorted(collections.items()):
        items.sort(key=lambda x: x[0].order)
        pack_dir = os.path.join(out_dir, collection)
        os.makedirs(os.path.join(pack_dir, "texts"), exist_ok=True)
        levels = sorted({src.level for src, _ in items})
        manifest = {"id": collection, "title": collection.replace("-", " ").capitalize(),
                    "level": levels[0] if len(levels) == 1 else "-".join([levels[0], levels[-1]]),
                    "formatVersion": 1, "version": 1, "minContentDB": min_content_db, "language": "it",
                    "translationLanguage": "en", "texts": []}
        for src, text in items:
            path = f"texts/{text['id']}.json"
            with open(os.path.join(pack_dir, path), "w", encoding="utf-8") as fh:
                json.dump(text, fh, ensure_ascii=False, indent=1)
            counts = text_lemmas(text)
            uses = sorted({g for b in text["blocks"] for s in b["sentences"]
                           for x in s["tokens"] + s.get("units", []) for g in x.get("grammar", [])})
            manifest["texts"].append({
                "id": text["id"], "order": src.order, "title": text["title"], "level": text["level"], "file": path,
                "words": word_count(text), "topics": src.topics,
                "grammar": {"introduces": src.introduces, "uses": uses},
                "lemmas": sorted(counts),
            })
            conn.execute("INSERT OR REPLACE INTO catalog_text (id, pack_id, title, level, collection, words, ord, bundled) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (text["id"], collection, text["title"], text["level"], collection, word_count(text),
                          src.order, 1 if bundled else 0))
            conn.executemany("INSERT OR REPLACE INTO text_lemma (text_id, lemma_id, count) VALUES (?,?,?)",
                             [(text["id"], lid, c) for lid, c in counts.items()])
        with open(os.path.join(pack_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
    conn.commit()
    return warnings, errors
