from maestro.vocab.discover import load_vocab
from contextlib import asynccontextmanager
from fastapi.encoders import jsonable_encoder
from typing import Annotated, Union
from fastapi import FastAPI, Request, HTTPException, Header, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from beanie import PydanticObjectId

import markdown
import random

from datetime import date
from maestro.db import init_db
from maestro.models import Message, Chat, VocabularyWord, UserVocabularyCard
from maestro.rag.retrieve import get_model
from maestro.vocab.nlp import get_nlp
from maestro.vocab.srs import review
import maestro.services


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_model()  # warm up sentence-transformers
    get_nlp()  # warm up spaCy Italian model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)


@app.get("/chat/", response_class=HTMLResponse)
async def home(request: Request):
    chat = await Chat.find_one()
    if not chat:
        chat = Chat()
        await chat.insert()
    return templates.TemplateResponse(
        request=request, name="chat.html", context={"chat": chat}
    )


@app.get("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def list_messages(
    chat_id: PydanticObjectId,
    request: Request,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    # fastapi.Header fills in the HTTP header based on the parameter name.
    # to make it explicit: Header(alias="HX-Request"). It handles hyphen and
    # case automagically

    chat = await Chat.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await Message.find({"chat.$id": chat.id}).to_list()
    if hx_request:
        return templates.TemplateResponse(
            request=request, name="messages.html", context={"messages": messages}
        )
    return JSONResponse(content=jsonable_encoder(messages))


@app.post("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def create_message(
    chat_id: PydanticObjectId, request: Request, message: Annotated[str, Form()]
):
    chat = await Chat.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    m = Message(chat=chat, text=message, sender="user")
    await m.insert()

    return templates.TemplateResponse(
        request=request, name="user-message.html", context={"message": m}
    )


@app.get("/chat/{chat_id}/messages/{message_id}/reply")
async def get_response(
    chat_id: PydanticObjectId,
    message_id: PydanticObjectId,
    request: Request,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    chat = await Chat.get(chat_id)
    user_msg = await Message.get(message_id)
    if chat is None or user_msg is None:
        raise HTTPException(404)
    context = await Message.find({"chat.$id": chat.id}).to_list()

    reply = await maestro.services.get_response(user_msg, context)
    await reply.insert()

    return templates.TemplateResponse(
        request=request, name="message.html", context={"message": reply}
    )


@app.get("/vocab", response_class=HTMLResponse)
async def vocab_list(request: Request):
    cards = await UserVocabularyCard.find_all().to_list()
    for card in cards:
        await card.fetch_all_links()
    return templates.TemplateResponse(
        request=request,
        name="vocab.html",
        context={"cards": cards, "today": date.today()},
    )


QUIZ_MODES = ("word", "definition", "translation")


@app.get("/vocab/practice", response_class=HTMLResponse)
async def vocab_practice(request: Request, mode: str = "random"):
    card = await UserVocabularyCard.find_one(
        {"next_review": {"$lte": date.today()}}
    )
    if card is None:
        return templates.TemplateResponse(
            request=request, name="vocab-practice.html", context={"card": None, "mode": mode}
        )
    await card.fetch_all_links()
    resolved_mode = random.choice(QUIZ_MODES) if mode == "random" else mode
    return templates.TemplateResponse(
        request=request, name="vocab-practice.html", context={"card": card, "mode": resolved_mode, "selected_mode": mode}
    )


@app.get("/vocab/practice/{card_id}/reveal", response_class=HTMLResponse)
async def vocab_reveal(card_id: PydanticObjectId, request: Request, mode: str = "word"):
    card = await UserVocabularyCard.get(card_id)
    await card.fetch_all_links()
    return templates.TemplateResponse(
        request=request, name="vocab-card-back.html", context={"card": card, "mode": mode}
    )


@app.post("/vocab/practice/{card_id}/review", response_class=HTMLResponse)
async def vocab_review(
    card_id: PydanticObjectId, request: Request, rating: Annotated[int, Form()],
    mode: Annotated[str, Form()] = "random",
):
    card = await UserVocabularyCard.get(card_id)
    card = review(card, rating)
    await card.save()
    return Response(status_code=204, headers={"HX-Redirect": f"/vocab/practice?mode={mode}"})
