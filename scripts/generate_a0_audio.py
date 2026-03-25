"""Pre-generate WAV audio for all A0 static assets.

Generates three kinds of audio:
1. Listening-activity audio — from a0_lessons.yaml (a0_*.wav)
2. Pronunciation audio — vowels and numbers referenced in grammar tables
3. Vocabulary word audio — from vocab_a0.yaml (word_*.wav)

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
import re
import sys
from pathlib import Path

import yaml

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_DATA_DIR = Path(__file__).parent.parent / "src" / "maestro" / "data" / "it"

# Pronunciation audio: filename stem -> Italian text to synthesize
_PRONUNCIATION_ITEMS: dict[str, str] = {
    "vowel_a": "a",
    "vowel_e": "e",
    "vowel_i": "i",
    "vowel_o": "o",
    "vowel_u": "u",
    "num_0": "zero",
    "num_1": "uno",
    "num_2": "due",
    "num_3": "tre",
    "num_4": "quattro",
    "num_5": "cinque",
    "num_6": "sei",
    "num_7": "sette",
    "num_8": "otto",
    "num_9": "nove",
    "num_10": "dieci",
    "num_11": "undici",
    "num_12": "dodici",
    "num_13": "tredici",
    "num_14": "quattordici",
    "num_15": "quindici",
    "num_16": "sedici",
    "num_17": "diciassette",
    "num_18": "diciotto",
    "num_19": "diciannove",
    "num_20": "venti",
}


def _load_lessons() -> dict:
    with open(_DATA_DIR / "a0_lessons.yaml") as f:
        return yaml.safe_load(f)


def _load_vocab() -> list[dict]:
    with open(_DATA_DIR / "vocab_a0.yaml") as f:
        return yaml.safe_load(f)


def _collect_strings(obj: object) -> list[str]:
    """Recursively collect all string values from a nested dict/list structure."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for item in obj for s in _collect_strings(item)]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _collect_strings(v)]
    return []


def _collect_pronunciation_paths(all_lessons: dict) -> list[str]:
    """Extract /static/audio/*.wav paths from grammar content (not listening audio_path)."""
    paths: list[str] = []
    for lesson_data in all_lessons.values():
        for act in lesson_data.get("activities", []):
            content = act.get("content", "") or ""
            paths.extend(re.findall(r"/static/audio/(\w+)\.wav", content))
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _lesson_lemmas(all_lessons: dict) -> set[str]:
    """Lemmatize Italian text from lessons.

    Two sources:
    1. Text inside <span lang="it"> tags (replicates discover()'s extraction).
    2. Drill item prompts/answers — these are bare Italian text with no spans.
    """
    from bs4 import BeautifulSoup
    from maestro.vocab.discover import tokenize, get_target_text

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
                target_text = get_target_text(lang_elements)
                lemmas.update(lem for lem, _, _ in tokenize(target_text))

            # 2. Drill items — prompts and answers are bare Italian
            for item in act.get("items") or []:
                for field in ("prompt", "correct_answer"):
                    text = item.get(field, "") or ""
                    if text:
                        lemmas.update(lem for lem, _, _ in tokenize(text))
    return lemmas


# ── check mode ──────────────────────────────────────────────────────


def check(all_lessons: dict, vocab_items: list[dict]) -> int:
    """Report missing audio files and lesson↔vocab coverage gaps. Returns exit code."""
    from maestro.tts import _audio_dir, word_audio_path

    audio_dir = _audio_dir()
    problems = 0

    # 1. Listening-activity audio
    print("Listening-activity audio (a0_*.wav):")
    for slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            audio_url = act.get("audio_path", "")
            if not audio_url:
                print(f"  MISS  {slug:30s} -> (no audio_path in YAML)")
                problems += 1
                continue
            filename = audio_url.rsplit("/", 1)[-1]
            path = audio_dir / filename
            if path.exists():
                print(f"  OK    {slug:30s} -> {filename}")
            else:
                print(f"  MISS  {slug:30s} -> {filename}")
                problems += 1

    # 2. Pronunciation audio (vowels, numbers, etc.)
    print("\nPronunciation audio:")
    pron_paths = _collect_pronunciation_paths(all_lessons)
    for stem in pron_paths:
        path = audio_dir / f"{stem}.wav"
        text = _PRONUNCIATION_ITEMS.get(stem)
        if not text:
            print(f"  WARN  {stem}.wav — no text mapping (add to _PRONUNCIATION_ITEMS)")
            problems += 1
            continue
        if path.exists():
            print(f"  OK    {stem:20s} -> {path.name}")
        else:
            print(f"  MISS  {stem:20s} -> {path.name}")
            problems += 1

    # 3. Word audio
    print("\nVocabulary word audio (word_*.wav):")
    for item in vocab_items:
        word = item["word"]
        path = word_audio_path(word)
        if path.exists():
            print(f"  OK    {word:20s} -> {path.name}")
        else:
            print(f"  MISS  {word:20s} -> {path.name}")
            problems += 1

    # 4. Lesson↔vocab coverage — replicate discover()'s matching direction:
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
    from maestro.tts import (
        _audio_dir,
        _strip_markup,
        _synth_to_file,
        generate_word_audio,
    )

    audio_dir = _audio_dir()
    audio_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    failed = 0

    # 1. Listening-activity audio (always regenerate — content may have changed)
    print("Listening-activity audio:")
    for slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            content = act.get("content", "")
            audio_url = act.get("audio_path", "")
            if not content or not audio_url:
                print(f"  SKIP  {slug}: no content or audio_path")
                skipped += 1
                continue
            filename = audio_url.rsplit("/", 1)[-1]
            path = audio_dir / filename
            # Delete existing file so we re-synthesize with updated content
            if path.exists():
                path.unlink()
            print(f"  GEN   {slug} -> {filename} ...", end=" ", flush=True)
            try:
                await _synth_to_file(_strip_markup(content), path)
                print(f"-> {audio_url}")
                generated += 1
            except Exception as e:
                print(f"FAILED: {e}")
                failed += 1

    # 2. Pronunciation audio (vowels, numbers, etc.)
    print("\nPronunciation audio:")
    pron_paths = _collect_pronunciation_paths(all_lessons)
    for stem in pron_paths:
        text = _PRONUNCIATION_ITEMS.get(stem)
        if not text:
            print(f"  SKIP  {stem}.wav — no text mapping")
            skipped += 1
            continue
        path = audio_dir / f"{stem}.wav"
        if path.exists():
            print(f"  SKIP  {path.name} (exists)")
            skipped += 1
            continue
        print(f"  GEN   {path.name} ...", end=" ", flush=True)
        try:
            await _synth_to_file(text, path)
            print("OK")
            generated += 1
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1

    # 3. Word audio
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
