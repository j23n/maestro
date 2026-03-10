"""One-off script to pre-generate WAV audio for A0 static listening activities.

Reads a0_lessons.yaml, finds all `type: listening` activities, and calls
generate_a0_audio() for each. WAVs are saved to src/maestro/static/audio/.

Usage (with Azure credentials in environment):
    uv run scripts/generate_a0_audio.py

Requires:
    AZURE_SPEECH_KEY and AZURE_SPEECH_REGION set in .env or environment.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def main() -> None:
    import yaml
    from dotenv import load_dotenv

    load_dotenv()

    from maestro.tts import generate_a0_audio

    lessons_file = (
        Path(__file__).parent.parent
        / "src"
        / "maestro"
        / "data"
        / "it"
        / "a0_lessons.yaml"
    )
    with open(lessons_file) as f:
        all_lessons = yaml.safe_load(f)

    generated = 0
    skipped = 0
    failed = 0

    for scenario_slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            content = act.get("content", "")
            if not content:
                print(f"  SKIP  {scenario_slug}: no content")
                skipped += 1
                continue
            print(f"  GEN   {scenario_slug} ...", end=" ", flush=True)
            url = await generate_a0_audio(scenario_slug, content)
            if url:
                print(f"-> {url}")
                generated += 1
            else:
                print("FAILED")
                failed += 1

    print(f"\nDone: {generated} generated, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
