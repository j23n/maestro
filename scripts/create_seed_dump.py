"""Dump static curriculum collections to data/seed/ for production seeding.

Run after ingesting data locally:
  python scripts/create_seed_dump.py
"""

import asyncio
from pathlib import Path

import bson
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient

from maestro.config import settings
from maestro.seed import SEED_COLLECTIONS

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed" / "current"


async def dump():
    client = AsyncMongoClient(settings.MONGODB_URI)
    db = client.get_database(
        settings.MONGODB_DB,
        codec_options=CodecOptions(tz_aware=True),
    )
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    for name in SEED_COLLECTIONS:
        docs = await db[name].find().to_list(None)
        out = SEED_DIR / f"{name}.bson"
        out.write_bytes(b"".join(bson.encode(doc) for doc in docs))
        print(f"{name}: {len(docs)} documents -> {out}")


if __name__ == "__main__":
    asyncio.run(dump())
