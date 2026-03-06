from beanie import init_beanie
from pymongo import AsyncMongoClient
from maestro.config import settings
from maestro.models import ALL_DOCUMENT_MODELS


async def init_db():
    client = AsyncMongoClient(settings.database_url)
    await init_beanie(
        database=client[settings.MONGODB_DB],
        document_models=ALL_DOCUMENT_MODELS,
    )


def init_indices(client):
    collection = client[settings.MONGODB_DB]["italian_chunks"]
    collection.create_search_index(
        {
            "name": "embedding_index",
            "definition": {
                "mappings": {
                    "dynamic": False,
                    "fields": {
                        "embedding": {
                            "type": "knnVector",
                            "dimensions": 1024,
                            "similarity": "cosine",
                        },
                        "chunk_type": {"type": "token"},
                    },
                }
            },
        }
    )
