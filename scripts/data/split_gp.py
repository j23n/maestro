"""
Split omnibus GrammarPoint entries in grammar_points.yaml into individual GPs.

Two categories:
  - verbi:        codes listed in VERBI_CODES  → split description on ' - '
  - preposizioni: codes with ';' in unistr_label → split unistr_label on ';'

Each child GP inherits: cefr_level, category, unistr_code, source_url from parent.
unistr_label and description = the split item text.
code = auto-generated short code (≤10 chars), deduplicated.

Run:
    uv run python scripts/split_gp.py [--dry-run]
"""

from __future__ import annotations
import re
import sys

import yaml

YAML_PATH = "src/maestro/data/it/grammar_points.yaml"


class LiteralStr(str):
    pass


def _lit_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)

# Verbi codes whose descriptions contain ' - ' delimited bullets
VERBI_CODES = ["aux_reg_vb", "verbs_a2", "verbs_b1", "verbs_b2"]

# Italian stop-words to ignore when building a code slug
_STOP = {
    "la",
    "le",
    "il",
    "lo",
    "i",
    "gli",
    "un",
    "una",
    "uno",
    "dei",
    "del",
    "della",
    "delle",
    "degli",
    "di",
    "a",
    "ad",
    "da",
    "in",
    "con",
    "su",
    "per",
    "tra",
    "fra",
    "e",
    "ed",
    "o",
    "ma",
    "non",
    "ne",
    "se",
    "che",
    "è",
    "come",
    "es",
    "es.",
    "al",
    "ai",
    "agli",
    "alle",
    "all",
    "alla",
    "dal",
    "dai",
    "dagli",
    "dalle",
    "nel",
    "nella",
    "nelle",
    "negli",
    "nei",
    "sul",
    "sulla",
    "sulle",
    "sugli",
    "sui",
    "col",
    "coi",
    "uso",
    "usi",
    "proposizione",
    "proposizioni",
    "persona",
    "singolare",
    "plurale",
    "coniugazione",
    "attiva",
    "verbo",
    "verbi",
    "regolari",
    "irregolari",
    # common filler words
    "ripresa",
    "riprese",
    "esteso",
    "estesa",
    "introdotte",
    "introdotta",
    "introdotto",
    "ho",
    "mi",
    "ci",
    "vi",
    "si",
    "più",
    "meno",
    "solo",
    "anche",
}

# Preferred short slugs for common Italian grammar terms
_ABBREV = {
    # moods
    "indicativo": "ind",
    "congiuntivo": "cong",
    "condizionale": "cond",
    "imperativo": "imper",
    "gerundio": "ger",
    "infinito": "inf",
    "participio": "part",
    # tenses
    "presente": "pres",
    "passato": "pass",
    "imperfetto": "imperf",
    "futuro": "fut",
    "trapassato": "trpass",
    "remoto": "rem",
    "prossimo": "pros",
    "anteriore": "ant",
    "semplice": "simp",
    "semplici": "simp",
    # adjectives / types
    "modale": "mod",
    "modali": "mod",
    "temporale": "temp",
    "temporali": "temp",
    "causale": "caus",
    "causali": "caus",
    "finale": "fin",
    "finali": "fin",
    "nominale": "nom",
    "storico": "stor",
    "storica": "stor",
    "impersonale": "impers",
    "impersonali": "impers",
    "passivante": "passiv",
    "progressiva": "prog",
    "progressivo": "prog",
    "perifrastica": "prog",
    "passiva": "passv",
    "riflessivo": "refl",
    "riflessivi": "refl",
    "esortativo": "esor",
    "concordanza": "seq",
    # general
    "tempo": "temp",
    "tempi": "temp",
    "modo": "mod",
    "forma": "form",
    "valore": "val",
    "stato": "loc",
    "moto": "mv",
    # preposition semantics
    "distributivo": "distr",
    "partitivo": "part",
    "paragone": "comp",
    "comparativo": "comp",
    "argomento": "arg",
    "abbondanza": "abb",
    "appartenenza": "appar",
    "materia": "mat",
    "mezzo": "mez",
    "origine": "orig",
    "provenienza": "orig",
    "termine": "ind",
    "luogo": "loc",
    "qualità": "qual",
    "qualita": "qual",
    "quantità": "qnt",
    "quantita": "qnt",
    "agente": "agt",
    "denominazione": "den",
    "stima": "stim",
    "prezzo": "prz",
    "consecutiva": "cons",
    "consecutivo": "cons",
    "compagnia": "comp",
    "durata": "dur",
    "subordinata": "sub",
    "subordinate": "sub",
}


