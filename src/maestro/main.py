from contextlib import asynccontextmanager
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("maestro").setLevel(logging.DEBUG)

from fastapi import FastAPI

from maestro.db import init_db
from maestro.rag.retrieve import get_model
from maestro.vocab.discover import load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import vocab, profilo, grammar, lezione


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_model()  # warm up sentence-transformers
    get_nlp()    # warm up spaCy Italian model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(vocab.router)
app.include_router(profilo.router)
app.include_router(grammar.router)
app.include_router(lezione.router)
