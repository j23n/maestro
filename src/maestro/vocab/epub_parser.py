"""
EPUB → TEI Lex-0 parser for the dizionario italiano di base.

Run with:  python -m maestro.vocab.epub_parser
Outputs:   data/dizionario_it_lex0.xml

Also provides parse_epub() → {epub_by_form, epub_by_lemma} for direct import
by the ingest script (avoids re-parsing XML).
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup, NavigableString, Tag

from maestro.utils import data_dir

logger = logging.getLogger(__name__)

_DATA_DIR = data_dir("it")
EPUB_DIR = _DATA_DIR / "dizionario_book" / "OEBPS" / "Text"
OUTPUT_XML = _DATA_DIR / "dizionario_it_lex0.xml"

TEI_NS = "http://www.tei-c.org/ns/1.0"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ParsedSense:
    definition: str = ""
    examples: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    pos: Optional[str] = None  # only if different from entry-level POS
    style: Optional[str] = None  # "figurato", "aulico"


@dataclass
class ParsedEntry:
    entry_id: str
    headword: str
    hyph: Optional[str]
    pos_abbrev: str
    senses: list[ParsedSense] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_entry(p_tag: Tag) -> Optional[ParsedEntry]:
    """Parse a single <p class="lemma"> element into a ParsedEntry."""
    entry_id = p_tag.get("id", "")
    if not entry_id.startswith("LM-"):
        return None

    # Primary headword comes from span.lemma or span.lemma_straniero.
    # Entries that start with only span.lemma_variante_grigio are cross-references → skip.
    primary = p_tag.find("span", class_="lemma") or p_tag.find(
        "span", class_="lemma_straniero"
    )
    if primary is None:
        return None

    headword = primary.get_text().strip()
    if not headword:
        return None

    # Syllabization: first sillabazione span, strip brackets.
    hyph: Optional[str] = None
    sill = p_tag.find("span", class_="sillabazione")
    if sill:
        hyph = sill.get_text().strip().strip("[]")

    entry_pos, senses = _parse_body(p_tag)
    if entry_pos is None:
        return None  # No POS found (prefix entries, etc.) → skip

    return ParsedEntry(
        entry_id=entry_id,
        headword=headword,
        hyph=hyph,
        pos_abbrev=entry_pos,
        senses=senses,
    )


def _parse_body(p_tag: Tag) -> tuple[Optional[str], list[ParsedSense]]:
    """
    Walk children of a <p class="lemma"> and extract (entry_pos, senses).

    Strategy:
    - Skip header spans (lemma, apice, sillabazione).
    - Track bracket depth for [inflection notes] → skip their content.
    - The first <em> at bracket-depth 0 after the header → entry-level POS.
    - Sense boundaries: numbered sottolemma, sfumature ⬨, barra_verticale |.
    - categoria ⬧ either introduces a new POS section (same word) or a
      sub-entry with a different lemma (→ stop).
    - Synonyms/antonyms come from text nodes (or italic) after Ⓢ / Ⓒ markers.
    """
    entry_pos: Optional[str] = None
    senses: list[ParsedSense] = []

    # Mutable collector for the sense currently being built
    cur_def: list[str] = []
    cur_ex: list[str] = []
    cur_syn: list[str] = []
    cur_ant: list[str] = []
    cur_style: Optional[str] = None
    cur_pos: Optional[str] = None  # pos override for current section

    in_header = True  # True until we find the entry-level POS
    in_pos = False  # True while accumulating multi-part POS (e.g. s + m → s.m.)
    in_bracket = 0  # depth of [...] inflection notes
    collect_syn = False
    collect_ant = False
    stop = False  # set True when we hit a sub-entry we don't want
    after_categoria = False

    def _flush() -> None:
        nonlocal cur_def, cur_ex, cur_syn, cur_ant
        def_text = re.sub(r"\s+", " ", " ".join(cur_def)).strip().strip(":")
        if def_text or cur_ex:
            senses.append(
                ParsedSense(
                    definition=def_text,
                    examples=list(cur_ex),
                    synonyms=list(cur_syn),
                    antonyms=list(cur_ant),
                    style=cur_style,
                    pos=cur_pos if cur_pos and cur_pos != entry_pos else None,
                )
            )
        cur_def.clear()
        cur_ex.clear()
        cur_syn.clear()
        cur_ant.clear()

    def _new_sense() -> None:
        nonlocal collect_syn, collect_ant
        _flush()
        collect_syn = False
        collect_ant = False

    for child in p_tag.children:
        if stop:
            break

        # ── Text node ──────────────────────────────────────────────────────
        if isinstance(child, NavigableString):
            text = str(child)

            # Extract only the segments outside [...] brackets, updating depth.
            outside: list[str] = []
            depth = in_bracket
            seg: list[str] = []
            for ch in text:
                if ch == "[":
                    if depth == 0 and seg:
                        outside.append("".join(seg))
                        seg = []
                    depth += 1
                elif ch == "]":
                    depth = max(0, depth - 1)
                else:
                    if depth == 0:
                        seg.append(ch)
            if seg:
                outside.append("".join(seg))
            in_bracket = depth

            if in_header:
                continue  # ignore text in header area

            if in_pos:
                outside_text = "".join(outside)
                non_sep = re.sub(r"[\s./\-]", "", outside_text)
                if not non_sep:
                    continue  # pure separator — skip
                # Single lowercase letter = gender/class suffix in plain text (e.g. "m", "f")
                if len(non_sep) == 1 and non_sep.isalpha() and non_sep.islower():
                    sep = "" if entry_pos.endswith(".") else "."
                    entry_pos += sep + non_sep
                    cur_pos = entry_pos
                    continue
                # Real text means the POS region is over; fall through to collect it
                in_pos = False
                _new_sense()

            for seg_text in outside:
                seg_stripped = seg_text.strip()
                if not seg_stripped:
                    continue
                if collect_syn:
                    cur_syn.extend(
                        s.strip().rstrip(".:,;()")
                        for s in re.split(r"[,;]", seg_stripped)
                        if s.strip()
                    )
                    collect_syn = False
                elif collect_ant:
                    cur_ant.extend(
                        a.strip().rstrip(".:,;()")
                        for a in re.split(r"[,;]", seg_stripped)
                        if a.strip()
                    )
                    collect_ant = False
                else:
                    # Skip text that's only punctuation (e.g. ";" between examples)
                    if re.search(r"[^\W\d_]", seg_stripped, re.UNICODE):
                        cur_def.append(seg_stripped)
            continue

        # ── Tag node ────────────────────────────────────────────────────────
        if not isinstance(child, Tag):
            continue

        tag = child.name
        classes = child.get("class") or []
        cls = classes[0] if classes else ""

        # ── POS accumulation (after first <em> found, before body begins) ──────
        if in_pos:
            if tag == "em" and in_bracket == 0:
                em_text = child.get_text().strip()
                if em_text:
                    sep = "" if entry_pos.endswith(".") else "."
                    entry_pos += sep + em_text
                    cur_pos = entry_pos
                continue
            # Any non-<em> tag ends the POS region
            in_pos = False
            _new_sense()
            # Fall through to normal tag processing

        # ── Inside header area ──────────────────────────────────────────────
        if in_header:
            if cls in (
                "lemma",
                "lemma_straniero",
                "lemma_variante_grigio",
                "apice",
                "sillabazione",
                "note",
                "manina",
            ):
                # Scan for brackets so in_bracket stays accurate even when the
                # opening [ is in a preceding text node and ] is inside this span
                # (common in sillabazione spans and loanword pronunciation notes).
                for ch in child.get_text():
                    if ch == "[":
                        in_bracket += 1
                    elif ch == "]":
                        in_bracket = max(0, in_bracket - 1)
                continue
            if tag == "em" and in_bracket == 0:
                # First root-level <em> = entry-level POS (normal format)
                entry_pos = child.get_text().strip()
                cur_pos = entry_pos
                in_header = False
                in_pos = True  # accumulate any further POS parts before body
            elif cls == "times_new_roman_italic" and in_bracket == 0:
                # Compact format: "s.m. definition text" all in one italic span.
                # Used for loanwords and simple single-sense entries.
                raw = child.get_text().strip()
                m = re.match(r"^(\S+\.)\s+(.*)", raw, re.DOTALL)
                if m:
                    entry_pos = m.group(1)
                    cur_pos = entry_pos
                    in_header = False
                    _new_sense()
                    rest = m.group(2).strip()
                    if rest and re.search(r"[^\W\d_]", rest, re.UNICODE):
                        cur_def.append(rest)
            continue  # still skip other elements while in header

        # ── Non-header area ─────────────────────────────────────────────────
        was_after_categoria = after_categoria
        after_categoria = False

        if tag == "em":
            em_text = child.get_text().strip()
            if in_bracket > 0:
                continue
            if was_after_categoria:
                # This em right after categoria ⬧ → new POS section for same word
                cur_pos = em_text
                continue
            if collect_syn:
                cur_syn.extend(s.strip() for s in em_text.split(",") if s.strip())
                collect_syn = False
                continue
            if collect_ant:
                cur_ant.extend(a.strip() for a in em_text.split(",") if a.strip())
                collect_ant = False
                continue
            if em_text:
                cur_ex.append(em_text)
            continue

        if tag in ("sup", "a"):
            continue  # apice superscripts and rimando links

        if tag != "span":
            continue

        if cls == "sottolemma":
            bold = child.get_text().strip()
            if re.match(r"^\d+$", bold):
                _new_sense()  # numbered sense boundary
            elif was_after_categoria:
                # Different lemma word after categoria → stop collecting
                _flush()
                stop = True
            else:
                _new_sense()  # inline sub-entry variant, treat as sense boundary
            continue

        if cls in ("sfumature", "barra_verticale"):
            _new_sense()
            continue

        if cls == "figurato":
            cur_style = "figurato"
            continue

        if cls == "aulico":
            cur_style = "aulico"
            continue

        if cls == "sinonimo":
            collect_syn = True
            collect_ant = False
            continue

        if cls == "contrario":
            collect_ant = True
            collect_syn = False
            continue

        if cls == "categoria":
            _new_sense()
            cur_style = None
            collect_syn = False
            collect_ant = False
            after_categoria = True
            continue

        # Other spans (note, manina, rimando, Trattino_facoltativo, etc.) → ignore

    _flush()
    return entry_pos, senses


# ---------------------------------------------------------------------------
# Top-level parse
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def parse_epub() -> dict:
    """
    Parse all content chapters from dizionario_book/.

    Returns a dict with two indices:
        epub_by_form:  {headword.lower(): [ParsedEntry, ...]}
        epub_by_lemma: {spacy_lemma:      ParsedEntry}   (populated lazily by ingest)
    """
    if not EPUB_DIR.exists():
        raise FileNotFoundError(f"EPUB directory not found: {EPUB_DIR}")

    # Content chapters: *_c*.xhtml (excludes fm/bm/cover)
    chapter_files = sorted(EPUB_DIR.glob("g*_c*.xhtml"))
    if not chapter_files:
        raise FileNotFoundError(f"No chapter files found in {EPUB_DIR}")

    epub_by_form: dict[str, list[ParsedEntry]] = {}
    total = 0
    skipped = 0

    for path in chapter_files:
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for p in soup.find_all("p", class_="lemma"):
            entry = _parse_entry(p)
            if entry is None:
                skipped += 1
                continue
            total += 1
            key = entry.headword.lower()
            epub_by_form.setdefault(key, []).append(entry)

    logger.info(
        f"Parsed {total} entries, skipped {skipped} from {len(chapter_files)} chapters"
    )
    print(f"  Parsed {total} entries, skipped {skipped}", file=sys.stderr)

    return {"epub_by_form": epub_by_form, "epub_by_lemma": {}}


# ---------------------------------------------------------------------------
# TEI Lex-0 XML output
# ---------------------------------------------------------------------------


def _make_tei(entries: dict[str, list[ParsedEntry]]) -> ET.ElementTree:
    ET.register_namespace("", TEI_NS)

    def el(parent, tag, **attrs):
        e = ET.SubElement(parent, f"{{{TEI_NS}}}{tag}", **attrs)
        return e

    root = ET.Element(f"{{{TEI_NS}}}TEI")

    # teiHeader (minimal)
    hdr = ET.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    fd = ET.SubElement(hdr, f"{{{TEI_NS}}}fileDesc")
    ti = ET.SubElement(fd, f"{{{TEI_NS}}}titleStmt")
    t = ET.SubElement(ti, f"{{{TEI_NS}}}title")
    t.text = "Dizionario italiano di base — TEI Lex-0"

    text = ET.SubElement(root, f"{{{TEI_NS}}}text")
    body = ET.SubElement(text, f"{{{TEI_NS}}}body")
    div = ET.SubElement(body, f"{{{TEI_NS}}}div", type="lexicon")
    div.set("{http://www.w3.org/XML/1998/namespace}lang", "it")

    all_entries = [e for group in entries.values() for e in group]
    for entry_data in sorted(all_entries, key=lambda e: e.entry_id):
        entry_el = ET.SubElement(div, f"{{{TEI_NS}}}entry")
        entry_el.set("{http://www.w3.org/XML/1998/namespace}id", entry_data.entry_id)

        # Form
        form_el = ET.SubElement(entry_el, f"{{{TEI_NS}}}form", type="lemma")
        orth = ET.SubElement(form_el, f"{{{TEI_NS}}}orth")
        orth.text = entry_data.headword
        if entry_data.hyph:
            hyph_el = ET.SubElement(form_el, f"{{{TEI_NS}}}hyph")
            hyph_el.text = entry_data.hyph

        # Entry-level gramGrp
        grp = ET.SubElement(entry_el, f"{{{TEI_NS}}}gramGrp")
        gram = ET.SubElement(grp, f"{{{TEI_NS}}}gram", type="pos")
        gram.text = entry_data.pos_abbrev

        # Senses
        for n, sense in enumerate(entry_data.senses, 1):
            s_el = ET.SubElement(entry_el, f"{{{TEI_NS}}}sense", n=str(n))

            if sense.pos and sense.pos != entry_data.pos_abbrev:
                s_grp = ET.SubElement(s_el, f"{{{TEI_NS}}}gramGrp")
                s_gram = ET.SubElement(s_grp, f"{{{TEI_NS}}}gram", type="pos")
                s_gram.text = sense.pos

            if sense.style:
                usg = ET.SubElement(s_el, f"{{{TEI_NS}}}usg", type="style")
                usg.text = sense.style

            if sense.definition:
                def_el = ET.SubElement(s_el, f"{{{TEI_NS}}}def")
                def_el.text = sense.definition

            for ex in sense.examples:
                cit = ET.SubElement(s_el, f"{{{TEI_NS}}}cit", type="example")
                q = ET.SubElement(cit, f"{{{TEI_NS}}}quote")
                q.text = ex

            for syn in sense.synonyms:
                xr = ET.SubElement(s_el, f"{{{TEI_NS}}}xr", type="synonymy")
                ref = ET.SubElement(xr, f"{{{TEI_NS}}}ref")
                ref.text = syn

            for ant in sense.antonyms:
                xr = ET.SubElement(s_el, f"{{{TEI_NS}}}xr", type="antonymy")
                ref = ET.SubElement(xr, f"{{{TEI_NS}}}ref")
                ref.text = ant

    ET.indent(root, space="  ")
    return ET.ElementTree(root)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("Parsing EPUB…")
    result = parse_epub()
    entries = result["epub_by_form"]

    total = sum(len(group) for group in entries.values())
    print(f"Writing TEI Lex-0 XML to {OUTPUT_XML}…")
    tree = _make_tei(entries)
    OUTPUT_XML.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(tree.getroot(), encoding="unicode").encode("utf-8")
    )
    print(f"Done. {total} entries written.")
