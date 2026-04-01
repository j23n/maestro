"""Language-specific morphology dispatch for vocabulary lookup."""


def get_lookup_factory(language: str):
    """Return the make_lookup callable for the given target language."""
    if language == "it":
        from maestro.vocab.morphology.it import make_lookup

        return make_lookup
    if language == "de":
        from maestro.vocab.morphology.de import make_lookup as de_make_lookup

        return de_make_lookup
    raise ValueError(f"No morphology module for {language}")
