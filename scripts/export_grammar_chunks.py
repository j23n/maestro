#!/usr/bin/env python3
"""Export GrammarChunk content to a static JSON file for offline explanation generation.

Writes data/it/grammar_chunk_contents.json:
  { "chunk_ref": "markdown content ...", ... }

Run this once after ingesting the grammar book, then commit the output.
The generate_explanations script reads from this file instead of hitting the database.

Usage: uv run python scripts/export_grammar_chunks.py
"""

import asyncio
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "data/it/grammar_chunk_contents.json"


async def main() -> None:
    from maestro.db import init_db
    from maestro.models import GrammarChunk

    await init_db()
    chunks = await GrammarChunk.find_all().to_list()
    if not chunks:
        print("No grammar chunks found in database. Run the grammar book ingest first.")
        return

    data = {chunk.ref: chunk.content for chunk in chunks}
    OUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Exported {len(data)} grammar chunks → {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
