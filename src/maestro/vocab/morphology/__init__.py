"""Language-specific morphology dispatch for vocabulary lookup."""
from maestro.config import settings


def get_lookup_factory():
    """Return the make_lookup callable for the configured target language."""
    if settings.TARGET_LANGUAGE == "it":
        from maestro.vocab.morphology.it import make_lookup
        return make_lookup
    raise ValueError(f"No morphology module for {settings.TARGET_LANGUAGE}")
