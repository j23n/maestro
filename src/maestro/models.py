from typing import Literal, Optional, List
from datetime import datetime, date
from dataclasses import dataclass
from enum import Enum
from beanie import Document, Link, PydanticObjectId
from pymongo import IndexModel, ASCENDING, DESCENDING
from pydantic import BaseModel, Field
from maestro.utils import utcnow


class ActivityType(str, Enum):
    DRILL = "drill"
    VOCAB_REVIEW = "vocab_review"
    READING = "reading"
    LISTENING = "listening"
    WRITING = "writing"
    GRAMMAR = "grammar"
    SPEAKING = "speaking"
    ONBOARDING = "onboarding"


class ActivityStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class LessonStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ExerciseType(str, Enum):
    FILL_BLANK = "fill_blank"
    ERROR_CORRECTION = "error_correction"


class CallType(str, Enum):
    LESSON_PLAN = "lesson_plan"
    ANALYZER = "analyzer"
    SCORER_SINGLE = "scorer_single"
    SCORER_MULTI = "scorer_multi"
    LESSON_FEEDBACK = "lesson_feedback"
    LESSON_ANALYZER_CF1 = "lesson_analyzer_cf1"
    LESSON_ANALYZER_CF2 = "lesson_analyzer_cf2"
    VOCAB_DEFINITION = "vocab_definition"
    GRAMMAR_EXPLANATION = "grammar_explanation"


class Student(Document):
    name: str = Field(default="", max_length=30)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "students"


class Account(Document):
    email: str
    password_hash: str
    email_verified: bool = False
    student_id: PydanticObjectId
    stripe_customer_id: Optional[str] = None
    subscription_tier: Literal["free", "pro"] = "free"
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "accounts"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
        ]


class CurriculumScenario(Document):
    slug: str  # "al-bar" (unique)
    label: str  # "Al bar"
    description: str  # English description of the scenario
    cefr_level: str  # "A1"
    cf_codes: List[str]  # CF codes exercised in this scenario
    gp_codes: List[str]  # GP codes exercised in this scenario
    depths: List[str]  # index 0 = depth 1, etc. Always 3 entries for A1+, 1 for A0.
    sequence: Optional[int] = None  # sequential ordering for A0 lessons (1-10)
    language: str = "it"

    class Settings:
        name = "curriculum_scenarios"


class StudentPersona(BaseModel):
    background: str = ""  # "Chi sei?" — student, retired, finance worker...
    interests: str = ""  # "Cosa ti piace?" — cooking, travel, wine...
    goal: str = ""  # "Perché l'italiano?" — travel, family, work...


class ScenarioProgress(BaseModel):
    depth: int = 0  # highest depth completed (0 = unvisited)
    last_visited: Optional[datetime] = None
    lesson_count: int = 0


class GrammarChunk(Document):
    ref: str = Field(unique=True)
    content: str
    chunk_type: str
    embedding: List[float]
    chunk_metadata: dict = {}
    language: str = "it"

    class Settings:
        name = "grammar_chunks"


class Sense(BaseModel):
    definition: str
    examples: List[str] = []
    synonyms: List[str] = []
    antonyms: List[str] = []
    pos: Optional[str] = None  # only if different from entry-level POS
    style: Optional[str] = None  # "figurato", "aulico", etc.


class VocabularyWord(Document):
    word: str = Field(unique=True)
    syllabization: Optional[str] = None  # "af-flùs-so" (no brackets)
    part_of_speech: str  # raw abbrev: "s.m.", "v.tr.", etc.
    cefr_level: Optional[str] = None  # A1–B2, or None for non-CEFR entries
    entry_id: Optional[str] = None  # "LM-00595"
    senses: List[Sense] = []  # all senses from EPUB
    audio_path: Optional[str] = None  # /static/audio/word_{slug}.wav
    language: str = "it"

    class Settings:
        name = "vocabulary_words"


class CefrSense(BaseModel):
    definition: str
    translation: str = ""  # English gloss for this specific sense
    examples: List[str] = []


