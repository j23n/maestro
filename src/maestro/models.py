from sqlalchemy import Column
from typing import Optional, List

from sqlmodel import Field, SQLModel, Relationship
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from datetime import datetime
from dataclasses import dataclass


class Chat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    messages: list["Message"] = Relationship(back_populates="chat")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    text: str = Field()
    sender: str = Field()

    chat_id: int = Field(foreign_key="chat.id")
    chat: Chat = Relationship(back_populates="messages")

    in_response_to_id: Optional[int] = Field(default=None, foreign_key="message.id")
    in_response_to: Optional["Message"] = Relationship(
        back_populates="replies", sa_relationship_kwargs={"remote_side": "Message.id"}
    )
    replies: List["Message"] = Relationship(back_populates="in_response_to")


class ItalianChunk(SQLModel, table=True):
    __tablename__ = "italian_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = Field(unique=True)
    content: str = Field(sa_column_kwargs={"name": "chunk"})
    chunk_type: str = Field()
    embedding: list = Field(sa_column=Column(Vector(1024)))
    chunk_metadata: dict = Field(sa_column=Column(JSONB))


@dataclass
class ItalianChunkResult:
    chunk: ItalianChunk
    similarity: float
