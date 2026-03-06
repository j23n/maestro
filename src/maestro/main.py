from contextlib import asynccontextmanager
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("maestro").setLevel(logging.DEBUG)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from maestro.db import init_db
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import vocab, profilo, grammar, lezione


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_nlp()        # warm up spaCy Italian model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")
app.include_router(vocab.router)
app.include_router(profilo.router)
app.include_router(grammar.router)
app.include_router(lezione.router)
