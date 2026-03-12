"""Pre-generate WAV audio for all A0 static assets.

Generates two kinds of audio:
1. Listening-activity audio — from a0_lessons.yaml (a0_*.wav)
2. Vocabulary word audio — from vocab_a0.json (word_*.wav)

Usage (with Azure credentials in environment):
    uv run scripts/generate_a0_audio.py

Optional flags:
    --check   Dry-run: report missing audio files and lesson↔vocab coverage
              gaps without calling Azure. Exit code 1 if anything is missing.

Requires:
    AZURE_SPEECH_KEY and AZURE_SPEECH_REGION set in .env or environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_DATA_DIR = Path(__file__).parent.parent / "src" / "maestro" / "data" / "it"


def _load_lessons() -> dict:
    import yaml

    with open(_DATA_DIR / "a0_lessons.yaml") as f:
        return yaml.safe_load(f)


def _load_vocab() -> list[dict]:
    with open(_DATA_DIR / "vocab_a0.json") as f:
        return json.load(f)


def _collect_strings(obj) -> list[str]:
    """Recursively collect all string values from a nested dict/list structure."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for item in obj for s in _collect_strings(item)]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _collect_strings(v)]
    return []


def _lesson_lemmas(all_lessons: dict) -> set[str]:
    """Lemmatize Italian text from lessons.

    Two sources:
    1. Text inside <span lang="it"> tags (replicates discover()'s extraction).
    2. Drill item prompts/answers — these are bare Italian text with no spans.
    """
    from bs4 import BeautifulSoup
    from maestro.vocab.discover import _lemmatize, _get_target_text

    lemmas: set[str] = set()
    for lesson_data in all_lessons.values():
        for act in lesson_data.get("activities", []):
            # 1. Span-tagged Italian in any field
            for text in _collect_strings(act):
                if 'lang="it"' not in text:
                    continue
                soup = BeautifulSoup(text, "html.parser")
                lang_elements = soup.find_all(attrs={"lang": "it"})
                if not lang_elements:
                    continue
                target_text = _get_target_text(lang_elements)
                lemmas.update(_lemmatize(target_text))

            # 2. Drill items — prompts and answers are bare Italian
            for item in act.get("items") or []:
                for field in ("prompt", "correct_answer"):
                    text = item.get(field, "") or ""
                    if text:
                        lemmas.update(_lemmatize(text))
    return lemmas


# ── check mode ──────────────────────────────────────────────────────


def check(all_lessons: dict, vocab_items: list[dict]) -> int:
    """Report missing audio files and lesson↔vocab coverage gaps. Returns exit code."""
    from maestro.tts import _a0_audio_path, _word_audio_path

    problems = 0

    # 1. Listening-activity audio
    print("Listening-activity audio (a0_*.wav):")
    for slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            path = _a0_audio_path(slug)
            if path.exists():
                print(f"  OK    {slug:30s} -> {path.name}")
            else:
                print(f"  MISS  {slug:30s} -> {path.name}")
                problems += 1

    # 2. Word audio
    print("\nVocabulary word audio (word_*.wav):")
    for item in vocab_items:
        word = item["word"]
        path = _word_audio_path(word)
        if path.exists():
            print(f"  OK    {word:20s} -> {path.name}")
        else:
            print(f"  MISS  {word:20s} -> {path.name}")
            problems += 1

    # 3. Lesson↔vocab coverage — replicate discover()'s matching direction:
    #    check which vocab headwords appear in the lemmatized lesson text.
    #    This is immune to bad lemmas (they just silently fail to match).
    print("\nLesson↔vocab coverage (discover-style headword matching):")
    lemmas = _lesson_lemmas(all_lessons)
    found = []
    not_found = []
    for item in vocab_items:
        headword = item["word"].lower()
        if headword in lemmas:
            found.append(headword)
        else:
            not_found.append(headword)
    for w in found:
        print(f"  OK    {w}")
    for w in not_found:
        print(f"  MISS  {w}")
    print(f"\n  {len(found)}/{len(vocab_items)} A0 vocab words discoverable in lessons")

    if problems:
        print(f"\n{problems} audio file(s) missing.")
    else:
        print("\nAll audio files present.")

    return 1 if problems else 0


# ── generate mode ───────────────────────────────────────────────────


async def generate(all_lessons: dict, vocab_items: list[dict]) -> int:
    """Generate all A0 audio. Returns exit code."""
    from maestro.tts import generate_a0_audio, generate_word_audio

    generated = 0
    skipped = 0
    failed = 0

    # 1. Listening-activity audio
    print("Listening-activity audio:")
    for slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            content = act.get("content", "")
            if not content:
                print(f"  SKIP  {slug}: no content")
                skipped += 1
                continue
            print(f"  GEN   {slug} ...", end=" ", flush=True)
            url = await generate_a0_audio(slug, content)
            if url:
                print(f"-> {url}")
                generated += 1
            else:
                print("FAILED")
                failed += 1

    # 2. Word audio
    print("\nVocabulary word audio:")
    for item in vocab_items:
        word = item["word"]
        print(f"  GEN   {word:20s} ...", end=" ", flush=True)
        url = await generate_word_audio(word)
        if url:
            print(f"-> {url}")
            generated += 1
        else:
            print("FAILED")
            failed += 1

    print(f"\nDone: {generated} generated, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


# ── entrypoint ──────────────────────────────────────────────────────


async def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: report missing files and coverage gaps (no Azure needed)",
    )
    args = parser.parse_args()

    all_lessons = _load_lessons()
    vocab_items = _load_vocab()

    if args.check:
        return check(all_lessons, vocab_items)
    return await generate(all_lessons, vocab_items)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
