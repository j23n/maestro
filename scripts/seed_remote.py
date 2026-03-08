"""Seed remote MongoDB from local BSON dump files.

Usage:
    MONGODB_URI=<uri> python scripts/seed_remote.py [--dir data/seed/current] [--user] [--force]

Options:
    --dir    Path to BSON dump directory (default: data/seed/current)
    --user   Also seed user collections (accounts, learning_profile, lessons, etc.)
    --force  Drop and re-insert even if collections already have data
"""

import argparse
import asyncio
import sys
from pathlib import Path

import bson
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maestro.config import settings
from maestro.seed import SEED_COLLECTIONS, USER_COLLECTIONS

DEFAULT_SEED_DIR = Path(__file__).resolve().parents[1] / "data" / "seed" / "current"


async def seed(seed_dir: Path, collections: list[str], force: bool) -> None:
    client = AsyncMongoClient(settings.MONGODB_URI)
    db = client.get_database(
        settings.MONGODB_DB,
        codec_options=CodecOptions(tz_aware=True),
    )

    print(f"Connected to {settings.MONGODB_URI} / {settings.MONGODB_DB}")
    print(f"Seed dir: {seed_dir}\n")

    for name in collections:
        path = seed_dir / f"{name}.bson"
        if not path.exists():
            print(f"  {name}: SKIP (file not found: {path})")
            continue

        count = await db[name].count_documents({})
        if count and not force:
            print(f"  {name}: SKIP ({count} documents already present; use --force to overwrite)")
            continue

        docs = bson.decode_all(path.read_bytes())
        if not docs:
            print(f"  {name}: SKIP (empty file)")
            continue

        if force:
            await db[name].drop()

        result = await db[name].insert_many(docs, ordered=False)
        print(f"  {name}: inserted {len(result.inserted_ids)} documents")

    await client.close()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed remote MongoDB from BSON files")
    parser.add_argument("--dir", type=Path, default=DEFAULT_SEED_DIR, metavar="DIR")
    parser.add_argument("--user", action="store_true", help="Also seed user collections")
    parser.add_argument("--force", action="store_true", help="Drop and re-insert existing collections")
    args = parser.parse_args()

    if not args.dir.exists():
        print(f"Error: seed directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    collections = SEED_COLLECTIONS + (USER_COLLECTIONS if args.user else [])
    asyncio.run(seed(args.dir, collections, args.force))


if __name__ == "__main__":
    main()
