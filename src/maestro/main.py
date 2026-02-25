from contextlib import asynccontextmanager
from fastapi.encoders import jsonable_encoder
from typing import Annotated, Union
from fastapi import FastAPI, Request, HTTPException, Header, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from beanie import PydanticObjectId

import markdown

from maestro.db import init_db
from maestro.models import Message, Chat
import maestro.services


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
