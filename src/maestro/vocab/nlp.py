from functools import lru_cache
import spacy

from maestro.config import settings


@lru_cache(maxsize=1)
def get_nlp():
    return spacy.load(settings.SPACY_MODEL)
