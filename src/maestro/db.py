from beanie import init_beanie
from pymongo import AsyncMongoClient
from maestro.settings import Settings
from maestro.models import (
    Chat,
    Message,
    ItalianChunk,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
    GrammarPoint,
    GrammarPointExplanation,
    CommunicativeFunction,
    LearningEvent,
    LearningProfile,
    DrillTemplate,
    GeneratedDrill,
    DrillAttempt,
    Lesson,
)


settings = Settings()


async def init_db():
    client = AsyncMongoClient(settings.database_url)
    await init_beanie(
        database=client[settings.MONGODB_DB],
        document_models=[
            Chat,
            Message,
            ItalianChunk,
            VocabularyWord,
            VocabularyWordDefinition,
            UserVocabularyCard,
            GrammarPoint,
            CommunicativeFunction,
            LearningEvent,
            LearningProfile,
            DrillTemplate,
            GeneratedDrill,
            DrillAttempt,
            Lesson,
            GrammarPointExplanation,
        ],
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
