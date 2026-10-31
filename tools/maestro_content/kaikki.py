"""Read kaikki.org (wiktextract) Italian JSONL into plain records.

Only what the app uses is kept: headword, part of speech, gender, plural, IPA, auxiliary,
senses (gloss, tags, examples, wiktextract senseid, Wikidata QID) and inflected forms.
Entries whose senses are all form-of become form records pointing at their lemma.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from . import tags as tagmap
from .normalize import nfc

POS = {
    "verb": "v", "noun": "n", "adj": "adj", "adv": "adv", "prep": "prep", "article": "art",
    "conj": "conj", "pron": "pron", "det": "det", "num": "num", "intj": "intj", "name": "propn",
    "phrase": "phr", "contraction": "contr", "prep_phrase": "phr", "particle": "adv",
}


@dataclass
class Sense:
    gloss: str
    tags: list[str] = field(default_factory=list)
    examples: list[tuple[str, str | None]] = field(default_factory=list)
    senseid: str | None = None
    wikidata: str | None = None


@dataclass
class Entry:
    headword: str
    pos: str
    etymology: str = ""
    gender: str | None = None
    plural: str | None = None
    ipa: str | None = None
    auxiliary: str | None = None
    senses: list[Sense] = field(default_factory=list)
    forms: list[tuple[str, str]] = field(default_factory=list)  # (form, tag)


@dataclass
class FormOf:
    form: str
    lemma: str
    pos: str
    tag: str


def open_jsonl(path: str) -> Iterator[dict]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _gender(raw: dict) -> str | None:
    tags = set(raw.get("tags", []))
    for ht in raw.get("head_templates", []):
        args = ht.get("args", {})
        g = args.get("1") or args.get("g") or ""
        if g in ("m", "f", "mf", "m-p", "f-p", "mfbysense"):
            return {"m-p": "m", "f-p": "f", "mfbysense": "mf"}.get(g, g)
    if {"masculine", "feminine"} <= tags:
        return "mf"
    if "masculine" in tags:
        return "m"
    if "feminine" in tags:
        return "f"
    return None


_AUX_RE = re.compile(r"auxiliary (essere|avere)(?: or (essere|avere))?")


def _auxiliary(raw: dict) -> str | None:
    found: set[str] = set()
    for f in raw.get("forms", []):
        if "auxiliary" in f.get("tags", []) and f.get("form") in ("essere", "avere"):
            found.add(f["form"])
    for ht in raw.get("head_templates", []):
        m = _AUX_RE.search(ht.get("expansion", ""))
        if m:
            found.update(x for x in m.groups() if x)
        aux_arg = ht.get("args", {}).get("1", "")
        if ht.get("name", "").startswith("it-verb") and aux_arg:
            for code in aux_arg.split(","):
                code = code.strip()[:1]
                if code == "e":
                    found.add("essere")
                elif code == "a":
                    found.add("avere")
    if not found:
        return None
    return "both" if len(found) == 2 else found.pop()


def _ipa(raw: dict) -> str | None:
    for s in raw.get("sounds", []):
        if s.get("ipa"):
            return s["ipa"]
    return None


def _clean_form(form: str) -> str | None:
    form = nfc(form.strip())
    if not form or " " in form or form in ("-", "—") or form.startswith("-"):
        return None
    return form


def parse(raw: dict) -> tuple[Entry | None, list[FormOf]]:
    if raw.get("lang_code", "it") != "it":
        return None, []
    pos = POS.get(raw.get("pos", ""))
    word = raw.get("word")
    if not pos or not word:
        return None, []
    word = nfc(word)

    senses: list[Sense] = []
    form_of: list[FormOf] = []
    for s in raw.get("senses", []):
        stags = s.get("tags", [])
        targets = s.get("form_of") or s.get("alt_of")
        if targets and ("form-of" in stags or "alt-of" in stags or s.get("form_of")):
            lemma = targets[0].get("word")
            if lemma:
                if pos == "v":
                    tag = tagmap.kaikki_form_tag(stags) or ""
                else:
                    tag = tagmap.kaikki_gender_number(stags) or ""
                form_of.append(FormOf(form=word, lemma=nfc(lemma), pos=pos, tag=tag))
            continue
        glosses = s.get("glosses") or s.get("raw_glosses")
        if not glosses:
            continue
        gloss = glosses[-1].strip()
        examples = [
            (nfc(e["text"]), e.get("english") or e.get("translation"))
            for e in s.get("examples", [])
            if e.get("text") and (e.get("english") or e.get("translation"))
        ][:3]
        senseid = (s.get("senseid") or [None])[0]
        wikidata = (s.get("wikidata") or [None])[0]
        senses.append(Sense(gloss=gloss, tags=[t for t in stags if t != "form-of"], examples=examples,
                            senseid=senseid, wikidata=wikidata))

    if not senses:
        return None, form_of

    entry = Entry(headword=word, pos=pos, etymology=str(raw.get("etymology_number", "") or ""),
                  gender=_gender(raw) if pos in ("n", "adj", "propn") else None,
                  ipa=_ipa(raw), senses=senses)
    if pos == "v":
        entry.auxiliary = _auxiliary(raw)
    seen: set[tuple[str, str]] = set()
    for f in raw.get("forms", []):
        form = _clean_form(f.get("form", ""))
        if not form:
            continue
        ftags = f.get("tags", [])
        if pos == "v":
            tag = tagmap.kaikki_form_tag(ftags)
            if tag is None:
                continue
        elif pos in ("n", "adj", "propn", "art", "det", "pron"):
            tag = tagmap.kaikki_gender_number(ftags)
            if tag is None and "plural" in ftags:
                tag = (entry.gender + "p") if entry.gender in ("m", "f") else ""
            if tag is None:
                continue
            if "plural" in ftags and entry.plural is None:
                entry.plural = form
        else:
            continue
        if (form, tag) not in seen:
            seen.add((form, tag))
            entry.forms.append((form, tag))
    return entry, form_of


def read(lines: Iterable[dict]) -> tuple[list[Entry], list[FormOf]]:
    entries: list[Entry] = []
    forms: list[FormOf] = []
    for raw in lines:
        entry, fo = parse(raw)
        if entry:
            entries.append(entry)
        forms.extend(fo)
    return entries, forms
