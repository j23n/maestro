"""
Generate structured grammar points (GPs) and communicative functions (CFs) from
extracted Goethe-Institut PDF text using LLM-assisted parsing.

Reads cleaned text files in data/<lang>/extracted/ and uses Claude to
parse them into structured YAML (GPs) and JSON (CFs) matching the existing data
schema.

Sources and outputs:
  Grammatik text        → grammar_points.yaml  (GPs)
  Sprachhandlungen text → comm_functions.json   (CFs)
  Strategien text       → comm_functions.json   (CFs)
  Notionen text         → comm_functions.json   (CFs)

Usage:
  uv run python scripts/data/generate_inventory.py                     # de GPs A1
  uv run python scripts/data/generate_inventory.py --type cfs          # de CFs A1
  uv run python scripts/data/generate_inventory.py --type all --level all
  uv run python scripts/data/generate_inventory.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import anthropic
import httpx
import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"

# ---------------------------------------------------------------------------
# Language configuration
# ---------------------------------------------------------------------------

GP_CATEGORIES_DE = {
    "verb",
    "nomen",
    "artikelwoerter_pronomen",
    "adjektiv",
    "praeposition",
    "syntax",
    "wortbildung",
}

CF_MACRO_CATEGORIES_DE = {
    # Sprachhandlungen
    "informationsaustausch",
    "bewertung_kommentar",
    "gefuehlsausdruck",
    "handlungsregulierung",
    "soziale_konventionen",
    # Strategien
    "redeorganisation",
    "verstaendnissicherung",
    "kompensation",
    # Notionen
    "notionen",
}

LANGUAGES = {
    "de": {
        "gp_sources": {
            "A1": [("grammatik", "A1_grammatik.txt")],
            "A2": [("grammatik", "A2_grammatik.txt")],
        },
        "cf_sources": {
            "A1": [
                ("sprachhandlungen", "A1_sprachhandlungen.txt"),
                ("strategien", "A1_strategien.txt"),
                ("notionen", "A1_notionen.txt"),
            ],
            "A2": [
                ("sprachhandlungen", "A2_sprachhandlungen.txt"),
                ("strategien", "A2_strategien.txt"),
                ("notionen", "A2_notionen.txt"),
            ],
        },
        "gp_categories": GP_CATEGORIES_DE,
        "cf_macro_categories": CF_MACRO_CATEGORIES_DE,
        "gp_output": "grammar_points.yaml",
        "cf_output": "comm_functions.json",
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

A2_GRAMMAR_NOTE = (
    "This document covers BOTH A1 and A2 grammar. Entries WITHOUT a star (*) are A1 "
    "(already covered). Entries WITH a star (*) are A2-specific additions. "
    "ONLY output the A2-specific (starred) entries — do not duplicate A1 entries."
)

A2_CF_NOTE = (
    "This document covers BOTH A1 (Start Deutsch 1) and A2 (Start Deutsch 2) content "
    "in a two-column layout. The left column is A1 (SD1) and the right column is A2 "
    "(SD2). pdftotext has linearised these columns imperfectly. "
    "ONLY output the A2-specific entries — do not duplicate A1 entries. "
    "A2 entries are typically in the right column or marked as SD2-specific additions."
)

GP_SYSTEM_PROMPT = """\
You are a German linguistics expert helping build a structured grammar inventory \
for a language learning app. You will receive raw text extracted (via pdftotext) \
from a Goethe-Institut Prüfungsziele PDF. The original PDF has a two-column \
layout: the left column describes grammar structures, the right column gives \
German example sentences. pdftotext has linearised these columns imperfectly, \
so you need to use your knowledge of German grammar to reconstruct which \
examples belong to which structures.

Your task: parse this text into a JSON array of grammar point objects."""

GP_USER_PROMPT = """\
Below is the extracted grammar inventory text from the Goethe-Institut \
Prüfungsziele/Testbeschreibung for level {level}. {level_note}

