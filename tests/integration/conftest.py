import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from fastapi.testclient import TestClient

from maestro.models import ALL_DOCUMENT_MODELS


@contextlib.contextmanager
def patch_lifespan():
    """Patch all lifespan startup calls (init_db, seed, nlp, vocab)."""
    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.run_pending", new_callable=AsyncMock),
        patch("maestro.main.sync_grammar_points", new_callable=AsyncMock),
        patch("maestro.main.sync_a0_vocab", new_callable=AsyncMock),
        patch("maestro.main.seed_if_empty", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(
        database=client["test_maestro"], document_models=ALL_DOCUMENT_MODELS
    )
    yield


@pytest.fixture
async def student(db):
    from maestro.models import Student

    s = Student(name="Test Student")
    await s.insert()
    return s


@pytest.fixture
async def account(db, student):
    from maestro.models import Account

    a = Account(
        email="test@example.com",
        password_hash="$2b$12$fakehashfortest",
        student_id=student.id,
    )
    await a.insert()
    return a


def sign_session(account_id: str) -> str:
    """Sign a session cookie for the given account ID."""
    from maestro.session import _get_serializer

    return _get_serializer().dumps({"account_id": account_id})


@pytest.fixture
async def auth_app(db):
    """FastAPI TestClient without pre-set cookies."""
    with patch_lifespan():
        from maestro.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            # Trigger CSRF cookie and set default header
            client.get("/")
            csrf_token = client.cookies.get("csrftoken")
            if csrf_token:
                client.headers["x-csrftoken"] = csrf_token
            yield client


@pytest.fixture
async def test_app(db, student, account):
    """FastAPI TestClient with mocked lifespan. Shares the db fixture's database."""
    with patch_lifespan():
        from maestro.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session", sign_session(str(account.id)))
            # Trigger CSRF cookie and set default header for POST requests
            client.get("/")
            csrf_token = client.cookies.get("csrftoken")
            if csrf_token:
                client.headers["x-csrftoken"] = csrf_token
            yield client


@pytest.fixture
def mock_scorer_client(mocker):
    """Patches get_async_client in llm.py to return a MagicMock for scorer tests."""
    mock = mocker.MagicMock()
    mock.messages.create = AsyncMock()
    mocker.patch("maestro.llm.get_async_client", return_value=mock)
    return mock


@pytest.fixture(autouse=True)
def reset_serializer():
    """Reset session serializer cache between tests."""
    import maestro.session

    maestro.session._serializer = None
    yield
    maestro.session._serializer = None


@pytest.fixture(autouse=True)
def reset_taxonomy():
    """Reset taxonomy cache between tests."""
    from maestro import taxonomy

    taxonomy.invalidate()
    yield
    taxonomy.invalidate()


@pytest.fixture(autouse=True)
def reset_i18n_cache():
    from maestro.i18n import _cache

    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset rate limiter state between tests."""
    from maestro.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def reset_llm_client_cache():
    """Clear lru_cache on LLM and TTS client factories between tests to prevent state leakage."""
    from maestro.llm import get_client, get_async_client
    from maestro.tts import _get_tts_client

    get_client.cache_clear()
    get_async_client.cache_clear()
    _get_tts_client.cache_clear()
    yield
    get_client.cache_clear()
    get_async_client.cache_clear()
    _get_tts_client.cache_clear()


@pytest.fixture(autouse=True)
def bg_test_mode():
    """Enable background task test mode for all integration tests."""
    from maestro.utils import enable_test_mode, disable_test_mode

    enable_test_mode()
    yield
    disable_test_mode()
