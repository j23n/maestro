from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass
from beanie import Document, Link
from pydantic import Field


class Chat(Document):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    class Settings:
        name = "chats"


class Message(Document):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    text: str
    sender: str
    chat: Link[Chat]
    in_response_to: Optional[Link["Message"]] = None

    class Settings:
        name = "messages"


class ItalianChunk(Document):
    ref: str = Field(unique=True)
    content: str
    chunk_type: str
    embedding: List[float]
    chunk_metadata: dict = {}

    class Settings:
        name = "italian_chunks"


@dataclass
class ItalianChunkResult:
    chunk: ItalianChunk
    similarity: float
