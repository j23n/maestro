from fastapi.encoders import jsonable_encoder
from typing import Annotated, Union
from fastapi import FastAPI, Request, HTTPException, Header, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import markdown

from maestro.models import Message, Chat
from maestro.db import SessionDep
import maestro.services


app = FastAPI()
templates = Jinja2Templates(directory="templates")
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)


@app.get("/chat/", response_class=HTMLResponse)
async def home(
    request: Request,
    session: SessionDep,
):
    chat = session.get(Chat, 0)
    if not chat:
        chat = Chat(id=0)
        session.add(chat)
        session.commit()
        session.refresh(chat)
    return templates.TemplateResponse(
        request=request, name="chat.html", context={"chat": chat}
    )


@app.get("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def list_messages(
    chat_id,
    request: Request,
    session: SessionDep,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    # fastapi.Header fills in the HTTP header based on the parameter name.
    # to make it explicit: Header(alias="HX-Request"). It handles hyphen and
    # case automagically

    chat = session.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if hx_request:
        return templates.TemplateResponse(
            request=request, name="messages.html", context={"messages": chat.messages}
        )
    return JSONResponse(content=jsonable_encoder(chat.messages))


@app.post("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def create_message(
    chat_id, request: Request, session: SessionDep, message: Annotated[str, Form()]
):
    chat = session.get(Chat, chat_id)
    if chat is None or chat.id is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    m = Message(chat_id=chat.id, text=message, sender="user")
    session.add(m)
    session.commit()
    session.refresh(m)

    return templates.TemplateResponse(
        request=request, name="user-message.html", context={"message": m}
    )


@app.get("/chat/{chat_id}/messages/{message_id}/reply")
async def get_response(
    chat_id: int,
    message_id: int,
    request: Request,
    session: SessionDep,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    chat = session.get(Chat, chat_id)
    user_msg = session.get(Message, message_id)
    if chat is None or user_msg is None:
        raise HTTPException(404)
    context = chat.messages

    reply = await maestro.services.get_response(user_msg, context)

    session.add(reply)
    session.commit()
    session.refresh(reply)

    return templates.TemplateResponse(
        request=request, name="message.html", context={"message": reply}
    )
