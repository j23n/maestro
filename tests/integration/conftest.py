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
async def test_app(db, student, account):
    """FastAPI TestClient with mocked lifespan. Shares the db fixture's database."""
    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session", sign_session(str(account.id)))
            yield client


@pytest.fixture
def mock_analyzer_client(mocker):
    """Patches _client() in analyzer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mock.messages.create = AsyncMock()
    mocker.patch("maestro.learning.analyzer._client", return_value=mock)
    return mock


@pytest.fixture
def mock_scorer_client(mocker):
    """Patches _client() in scorer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mock.messages.create = AsyncMock()
    mocker.patch("maestro.learning.scorer._client", return_value=mock)
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
def bg_test_mode():
    """Enable background task test mode for all integration tests."""
    from maestro.utils import enable_test_mode, disable_test_mode
    enable_test_mode()
    yield
    disable_test_mode()
