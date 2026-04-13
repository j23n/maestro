import logging

from beanie import init_beanie
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient
from maestro.config import settings
from maestro.models import ALL_DOCUMENT_MODELS

logger = logging.getLogger(__name__)

_db = None


async def init_db():
    global _db
    logger.info("initialising MongoDB: db=%s", settings.MONGODB_DB)
    client = AsyncMongoClient(settings.MONGO_URL)
    _db = client.get_database(
        settings.MONGODB_DB,
        codec_options=CodecOptions(tz_aware=True),
    )
    await init_beanie(
        database=_db,
        document_models=ALL_DOCUMENT_MODELS,
    )
    logger.info("MongoDB ready")


def get_db():
    return _db