class VocabularyWordDefinition(Document):
    word: Link["VocabularyWord"]
    student_level: str  # "A1" | "A2" | "B1" | "B2"
    senses: List[CefrSense]
    translation: str  # single English word or short phrase
    language: str = "it"

    class Settings:
        name = "vocabulary_word_definitions"


class UserVocabularyCard(Document):
    student_id: Optional[PydanticObjectId] = None
    word: Link[VocabularyWord]
    discovered_at: datetime = Field(default_factory=utcnow)
    ease_factor: float = 2.5
    interval: int = 1
    repetitions: int = 0
    next_review: date = Field(default_factory=date.today)

    class Settings:
        name = "user_vocabulary_cards"
        indexes = [
            IndexModel([("student_id", ASCENDING), ("next_review", ASCENDING)]),
            IndexModel([("student_id", ASCENDING), ("word", ASCENDING)]),
        ]


# --- Learning outcome taxonomy ---


class GrammarExplanation(BaseModel):
    """Language-specific explanation for a grammar point, stored inline on GrammarPoint."""

    title: str = ""
    tip: str = ""
    explanation: str
    language: str = "en"  # "en" or "it"


class GrammarPoint(Document):
    code: str
    unistr_code: str = ""  # original verbose code before short-code migration
    label: str
    unistr_label: str = ""  # original verbose label before short-label migration
    cefr_level: str
    category: str
    chunk_ref: Optional[str] = (
        None  # GrammarChunk.ref — set from mapping file at ingest
    )
    explanations: dict[str, GrammarExplanation] = Field(default_factory=dict)
    language: str = "it"

    class Settings:
        name = "grammar_points"


class CommunicativeFunction(Document):
    code: str
    label: str
    macro_category: str
    cefr_level: str
    patterns: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    description: str = ""  # built from patterns at ingest; used in analyzer prompt
    source_url: str = ""
    language: str = "it"

    class Settings:
        name = "comm_functions"


# --- Learning events and profile ---


