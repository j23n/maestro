import spacy

_nlp_cache: dict[str, spacy.Language] = {}


def get_nlp(language: str) -> spacy.Language:
    """Return a cached spaCy model for *language*."""
    if language not in _nlp_cache:
        from maestro.language import get_language_config

        cfg = get_language_config(language)
        _nlp_cache[language] = spacy.load(cfg.spacy_model)
    return _nlp_cache[language]
