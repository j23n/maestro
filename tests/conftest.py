import os


def pytest_configure(config):
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
    os.environ.setdefault("MONGODB_USER", "test")
    os.environ.setdefault("MONGODB_PASSWORD", "test")
    os.environ.setdefault("MONGODB_DB", "test_maestro")
    os.environ.setdefault("MONGODB_HOST", "localhost")
    os.environ.setdefault("MONGODB_PORT", "27017")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
