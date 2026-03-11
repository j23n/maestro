"""Dump collections to data/seed/ for seeding.

Usage:
    python scripts/create_seed_dump.py           # curriculum collections only
    python scripts/create_seed_dump.py --user    # also dump user collections
"""

import argparse
import asyncio
from pathlib import Path

import bson
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient

from maestro.config import settings
from maestro.seed import SEED_COLLECTIONS, USER_COLLECTIONS

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed" / "current"


async def dump(collections: list[str]) -> None:
    client = AsyncMongoClient(settings.MONGO_URL)
    db = client.get_database(
        settings.MONGODB_DB,
        codec_options=CodecOptions(tz_aware=True),
    )
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    for name in collections:
        docs = await db[name].find().to_list(None)
        out = SEED_DIR / f"{name}.bson"
        out.write_bytes(b"".join(bson.encode(doc) for doc in docs))
        print(f"{name}: {len(docs)} documents -> {out}")

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump MongoDB collections to BSON files"
    )
    parser.add_argument(
        "--user", action="store_true", help="Also dump user collections"
    )
    args = parser.parse_args()

    collections = SEED_COLLECTIONS + (USER_COLLECTIONS if args.user else [])
    asyncio.run(dump(collections))


if __name__ == "__main__":
    main()
