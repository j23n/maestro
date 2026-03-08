import os


def pytest_configure(config):
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
    os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/test_maestro")
    os.environ.setdefault("MONGODB_DB", "test_maestro")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