class LearningEvent(Document):
    student_id: Optional[PydanticObjectId] = None
    lesson_id: Optional[PydanticObjectId] = None
    activity_type: Optional[str] = None
    activity_index: Optional[int] = None
    student_text: str = ""
    grammar_correct: List[str] = Field(default_factory=list)
    grammar_errors: List[str] = Field(default_factory=list)
    functions_performed: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    feedback: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "learning_events"
        indexes = [
            IndexModel([("student_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("lesson_id", ASCENDING)]),
        ]


class LearningProfile(Document):
    student_id: Optional[PydanticObjectId] = None
    grammar_correct_counts: dict = Field(default_factory=dict)
    grammar_error_counts: dict = Field(default_factory=dict)
    grammar_recent_outcomes: dict = Field(
        default_factory=dict
    )  # code → list[bool], sliding window of last 10
    functions_counts: dict = Field(default_factory=dict)
    themes_seen: List[str] = Field(default_factory=list)
    cefr_estimate: str = "A0"
    description: str = ""
    updated_at: datetime = Field(default_factory=utcnow)
    persona: StudentPersona = Field(default_factory=StudentPersona)
    scenario_progress: dict[str, ScenarioProgress] = Field(default_factory=dict)
    target_language: str = "it"

    class Settings:
        name = "learning_profile"
        indexes = [
            IndexModel([("student_id", ASCENDING)], unique=True),
        ]


# --- Drills ---


class DrillItem(BaseModel):
    prompt: str
    correct_answer: Optional[str] = None


class GeneratedDrill(Document):
    student_id: Optional[PydanticObjectId] = None
    grammar_point_code: str
    cefr_level: str
    exercise_type: ExerciseType
    prompt: str
    correct_answer: Optional[str] = None
    distractors: List[str] = Field(default_factory=list)
    items: List[DrillItem] = Field(
        default_factory=list
    )  # multi-item drills (fill_blank, error_correction)
    scenario_slug: Optional[str] = None
    generated_at: datetime = Field(default_factory=utcnow)
    used: bool = False
    chunk_ref: Optional[str] = None  # GrammarChunk.ref from the GP's chunk_ref

    class Settings:
        name = "generated_drills"
        indexes = [
            IndexModel([("student_id", ASCENDING), ("used", ASCENDING)]),
        ]


class DrillAttempt(Document):
    student_id: Optional[PydanticObjectId] = None
    generated_drill: Link[GeneratedDrill]
    student_answer: str
    correct: Optional[bool] = None
    attempted_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "drill_attempts"
        indexes = [
            IndexModel([("student_id", ASCENDING)]),
        ]


@dataclass
class GrammarChunkResult:
    chunk: GrammarChunk
    similarity: float


# --- Lezione ---


class LessonActivity(BaseModel):
    type: ActivityType  # "drill" | "vocab_review" | "reading" | "writing" | "grammar" | "speaking" | "onboarding"
    title: str
    description: str
    duration_minutes: int = 2
    status: ActivityStatus = (
        ActivityStatus.PENDING
    )  # "pending" | "active" | "completed" | "skipped"
    # Content references (set when lesson is created)
    drill_id: Optional[PydanticObjectId] = None
    card_ids: List[PydanticObjectId] = Field(default_factory=list)
    content: Optional[str] = None  # generated text for reading/writing/grammar
    questions: List[str] = Field(
        default_factory=list
    )  # comprehension questions for reading
    correct_answers: List[str] = Field(
        default_factory=list
    )  # expected answers for reading
    result: Optional[dict] = None
    why_important: Optional[str] = (
        None  # 1-2 sentence motivation for grammar activities
    )
    hint: Optional[str] = None  # optional hint shown on request (drills)
    profile_field: Optional[str] = (
        None  # for onboarding activities: "name", "background", "interests", "goal"
    )
    response_template: Optional[str] = (
        None  # shown after onboarding submit, supports {answer} placeholder
    )
    grammar_point_code: Optional[str] = None
    audio_path: Optional[str] = None  # /static/audio/lesson_{id}_{idx}.wav


class Lesson(Document):
    student_id: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: LessonStatus = (
        LessonStatus.PLANNING
    )  # "planning" | "active" | "completed" | "abandoned"
    duration_minutes: int = 20
    scenario_slug: Optional[str] = None
    scenario_depth: Optional[int] = None
    topic_title: Optional[str] = None
    topic_description: Optional[str] = None
    activities: List[LessonActivity] = []
    current_index: int = 0
    cefr_at_start: str = "A0"
    overview: Optional[str] = None  # 2-3 sentence lesson overview
    lesson_context: Optional[str] = None  # per-lesson coloring text from student
    focus_weak: bool = False  # when True, grammar selection ignores scenario constraint
    feedback_summary: Optional[str] = None  # post-lesson AI feedback
    generating: bool = True  # True while background LLM generation is in progress
    generation_error: Optional[str] = None  # set when background generation fails
    language: str = "it"

    class Settings:
        name = "lessons"
        indexes = [
            IndexModel([("student_id", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("student_id", ASCENDING), ("created_at", DESCENDING)]),
        ]


class LLMUsageRecord(Document):
    student_id: Optional[PydanticObjectId] = None
    entity_id: PydanticObjectId
    call_type: CallType
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "llm_usage_records"
        indexes = [
            IndexModel([("student_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("entity_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("call_type", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]


class LLMCritique(Document):
    call_type: CallType
    url: str
    refs: dict  # call_type-specific DB references
    prompt_version: str
    input_snapshot: dict  # reconstructed LLM inputs at flag time
    actual_output: dict  # reconstructed LLM output at flag time
    issue_description: str = ""
    expected_output: Optional[str] = None
    exported: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "llm_critiques"
        indexes = [
            IndexModel(
                [
                    ("call_type", ASCENDING),
                    ("exported", ASCENDING),
                    ("created_at", DESCENDING),
                ]
            ),
            IndexModel([("created_at", DESCENDING)]),
        ]


ALL_DOCUMENT_MODELS = [
    Student,
    Account,
    CurriculumScenario,
    GrammarChunk,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
    GrammarPoint,
    CommunicativeFunction,
    LearningEvent,
    LearningProfile,
    GeneratedDrill,
    DrillAttempt,
    Lesson,
    LLMUsageRecord,
    LLMCritique,
]
