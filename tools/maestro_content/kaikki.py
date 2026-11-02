"""Read kaikki.org (wiktextract) Italian or German JSONL into plain records.

Only what the app uses is kept: headword, part of speech, gender, plural, IPA, auxiliary,
senses (gloss, tags, examples, wiktextract senseid, Wikidata QID) and inflected forms.
Entries whose senses are all form-of become form records pointing at their lemma.
German entries keep their capitals and get German form tags and case tags (tags.py, HANDOFF.md 6.5).
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


UNTAGGED = "?"
"""A German form-of row whose tags name no case or form: build_db skips it rather than store it as a headword."""


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


def parse(raw: dict, language: str = "it") -> tuple[Entry | None, list[FormOf]]:
    if language == "de":
        return parse_de(raw)
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


# --- German ------------------------------------------------------------------------------

def _gender_de(raw: dict) -> str | None:
    """m, f, n, or several letters (mn) for a noun with more than one gender."""
    found: list[str] = []
    for ht in raw.get("head_templates", []):
        if not ht.get("name", "").startswith("de-"):
            continue
        args = ht.get("args", {})
        for key in ("g", "g2", "1"):
            g = (args.get(key) or "").split(",")[0].strip()
            g = g.split("-")[0]
            if g in ("m", "f", "n") and g not in found:
                found.append(g)
    if not found:
        tags = set(raw.get("tags", []))
        found = [g for x, g in (("masculine", "m"), ("feminine", "f"), ("neuter", "n")) if x in tags]
    return "".join(found) or None


_AUX_DE_RE = re.compile(r"auxiliary (haben|sein)(?: or (haben|sein))?")


def _auxiliary_de(raw: dict) -> str | None:
    found = {f["form"] for f in raw.get("forms", [])
             if "auxiliary" in f.get("tags", []) and f.get("form") in ("haben", "sein")}
    for ht in raw.get("head_templates", []):
        m = _AUX_DE_RE.search(ht.get("expansion", ""))
        if m:
            found.update(x for x in m.groups() if x)
    if not found:
        return None
    return "both" if len(found) == 2 else found.pop()


def _form_tags_de(stags: list[str], pos: str, gender: str | None) -> list[str]:
    if pos == "v":
        return tagmap.kaikki_verb_tags_de(stags)
    if pos in ("n", "adj", "art", "det", "pron", "num"):
        return tagmap.kaikki_case_tags_de(stags, gender, pos)
    return []


def parse_de(raw: dict) -> tuple[Entry | None, list[FormOf]]:
    if raw.get("lang_code") != "de":
        return None, []
    pos = POS.get(raw.get("pos", ""))
    word = raw.get("word")
    if not pos or not word:
        return None, []
    word = nfc(word)
    gender = _gender_de(raw) if pos in ("n", "propn") else None

    senses: list[Sense] = []
    form_of: list[FormOf] = []
    for s in raw.get("senses", []):
        stags = s.get("tags", [])
        targets = s.get("form_of") or s.get("alt_of")
        if targets and ("form-of" in stags or "alt-of" in stags or s.get("form_of")):
            lemma = targets[0].get("word")
            if lemma:
                # The lemma's gender isn't known here: "?" leaves it to build_db (gen.s becomes gen.ns).
                found = _form_tags_de([t for t in stags if t != "form-of"], pos, "?")
                if not found:
                    # A spelling variant is the headword again. A form-of sense whose tags name no form
                    # (dem tagged only "definite") is UNTAGGED, which build_db counts and skips.
                    found = [UNTAGGED if s.get("form_of") and pos != "v" else ""]
                form_of.extend(FormOf(form=word, lemma=nfc(lemma), pos=pos, tag=tag) for tag in found)
            continue
        glosses = s.get("glosses") or s.get("raw_glosses")
        if not glosses:
            continue
        examples = [
            (nfc(e["text"]), e.get("english") or e.get("translation"))
            for e in s.get("examples", [])
            if e.get("text") and (e.get("english") or e.get("translation"))
        ][:3]
        senses.append(Sense(gloss=glosses[-1].strip(), tags=[t for t in stags if t != "form-of"],
                            examples=examples, senseid=(s.get("senseid") or [None])[0],
                            wikidata=(s.get("wikidata") or [None])[0]))
    if not senses:
        return None, form_of

    entry = Entry(headword=word, pos=pos, etymology=str(raw.get("etymology_number", "") or ""),
                  gender=gender, ipa=_ipa(raw), senses=senses)
    if pos == "v":
        entry.auxiliary = _auxiliary_de(raw)
    seen: set[tuple[str, str]] = set()
    for f in raw.get("forms", []):
        form = _clean_form(f.get("form", ""))
        if not form:
            continue  # separated forms (rufe an) and compound tenses have a space; the app joins them
        for tag in _form_tags_de(f.get("tags", []), pos, gender):
            if pos == "n" and tag.startswith("nom.pl") and entry.plural is None:
                entry.plural = form
            if (form, tag) not in seen:
                seen.add((form, tag))
                entry.forms.append((form, tag))
    if pos == "n" and entry.plural is None:
        # A head-line plural with tags the case mapping rejects (plural, uncommon) still names the plural.
        entry.plural = next((_clean_form(f.get("form", "")) for f in raw.get("forms", [])
                             if "plural" in f.get("tags", []) and not set(f.get("tags", [])) & _CASES), None)
    return entry, form_of


_CASES = {"nominative", "accusative", "dative", "genitive"}


def read(lines: Iterable[dict], language: str = "it") -> tuple[list[Entry], list[FormOf]]:
    entries: list[Entry] = []
    forms: list[FormOf] = []
    for raw in lines:
        entry, fo = parse(raw, language)
        if entry:
            entries.append(entry)
        forms.extend(fo)
    return entries, forms
