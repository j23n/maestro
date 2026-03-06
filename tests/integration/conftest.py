import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from fastapi.testclient import TestClient

from maestro.models import ALL_DOCUMENT_MODELS


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)
    yield


@pytest.fixture
async def test_app(db):
    """FastAPI TestClient with mocked lifespan. Shares the db fixture's database."""
    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.fixture
def mock_analyzer_client(mocker):
    """Patches _client() in analyzer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mocker.patch("maestro.learning.analyzer._client", return_value=mock)
    return mock


@pytest.fixture
def mock_scorer_client(mocker):
    """Patches _client() in scorer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mocker.patch("maestro.learning.scorer._client", return_value=mock)
    return mock


@pytest.fixture(autouse=True)
def reset_taxonomy():
    """Reset taxonomy cache between tests."""
    from maestro import taxonomy
    taxonomy.invalidate()
    yield
    taxonomy.invalidate()
