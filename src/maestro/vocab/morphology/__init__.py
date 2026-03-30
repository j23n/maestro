"""Language-specific morphology dispatch for vocabulary lookup."""

from maestro.language import DEFAULT_LANGUAGE


def get_lookup_factory(language: str | None = None):
    """Return the make_lookup callable for the given target language."""
    lang = language or DEFAULT_LANGUAGE
    if lang == "it":
        from maestro.vocab.morphology.it import make_lookup

        return make_lookup
    if lang == "de":
        from maestro.vocab.morphology.de import make_lookup as de_make_lookup

        return de_make_lookup
    raise ValueError(f"No morphology module for {lang}")