Parse this into a JSON array of grammar point objects. Each object should represent \
ONE distinct, teachable grammar point (not a category heading).

For each grammar point, produce:
{{
  "code": "<≤20 char snake_case English code, e.g. present_tense, def_article, modal_verb>",
  "label": "<German grammar label, 3-8 words, e.g. Präsens aller Verben>",
  "cefr_level": "{level}",
  "category": "<one of: verb, nomen, artikelwoerter_pronomen, adjektiv, praeposition, syntax, wortbildung>",
  "subcategory": "<subcategory from the PDF, e.g. Tempus, Modus, Kasus, temporal, lokal, etc.>",
  "description": "<1-2 sentence English description of what this grammar point covers>",
  "examples": ["<2-4 example sentences from the PDF text>"],
  "source_note": "<brief note about what the PDF says, e.g. 'Präsens aller Verben der Wortliste'>"
}}

Important guidelines:
- Each entry should be a single teachable grammar concept, not a section heading
- The "code" must be ≤20 chars, snake_case, English, unique across all entries
- Use the PDF's own category structure (Verb, Nomen, etc.) mapped to the lowercase versions listed above
- "artikelwoerter_pronomen" covers both Artikelwörter and Pronomen sections
- Include examples from the PDF text where available
- For the A2 level: items marked with * are A2-specific additions (items without * are A1 and already covered)
- Aim for granularity similar to: one entry per distinct tense, one per case, one per preposition group, etc.
- Do NOT include the introductory paragraph about grammar pedagogy
- Do NOT create entries for the overview/table of contents at the start

Output ONLY valid JSON (no markdown fences, no commentary).

--- EXTRACTED TEXT ---
{text}
--- END ---"""

CF_SYSTEM_PROMPT = """\
You are a German linguistics expert helping build a structured communicative \
functions inventory for a language learning app. You will receive raw text \
extracted (via pdftotext) from a Goethe-Institut Prüfungsziele PDF. \
The original PDF may have a two-column layout that pdftotext has linearised \
imperfectly — use your knowledge of German to reconstruct the structure.

Your task: parse this text into a JSON array of communicative function objects.

