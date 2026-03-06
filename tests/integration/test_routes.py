"""FastAPI route smoke tests using mongomock DB and patched lifespan."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import ALL_DOCUMENT_MODELS


@pytest.fixture
async def test_app():
    """Create the FastAPI app with a mocked lifespan (no real DB, no ML models)."""
    mongo_client = AsyncMongoMockClient()
    await init_beanie(database=mongo_client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)

    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.mark.integration
def test_vocab_page_ok(test_app):
    response = test_app.get("/vocab")
    assert response.status_code == 200


@pytest.mark.integration
def test_vocab_word_not_found(test_app):
    response = test_app.get("/vocab/word/NONEXISTENT-ID")
    assert response.status_code == 404


@pytest.mark.integration
def test_profilo_page_ok(test_app):
    """Profile page renders even with no profile in DB."""
    response = test_app.get("/profilo")
    assert response.status_code == 200


@pytest.mark.integration
def test_grammar_nonexistent_returns_404(test_app):
    response = test_app.get("/grammar/NONEXISTENT")
    assert response.status_code == 404


@pytest.mark.integration
def test_lezione_index_no_active_redirects_to_new(test_app):
    """With no active lesson, /lezione/ should redirect to /lezione/new."""
    response = test_app.get("/lezione/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/lezione/new" in response.headers.get("location", "")
