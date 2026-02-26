from functools import lru_cache
import spacy


@lru_cache(maxsize=1)
def get_nlp():
    return spacy.load("it_core_news_sm")
