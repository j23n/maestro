import pytest
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import ALL_DOCUMENT_MODELS


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)
    yield


@pytest.fixture
def mock_analyzer_client(mocker):
    """Patches _client() in analyzer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mocker.patch("maestro.learning.analyzer._client", return_value=mock)
    return mock
