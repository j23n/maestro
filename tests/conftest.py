import logging
import os

import pytest


def pytest_configure(config):
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/test_maestro")
    os.environ.setdefault("MONGODB_DB", "test_maestro")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture(autouse=True, scope="session")
def _ensure_caplog_compat():
    """Prevent maestro logger from swallowing caplog records."""
    maestro_logger = logging.getLogger("maestro")
    maestro_logger.propagate = True
