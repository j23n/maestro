from typing import Optional, List
from datetime import datetime, date
from dataclasses import dataclass
from beanie import Document, Link, Insert, after_event
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

    @after_event(Insert)
    async def on_insert(self):
        if self.sender == "assistant":
            from maestro.vocab.discover import discover  # lazy import

            self.text = await discover(self.text, self)
            await self.save()


class ItalianChunk(Document):
    ref: str = Field(unique=True)
    content: str
    chunk_type: str
    embedding: List[float]
    chunk_metadata: dict = {}

    class Settings:
        name = "italian_chunks"


class VocabularyWord(Document):
    word: str = Field(unique=True)
    part_of_speech: str
    cefr_level: str
    definition: str
    translation: str

    class Settings:
        name = "vocabulary_words"


class UserVocabularyCard(Document):
    word: Link[VocabularyWord]
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    message: Optional[Link["Message"]] = None
    ease_factor: float = 2.5
    interval: int = 1
    repetitions: int = 0
    next_review: date = Field(default_factory=date.today)

    class Settings:
        name = "user_vocabulary_cards"


@dataclass
class ItalianChunkResult:
    chunk: ItalianChunk
    similarity: float