CRITICAL: Your output must be valid JSON. Do NOT use German quotation marks \
(„ ") inside string values — replace them with single quotes or remove them. \
Escape any literal double quotes inside strings with a backslash."""

CF_USER_PROMPTS = {
    "sprachhandlungen": """\
Below is the extracted Sprachhandlungen (speech acts / communicative functions) \
inventory from the Goethe-Institut Prüfungsziele for level {level}. {level_note}

Parse this into a JSON array of communicative function objects. Each object should \
represent ONE distinct communicative function (speech act).

For each function, produce:
{{
  "code": "<≤20 char snake_case English code, e.g. greet, ask_name, express_joy>",
  "label": "<German label, 2-6 words, e.g. Begrüßung, Sich vorstellen>",
  "macro_category": "<one of: informationsaustausch, bewertung_kommentar, gefuehlsausdruck, handlungsregulierung, soziale_konventionen>",
  "cefr_level": "{level}",
  "patterns": ["<2-6 key phrases/sentence patterns from the PDF>"],
  "examples": ["<2-4 complete example exchanges from the PDF>"],
  "description": "<1-2 sentence English description of this communicative function>"
}}

Important guidelines:
- Each entry should be a single communicative function, not a section heading
- Map to the correct macro_category based on the PDF's section structure:
  - Informationsaustausch: benennen, beschreiben, erklären, berichten, Mitteilung, Nachfrage, etc.
  - Bewertung, Kommentar: Meinung, Zufriedenheit, Gefallen, Interesse, Billigung, Zustimmung, Wunsch, Vorlieben, etc.
  - Gefühlsausdruck: Freude, Neigung, Gelassenheit, Mitgefühl, Erstaunen, Hoffnung, Sorge, etc.
  - Handlungsregulierung: Bitte, Bestätigung, Hilfe, Bestellung, Rat, Erlaubnis, Vorschlag, Verabredung, Einladung, etc.
  - Soziale Konventionen: Kontaktaufnahme, grüßen, vorstellen, Befinden, gute Wünsche, Gratulation, Dank, Entschuldigung, Verabschiedung, etc.
- "patterns" should capture the key PHRASES (shorter, more formulaic)
- "examples" should capture full SENTENCES/EXCHANGES showing the function in context
- Do NOT include the introductory paragraph
- Do NOT create entries for the table of contents at the start

Output ONLY valid JSON (no markdown fences, no commentary).

--- EXTRACTED TEXT ---
{text}
--- END ---""",
    "strategien": """\
Below is the extracted Strategien (communication strategies) inventory from the \
Goethe-Institut Prüfungsziele for level {level}. {level_note}

Parse this into a JSON array of communicative function objects. Each object should \
represent ONE distinct communication strategy.

For each strategy, produce:
{{
  "code": "<≤20 char snake_case English code, e.g. open_conv, ask_repeat, self_correct>",
  "label": "<German label, 2-6 words, e.g. eine Äußerung einleiten>",
  "macro_category": "<one of: redeorganisation, verstaendnissicherung, kompensation>",
  "cefr_level": "{level}",
  "patterns": ["<2-6 key phrases/patterns from the PDF>"],
  "examples": ["<2-4 complete example sentences from the PDF>"],
  "description": "<1-2 sentence English description of this strategy>"
}}

Important guidelines:
- Map to the correct macro_category:
  - Redeorganisation: Äußerung einleiten/abschließen, um das Wort bitten, Zuhören signalisieren, zum Sprechen auffordern, etc.
  - Verständnissicherung: Verständnishilfen anbieten/bitten, Rückfragen, buchstabieren, etc.
  - Kompensation: Synonyme verwenden, Selbstkorrektur, ausdrücken dass man ein Wort nicht kennt, etc.
- Do NOT include the introductory paragraph about strategies
- Include both the strategy description and example phrases

Output ONLY valid JSON (no markdown fences, no commentary).

--- EXTRACTED TEXT ---
{text}
--- END ---""",
    "notionen": """\
Below is the extracted Allgemeine Begriffe / Notionen (general notions) inventory \
from the Goethe-Institut Prüfungsziele for level {level}. {level_note}

These notions describe general communicative capabilities (expressing existence, \
quantity, time, space, etc.) — they are communicative functions, not grammar structures.

Parse this into a JSON array of communicative function objects. Each object should \
represent ONE distinct notional function.

For each function, produce:
{{
  "code": "<≤20 char snake_case English code, e.g. expr_existence, expr_time, expr_place>",
  "label": "<German label, 2-6 words, e.g. Existenz ausdrücken, Ort angeben>",
  "macro_category": "notionen",
  "cefr_level": "{level}",
  "patterns": ["<2-6 key phrases/patterns from the PDF>"],
  "examples": ["<2-4 complete example sentences from the PDF>"],
  "description": "<1-2 sentence English description of this notional function>"
}}

Important guidelines:
- Each entry should be a distinct notional function (e.g. expressing existence, expressing quantity, expressing location)
- Keep granularity at the sub-heading level (e.g. Ort, Herkunft, Richtung — NOT the whole "Raum definieren" section as one entry)
- Include the German example sentences from the PDF
- Do NOT include the introductory paragraph

Output ONLY valid JSON (no markdown fences, no commentary).

--- EXTRACTED TEXT ---
{text}
--- END ---""",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data_dir(language: str) -> Path:
    return DATA_ROOT / language


def _read_source(language: str, filename: str) -> str:
    path = _data_dir(language) / "extracted" / filename
    if not path.exists():
        logger.error(f"Extracted text not found: {path}")
        logger.error("Run: uv run python scripts/data/extract_goethe_pdfs.py")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def _sanitize_json_text(text: str) -> str:
    """Replace German/French quotation marks inside JSON strings that break parsing.

    Characters like „ (U+201E) and " (U+201C) can cause issues when pdftotext
    output is embedded in JSON string values — sometimes the LLM mixes them
    with ASCII double quotes.
    """
    # Replace typographic quotes with simple escaped alternatives
    text = text.replace("\u201e", "'")  # „ → '
    text = text.replace("\u201c", "'")  # " → '
    text = text.replace("\u201d", "'")  # " → '
    text = text.replace("\u201a", "'")  # ‚ → '
    text = text.replace("\u2018", "'")  # ' → '
    text = text.replace("\u2019", "'")  # ' → '
    text = text.replace("\u00ab", "'")  # « → '
    text = text.replace("\u00bb", "'")  # » → '
    return text


def _parse_response(raw: str) -> list[dict]:
    """Parse the LLM JSON response, handling markdown fences, quotes, and truncation."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]

    # First attempt: parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Second attempt: sanitize typographic quotes
    sanitized = _sanitize_json_text(text)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Third attempt: recover truncated JSON array
    for t in (sanitized, text):
        last_brace = t.rfind("}")
        if last_brace > 0:
            truncated = t[: last_brace + 1] + "\n]"
            try:
                result = json.loads(truncated)
                logger.warning(
                    f"Recovered truncated JSON ({len(result)} entries parsed)"
                )
                return result
            except json.JSONDecodeError:
                pass

    # Give up — raise with original text for debugging
    return json.loads(text)


def _sanitize_code(code: str, max_len: int = 20) -> str:
    """Normalise a code: lowercase, strip non-alnum, truncate."""
    code = code.lower().strip()
    code = re.sub(r"[^a-z0-9_]", "_", code)
    code = re.sub(r"_+", "_", code).strip("_")
    return code[:max_len].rstrip("_")


def _call_llm(
    client: anthropic.Anthropic,
    system: str,
    user: str,
    max_tokens: int = 16384,
) -> str:
    """Send a single LLM request and return the text response."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# GP generation
# ---------------------------------------------------------------------------


def _validate_gp(gp: dict, idx: int, valid_cats: set[str]) -> list[str]:
    warnings = []
    code = gp.get("code", "")
    if len(code) > 20:
        warnings.append(f"  GP #{idx}: code '{code}' exceeds 20 chars ({len(code)})")
    if not code.replace("_", "").isalnum():
        warnings.append(f"  GP #{idx}: code '{code}' has invalid characters")
    cat = gp.get("category", "")
    if cat not in valid_cats:
        warnings.append(f"  GP #{idx}: unknown category '{cat}'")
    if not gp.get("label"):
        warnings.append(f"  GP #{idx}: missing label")
    return warnings


def generate_gps(
    language: str,
    level: str,
    client: anthropic.Anthropic,
    dry_run: bool = False,
) -> list[dict]:
    """Generate grammar points for a single CEFR level."""
    config = LANGUAGES[language]
    sources = config["gp_sources"].get(level, [])
    if not sources:
        logger.warning(f"No GP sources for {language}/{level}")
        return []

    all_gps: list[dict] = []

    for source_type, filename in sources:
        logger.info(f"Generating GPs from {filename} ({level})...")
        text = _read_source(language, filename)

        level_note = A2_GRAMMAR_NOTE if level == "A2" else ""
        prompt = GP_USER_PROMPT.format(level=level, level_note=level_note, text=text)
        raw = _call_llm(client, GP_SYSTEM_PROMPT, prompt)
        logger.debug(f"Raw GP response length: {len(raw)} chars")

        try:
            gps = _parse_response(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GP response as JSON: {e}")
            logger.error(f"Raw (first 500 chars): {raw[:500]}")
            continue

        if not isinstance(gps, list):
            logger.error(f"Expected JSON array, got {type(gps).__name__}")
            continue

        for gp in gps:
            gp["code"] = _sanitize_code(gp.get("code", ""))

        # Validate
        codes_seen: set[str] = set()
        for i, gp in enumerate(gps):
            for w in _validate_gp(gp, i, config["gp_categories"]):
                logger.warning(w)
            code = gp.get("code", "")
            if code in codes_seen:
                logger.warning(f"  GP #{i}: duplicate code '{code}'")
            codes_seen.add(code)

        logger.info(f"  Generated {len(gps)} GPs from {filename}")
        all_gps.extend(gps)

    if dry_run:
        print(json.dumps(all_gps, indent=2, ensure_ascii=False))

    return all_gps


# ---------------------------------------------------------------------------
# CF generation
# ---------------------------------------------------------------------------


def _validate_cf(cf: dict, idx: int, valid_cats: set[str]) -> list[str]:
    warnings = []
    code = cf.get("code", "")
    if len(code) > 20:
        warnings.append(f"  CF #{idx}: code '{code}' exceeds 20 chars ({len(code)})")
    if not code.replace("_", "").isalnum():
        warnings.append(f"  CF #{idx}: code '{code}' has invalid characters")
    cat = cf.get("macro_category", "")
    if cat not in valid_cats:
        warnings.append(f"  CF #{idx}: unknown macro_category '{cat}'")
    if not cf.get("label"):
        warnings.append(f"  CF #{idx}: missing label")
    return warnings


def generate_cfs(
    language: str,
    level: str,
    client: anthropic.Anthropic,
    dry_run: bool = False,
) -> list[dict]:
    """Generate communicative functions for a single CEFR level."""
    config = LANGUAGES[language]
    sources = config["cf_sources"].get(level, [])
    if not sources:
        logger.warning(f"No CF sources for {language}/{level}")
        return []

    all_cfs: list[dict] = []

    for source_type, filename in sources:
        logger.info(f"Generating CFs from {filename} ({source_type}, {level})...")
        text = _read_source(language, filename)

        prompt_template = CF_USER_PROMPTS.get(source_type)
        if not prompt_template:
            logger.error(f"No CF prompt for source type '{source_type}'")
            continue

        level_note = A2_CF_NOTE if level == "A2" else ""
        prompt = prompt_template.format(level=level, level_note=level_note, text=text)
        raw = _call_llm(client, CF_SYSTEM_PROMPT, prompt)
        logger.debug(f"Raw CF response length: {len(raw)} chars")

        try:
            cfs = _parse_response(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CF response as JSON: {e}")
            logger.error(f"Raw (first 500 chars): {raw[:500]}")
            continue

        if not isinstance(cfs, list):
            logger.error(f"Expected JSON array, got {type(cfs).__name__}")
            continue

        # Sanitize codes
        for cf in cfs:
            cf["code"] = _sanitize_code(cf.get("code", ""))

        # Validate
        codes_seen: set[str] = set()
        for i, cf in enumerate(cfs):
            for w in _validate_cf(cf, i, config["cf_macro_categories"]):
                logger.warning(w)
            code = cf.get("code", "")
            if code in codes_seen:
                logger.warning(f"  CF #{i}: duplicate code '{code}'")
            codes_seen.add(code)

        logger.info(f"  Generated {len(cfs)} CFs from {filename}")
        all_cfs.extend(cfs)

    if dry_run:
        print(json.dumps(all_cfs, indent=2, ensure_ascii=False))

    return all_cfs


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _gp_to_yaml(gp: dict) -> dict:
    """Convert LLM output to grammar_points.yaml schema."""
    return {
        "code": gp["code"],
        "cefr_level": gp["cefr_level"],
        "category": gp["category"],
        "subcategory": gp.get("subcategory", ""),
        "label": gp["label"],
        "description": gp.get("description", ""),
        "examples": gp.get("examples", []),
        "source_note": gp.get("source_note", ""),
        "explanations": {},
    }


def _cf_to_json(cf: dict) -> dict:
    """Convert LLM output to comm_functions.json schema."""
    return {
        "code": cf["code"],
        "label": cf["label"],
        "macro_category": cf["macro_category"],
        "cefr_level": cf["cefr_level"],
        "patterns": cf.get("patterns", []),
        "examples": cf.get("examples", []),
        "description": cf.get("description", ""),
    }


def _write_gps(gps: list[dict], language: str) -> None:
    out_path = _data_dir(language) / LANGUAGES[language]["gp_output"]
    yaml_entries = [_gp_to_yaml(gp) for gp in gps]

    # Merge with existing
    if out_path.exists():
        with open(out_path) as f:
            existing = yaml.safe_load(f) or []
        existing_codes = {e["code"] for e in existing}
        new_entries = [e for e in yaml_entries if e["code"] not in existing_codes]
        if new_entries:
            existing.extend(new_entries)
            logger.info(
                f"Added {len(new_entries)} new GPs to existing {len(existing) - len(new_entries)}"
            )
        else:
            logger.info("No new GP entries to add (all codes already exist)")
        yaml_entries = existing

    with open(out_path, "w") as f:
        yaml.dump(
            yaml_entries, f, default_flow_style=False, allow_unicode=True, width=200
        )
    logger.info(f"Wrote {len(yaml_entries)} GPs to {out_path}")


def _write_cfs(cfs: list[dict], language: str) -> None:
    out_path = _data_dir(language) / LANGUAGES[language]["cf_output"]
    json_entries = [_cf_to_json(cf) for cf in cfs]

    # Merge with existing
    if out_path.exists():
        with open(out_path) as f:
            existing = json.load(f)
        existing_codes = {e["code"] for e in existing}
        new_entries = [e for e in json_entries if e["code"] not in existing_codes]
        if new_entries:
            existing.extend(new_entries)
            logger.info(
                f"Added {len(new_entries)} new CFs to existing {len(existing) - len(new_entries)}"
            )
        else:
            logger.info("No new CF entries to add (all codes already exist)")
        json_entries = existing

    with open(out_path, "w") as f:
        json.dump(json_entries, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info(f"Wrote {len(json_entries)} CFs to {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate structured grammar points and communicative functions from extracted text"
    )
    parser.add_argument(
        "--language",
        choices=list(LANGUAGES.keys()),
        default="de",
        help="Target language (default: de)",
    )
    parser.add_argument(
        "--type",
        choices=["gps", "cfs", "all"],
        default="gps",
        help="What to generate (default: gps)",
    )
    parser.add_argument(
        "--level",
        choices=["A1", "A2", "all"],
        default="A1",
        help="CEFR level (default: A1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout instead of writing files",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    load_dotenv()

    config = LANGUAGES[args.language]
    all_levels = sorted(
        set(list(config["gp_sources"].keys()) + list(config["cf_sources"].keys()))
    )
    levels = all_levels if args.level == "all" else [args.level]

    client = anthropic.Anthropic(
        timeout=httpx.Timeout(300.0, connect=10.0),
        max_retries=2,
    )

    # Generate GPs
    if args.type in ("gps", "all"):
        all_gps: list[dict] = []
        for level in levels:
            gps = generate_gps(args.language, level, client, dry_run=args.dry_run)
            all_gps.extend(gps)

        if not args.dry_run:
            if all_gps:
                _write_gps(all_gps, args.language)
            else:
                logger.warning("No grammar points generated")

    # Generate CFs
    if args.type in ("cfs", "all"):
        all_cfs: list[dict] = []
        for level in levels:
            cfs = generate_cfs(args.language, level, client, dry_run=args.dry_run)
            all_cfs.extend(cfs)

        if not args.dry_run:
            if all_cfs:
                _write_cfs(all_cfs, args.language)
            else:
                logger.warning("No communicative functions generated")


if __name__ == "__main__":
    main()
