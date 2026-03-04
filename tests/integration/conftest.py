import pytest
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import (
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

ALL_MODELS = [
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
]


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro"], document_models=ALL_MODELS)
    yield


@pytest.fixture
def mock_analyzer_client(mocker):
    """Patches _client() in analyzer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mocker.patch("maestro.learning.analyzer._client", return_value=mock)
    return mock