def _slugify(text: str) -> str:
    """Generate a ≤10 char snake_case slug from a descriptive text."""
    import unicodedata

    # Strip after comma or semicolon or 'es.' to remove examples
    text = re.split(r"[,;]|es\.", text)[0]
    # Remove parenthetical content
    text = re.sub(r"\(.*?\)", "", text)
    # Normalise accents → ASCII
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lower
    text = text.lower().strip()
    # Replace non-word chars
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()

    parts: list[str] = []
    for w in words:
        if w in _STOP:
            continue
        w = _ABBREV.get(w, w)
        parts.append(w[:6])  # cap each segment at 6 chars
        if len("_".join(parts)) >= 9:
            break

    slug = "_".join(parts)[:10].rstrip("_")
    return slug or "gp"


def _dedup(code: str, existing: set[str]) -> str:
    if code not in existing:
        return code
    base = code[:8].rstrip("_")
    n = 2
    while True:
        candidate = f"{base}_{n}"[:10]
        if candidate not in existing:
            return candidate
        n += 1


def split_gp(items: list[dict], dry_run: bool) -> list[dict]:
    existing_codes: set[str] = {i["code"] for i in items}
    to_remove: set[str] = set()
    new_gps: list[tuple[int, list[dict]]] = []  # (insert_after_index, gps)

    for idx, item in enumerate(items):
        code = item["code"]
        category = item.get("category", "")

        # --- Verbi ---
        if code in VERBI_CODES:
            desc = item.get("description", "")
            # Split on ' - '; first segment is preamble (skip it)
            parts = [p.strip() for p in desc.split(" - ") if p.strip()]
            bullets = parts[1:] if len(parts) > 1 else parts  # skip preamble
            if not bullets:
                continue

            to_remove.add(code)
            children: list[dict] = []
            for bullet in bullets:
                slug = _slugify(bullet)
                new_code = _dedup(slug, existing_codes)
                existing_codes.add(new_code)
                child = {
                    "code": new_code,
                    "cefr_level": item["cefr_level"],
                    "category": category,
                    "description": bullet,
                    "unistr_code": item.get("unistr_code", code),
                    "unistr_label": bullet,
                }
                if "source_url" in item:
                    child["source_url"] = item["source_url"]
                children.append(child)
                print(f"  + {new_code:20s} {item['cefr_level']}  {bullet[:70]}")
            new_gps.append((idx, children))

        # --- Preposizioni ---
        elif category == "preposizioni":
            label = item.get("unistr_label", "")
            if ";" not in label:
                continue
            uses = [u.strip() for u in label.split(";") if u.strip()]
            if len(uses) < 2:
                continue

            to_remove.add(code)
            children = []
            for use in uses:
                slug = _slugify(use)
                # Prefix with 'prep_' for preposizioni
                if not slug.startswith("prep_"):
                    # incorporate parent code prefix (strip trailing underscore)
                    prefix = code[:7].rstrip("_")  # e.g. 'prep_a' or 'prep_di'
                    slug = (prefix + "_" + slug)[:10].rstrip("_")
                new_code = _dedup(slug, existing_codes)
                existing_codes.add(new_code)
                child = {
                    "code": new_code,
                    "cefr_level": item["cefr_level"],
                    "category": category,
                    "description": use,
                    "unistr_code": item.get("unistr_code", code),
                    "unistr_label": use,
                }
                if "source_url" in item:
                    child["source_url"] = item["source_url"]
                children.append(child)
                print(f"  + {new_code:20s} {item['cefr_level']}  {use[:70]}")
            new_gps.append((idx, children))

    # Build new list: iterate original, skip removed, insert children after parent position
    insert_map: dict[int, list[dict]] = {idx: gps for idx, gps in new_gps}
    result: list[dict] = []
    for idx, item in enumerate(items):
        if item["code"] in to_remove:
            # Insert children in place of parent
            result.extend(insert_map.get(idx, []))
        else:
            result.append(item)

    print(
        f"\nRemoved {len(to_remove)} omnibus GPs, added {sum(len(g) for _, g in new_gps)} split GPs"
    )
    print(f"Total: {len(items)} → {len(result)}")

    # Validate
    codes = [i["code"] for i in result]
    dups = {c for c in codes if codes.count(c) > 1}
    if dups:
        print(f"ERROR: duplicate codes: {dups}")
        sys.exit(1)
    long_codes = [i["code"] for i in result if len(i["code"]) > 10]
    if long_codes:
        print(f"ERROR: codes >10 chars: {long_codes}")
        sys.exit(1)

    return result


def main():
    dry_run = "--dry-run" in sys.argv
    with open(YAML_PATH) as f:
        items = yaml.safe_load(f)

    print(f"Loaded {len(items)} grammar points\n")
    result = split_gp(items, dry_run)

    if dry_run:
        print("\n[DRY RUN] Not writing.")
        return

    with open(YAML_PATH, "w") as f:
        yaml.dump(result, f, default_flow_style=False, allow_unicode=True, width=200)
    print(f"Written to {YAML_PATH}")


if __name__ == "__main__":
    main()
