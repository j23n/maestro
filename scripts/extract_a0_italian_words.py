#!/usr/bin/env python3
"""
Extract all Italian words and phrases from A0 lessons and A0 grammar points,
run them through match_vocab_words() against the production dictionary fixture,
and report matched vs unmatched tokens.

Uses the ACTUAL matching pipeline (spaCy + simplemma + elision repair + POS
disambiguation) — no reimplementation.
"""

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

# Set dummy env vars so the import chain doesn't fail
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SECRET_KEY", "dummy")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")

import yaml  # noqa: E402

from maestro.vocab.discover import match_vocab_words  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "src" / "maestro" / "data" / "it"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "vocab_headwords.json"


def build_prod_word_index() -> dict[str, list]:
    """Build word_index from production vocab fixture (same as test suite)."""
    with open(FIXTURE_PATH) as f:
        raw = json.load(f)
    idx: dict[str, list] = {}
    for word, pos in raw:
        obj = SimpleNamespace(
            word=word,
            part_of_speech=pos,
            syllabization="",
            entry_id=f"LM-{word.upper()[:10]}",
            senses=[],
            id=f"fixture-{word}-{pos}",
            audio_url=None,
        )
        idx.setdefault(word, []).append(obj)
    return idx


def extract_lang_it_fragments(text: str) -> list[tuple[str, bool]]:
    """Extract (clean_text, has_data_no_save) from lang='it' elements."""
    results = []
    pattern = re.compile(
        r'<\w+\s([^>]*?)lang="it"([^>]*)>(.*?)</\w+>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        attrs = match.group(1) + match.group(2)
        no_save = "data-no-save" in attrs
        inner = match.group(3)
        clean = re.sub(r"<[^>]+>", " ", inner)
        clean = re.sub(r"\*+", "", clean)
        clean = clean.strip()
        if clean:
            results.append((clean, no_save))
    return results


def main():
    print("Building production word_index from fixture...")
    word_index = build_prod_word_index()
    print(f"  {len(word_index)} headwords loaded")

    # Load current vocab_a0.json for cross-reference
    with open(DATA_DIR / "vocab_a0.json") as f:
        current_a0 = json.load(f)
    current_a0_words = {item["word"].lower() for item in current_a0}

    # --- Extract from A0 lessons ---
    print("\nExtracting from a0_lessons.yaml...")
    with open(DATA_DIR / "a0_lessons.yaml") as f:
        lessons_content = f.read()
    lessons_data = yaml.safe_load(lessons_content)

    lesson_fragments = extract_lang_it_fragments(lessons_content)
    print(f"  {len(lesson_fragments)} lang='it' fragments")

    # Extract drill correct_answers
    drill_answers = []
    for lesson_key, lesson in lessons_data.items():
        for activity in lesson.get("activities", []):
            if activity.get("type") == "drill":
                for item in activity.get("items", []):
                    answer = item.get("correct_answer", "")
                    if answer and "{" not in answer:
                        drill_answers.append(answer)
    print(f"  {len(drill_answers)} drill answers")

    # --- Extract from A0 grammar points ---
    print("Extracting from grammar_points.yaml (A0 only)...")
    with open(DATA_DIR / "grammar_points.yaml") as f:
        gp_data = yaml.safe_load(f)
    a0_gps = [gp for gp in gp_data if gp.get("cefr_level") == "A0"]
    print(f"  {len(a0_gps)} A0 grammar points")

    gp_fragments = []
    for gp in a0_gps:
        for lang_code, expl in gp.get("explanations", {}).items():
            for field in ("explanation", "tip"):
                text = expl.get(field, "")
                if text:
                    gp_fragments.extend(extract_lang_it_fragments(text))
    print(f"  {len(gp_fragments)} grammar fragments")

    # --- Run all text through match_vocab_words ---
    all_fragments = lesson_fragments + gp_fragments
    # Add drill answers as fragments too
    for answer in drill_answers:
        all_fragments.append((answer, False))

    # Combine all text for one big match call (more efficient, mirrors discover())
    all_plain_texts = [text for text, _ in all_fragments]
    combined_text = " . ".join(all_plain_texts)

    print(
        f"\nRunning match_vocab_words() on combined text ({len(combined_text)} chars)..."
    )
    matches = match_vocab_words(combined_text, word_index)

    matched_lemmas = {}
    for m in matches:
        matched_lemmas[m.lemma] = {
            "word": m.word.word,
            "pos": m.word.part_of_speech,
            "surfaces": m.surface_forms,
        }

    print(f"\n{'=' * 70}")
    print(f"MATCHED: {len(matched_lemmas)} lemmas found in dictionary")
    print(f"{'=' * 70}")
    for lemma in sorted(matched_lemmas):
        m = matched_lemmas[lemma]
        surfaces = ", ".join(m["surfaces"])
        in_a0 = (
            "[a0]"
            if lemma in current_a0_words
            or any(s.lower() in current_a0_words for s in m["surfaces"])
            else "    "
        )
        print(
            f"  {in_a0} {lemma:25s} → {m['word']:20s} ({m['pos']:10s})  surfaces: {surfaces}"
        )

    # --- Find unmatched tokens ---
    # Re-tokenize to get ALL tokens, then subtract matched lemmas
    from maestro.vocab.discover import tokenize

    all_tokens = tokenize(combined_text)
    matched_set = set(matched_lemmas.keys())

    unmatched = {}
    for lem, pos, surface in all_tokens:
        if lem not in matched_set and lem not in unmatched:
            unmatched[lem] = {"pos": pos, "surface": surface}

    print(f"\n{'=' * 70}")
    print(f"UNMATCHED: {len(unmatched)} lemmas NOT in dictionary")
    print(f"{'=' * 70}")
    for lem in sorted(unmatched):
        u = unmatched[lem]
        in_a0 = (
            "[a0]"
            if lem in current_a0_words or u["surface"].lower() in current_a0_words
            else "    "
        )
        print(f"  {in_a0} {lem:25s}  POS={u['pos']:6s}  surface={u['surface']}")

    # --- Phrases ---
    print(f"\n{'=' * 70}")
    print("PHRASES from A0 content (multi-word lang='it' elements, ≤6 words)")
    print(f"{'=' * 70}")
    seen_phrases = set()
    for text, no_save in lesson_fragments + gp_fragments:
        if " " not in text:
            continue
        clean = re.sub(r"[.!?,;:…]+$", "", text).strip().lower()
        clean = re.sub(r"\*+", "", clean)
        if clean.startswith(("—", "-")):
            continue
        words = clean.split()
        if len(words) < 2 or len(words) > 6:
            continue
        if "{" in clean or "/" in clean or "→" in clean or "=" in clean:
            continue
        if clean in seen_phrases:
            continue
        seen_phrases.add(clean)
        in_a0 = "[a0]" if clean in current_a0_words else "    "
        ns = "[no-save]" if no_save else ""
        print(f"  {in_a0} {clean:45s} {ns}")

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Matched lemmas (in dict):   {len(matched_lemmas)}")
    print(f"  Unmatched lemmas:           {len(unmatched)}")
    print(f"  Phrases extracted:          {len(seen_phrases)}")
    print(f"  Current vocab_a0.json:      {len(current_a0_words)} entries")


if __name__ == "__main__":
    main()
