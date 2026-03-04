from typing import Optional, List
from datetime import datetime, date
from dataclasses import dataclass
from beanie import Document, Link, Insert, after_event, PydanticObjectId
from pydantic import BaseModel, Field


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


class Sense(BaseModel):
    definition: str
    examples: List[str] = []
    synonyms: List[str] = []
    antonyms: List[str] = []
    pos: Optional[str] = None    # only if different from entry-level POS
    style: Optional[str] = None  # "figurato", "aulico", etc.


class VocabularyWord(Document):
    word: str = Field(unique=True)
    syllabization: Optional[str] = None   # "af-flùs-so" (no brackets)
    part_of_speech: str                   # raw abbrev: "s.m.", "v.tr.", etc.
    cefr_level: str                       # A1–B2
    entry_id: Optional[str] = None        # "LM-00595"
    senses: List[Sense] = []              # all senses from EPUB

    class Settings:
        name = "vocabulary_words"


class CefrSense(BaseModel):
    definition: str
    examples: List[str] = []


class VocabularyWordDefinition(Document):
    word: Link["VocabularyWord"]
    student_level: str           # "A1" | "A2" | "B1" | "B2"
    senses: List[CefrSense]
    translation: str             # single English word or short phrase

    class Settings:
        name = "vocabulary_word_definitions"


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


# --- Learning outcome taxonomy ---

class GrammarPoint(Document):
    code: str
    label: str
    cefr_level: str
    category: str
    description: str
    rag_refs: List[str] = Field(default_factory=list)  # book-chunk refs, set at ingest

    class Settings:
        name = "grammar_points"


class CommunicativeFunction(Document):
    code: str
    label: str
    macro_category: str
    cefr_level: str
    patterns: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    description: str = ""   # built from patterns at ingest; used in analyzer prompt
    source_url: str = ""

    class Settings:
        name = "comm_functions"


# --- Learning events and profile ---

class LearningEvent(Document):
    message: Optional[Link[Message]] = None
    drill_attempt: Optional[Link["DrillAttempt"]] = None
    grammar_correct: List[str] = Field(default_factory=list)
    grammar_errors: List[str] = Field(default_factory=list)
    functions_performed: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    feedback: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "learning_events"


class LearningProfile(Document):
    grammar_correct_counts: dict = Field(default_factory=dict)
    grammar_error_counts: dict = Field(default_factory=dict)
    grammar_recent_outcomes: dict = Field(default_factory=dict)  # code → list[bool], sliding window of last 10
    functions_counts: dict = Field(default_factory=dict)
    themes_seen: List[str] = Field(default_factory=list)
    cefr_estimate: str = "A1"
    description: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    student_interests: List[str] = Field(default_factory=list)

    class Settings:
        name = "learning_profile"


# --- Drills ---

class DrillItem(BaseModel):
    prompt: str
    correct_answer: Optional[str] = None


class DrillTemplate(Document):
    grammar_point_code: str
    cefr_level: str
    exercise_type: str  # "fill_blank" | "error_correction" | "free_form"

    class Settings:
        name = "drill_templates"


class GeneratedDrill(Document):
    template: Link[DrillTemplate]
    grammar_point_code: str
    cefr_level: str
    exercise_type: str
    prompt: str
    correct_answer: Optional[str] = None
    distractors: List[str] = Field(default_factory=list)
    items: List[DrillItem] = Field(default_factory=list)  # multi-item drills (fill_blank, error_correction)
    topic_used: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    used: bool = False
    rag_refs: List[str] = Field(default_factory=list)  # RAG chunk refs used during generation

    class Settings:
        name = "generated_drills"


class DrillAttempt(Document):
    generated_drill: Link[GeneratedDrill]
    student_answer: str
    correct: Optional[bool] = None
    learning_event: Optional[Link[LearningEvent]] = None
    attempted_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "drill_attempts"


@dataclass
class ItalianChunkResult:
    chunk: ItalianChunk
    similarity: float


class GrammarPointExplanation(Document):
    grammar_point: Link["GrammarPoint"]
    student_level: str    # "A1" | "A2" | "B1" | "B2"
    explanation: str      # markdown, tailored to this CEFR level

    class Settings:
        name = "grammar_point_explanations"


# --- Lezione ---

class LessonTopic(BaseModel):
    title: str                        # e.g. "Chiedere informazioni in farmacia"
    description: str                  # 1-2 sentences on what real-world situation this covers
    cf_codes: List[str]               # 2-4 CF codes anchoring this topic
    depth: int = 1                    # 1=introduction, 2=develops prior, 3=advanced
    builds_on: Optional[str] = None   # title of the prior lesson this extends (depth > 1)


class LessonActivity(BaseModel):
    type: str           # "drill" | "vocab_review" | "reading" | "writing" | "grammar" | "speaking" | "conversazione"
    title: str
    description: str
    duration_minutes: int
    status: str = "pending"   # "pending" | "active" | "completed" | "skipped"
    # Content references (set when lesson is created)
    drill_id: Optional[PydanticObjectId] = None
    card_ids: List[PydanticObjectId] = []
    content: Optional[str] = None    # generated text for reading/writing/grammar
    questions: List[str] = []        # comprehension questions for reading
    correct_answers: List[str] = []  # expected answers for reading
    result: Optional[dict] = None
    why_important: Optional[str] = None  # 1-2 sentence motivation for grammar activities


class Lesson(Document):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "planning"  # "planning" | "active" | "completed" | "abandoned"
    duration_minutes: int = 20
    topic: Optional[LessonTopic] = None
    activities: List[LessonActivity] = []
    current_index: int = 0
    cefr_at_start: str = "A1"
    overview: Optional[str] = None          # 2-3 sentence lesson overview
    feedback_summary: Optional[str] = None  # post-lesson AI feedback
    generating: bool = True                 # True while background LLM generation is in progress

    class Settings:
        name = "lessons"
