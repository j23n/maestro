from typing import Literal, Optional, List
from datetime import datetime, date
from enum import Enum
from beanie import Document, Link, PydanticObjectId
from pymongo import IndexModel, ASCENDING, DESCENDING
from pydantic import BaseModel, Field, model_validator
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
    INFO = "info"
    INTRO = "intro"


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
    AUGMENT_GP = "augment_gp"
    AUGMENT_CF = "augment_cf"
    STORYLINE_EVOLVE = "storyline_evolve"


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
    overview: str = ""  # 2-3 sentence lesson overview
    image: str = ""  # path relative to /static (e.g. "images/a0-01-in-aereo.png")
    scene_setting: str = ""  # narrative intro paragraph for the lesson intro activity
    outro: str = ""  # narrative recap shown on the lesson completion page
    cefr_level: str  # "A1"
    cf_codes: List[str]  # CF codes exercised in this scenario
    gp_codes: List[str]  # GP codes exercised in this scenario
    depths: List[str]  # index 0 = depth 1, etc. Always 3 entries for A1+, 1 for A0.
    sequence: Optional[int] = None  # sequential ordering for A0 lessons (1-10)
    phase: int = 1  # A1 curriculum phase: 1, 2, or 3
    language: str = "it"

    class Settings:
        name = "curriculum_scenarios"
        indexes = [
            IndexModel([("cefr_level", ASCENDING)]),
            IndexModel([("slug", ASCENDING)], unique=True),
        ]


class StudentPersona(BaseModel):
    background: str = ""  # "Chi sei?" — student, retired, finance worker...
    interests: str = ""  # "Cosa ti piace?" — cooking, travel, wine...
    goal: str = ""  # "Perché l'italiano?" — travel, family, work...


class ScenarioProgress(BaseModel):
    depth: int = 0  # highest depth completed (0 = unvisited)
    last_visited: Optional[datetime] = None
    lesson_count: int = 0


class LanguageProgress(BaseModel):
    grammar_correct_counts: dict = Field(default_factory=dict)
    grammar_error_counts: dict = Field(default_factory=dict)
    grammar_recent_outcomes: dict = Field(
        default_factory=dict
    )  # code → list[{ok: bool, ts: str} | bool], sliding window of last 10
    grammar_mastery_scores: dict = Field(
        default_factory=dict
    )  # code → float, weighted mastery score
    grammar_introduced: List[str] = Field(default_factory=list)
    functions_counts: dict = Field(default_factory=dict)
    scenario_progress: dict[str, ScenarioProgress] = Field(default_factory=dict)
    cefr_estimate: str = "A0"
    onboarding_completed: bool = False
    onboarding_skipped: bool = False
    description: str = ""
    storyline: str = ""
    storyline_lessons_since_evolve: int = 0
    storyline_updated_at: Optional[datetime] = None


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
    word: str
    syllabization: Optional[str] = None  # "af-flùs-so" (no brackets)
    ipa: Optional[str] = None  # IPA transcription, e.g. /ˈbɪtə/
    part_of_speech: str  # raw abbrev: "s.m.", "v.tr.", etc.
    cefr_level: Optional[str] = None  # A1–B2, or None for non-CEFR entries
    entry_id: Optional[str] = None  # "LM-00595"
    senses: List[Sense] = []  # all senses from EPUB
    language: str = "it"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def audio_url(self) -> Optional[str]:
        """Return the static URL for this word's audio, or None if the file doesn't exist."""
        from maestro.tts import word_audio_path

        path = word_audio_path(self.word, language=self.language)
        lang = self.language
        return f"/static/audio/{lang}/{path.name}" if path.exists() else None

    class Settings:
        name = "vocabulary_words"
        indexes = [
            IndexModel(
                [
                    ("word", ASCENDING),
                    ("part_of_speech", ASCENDING),
                    ("language", ASCENDING),
                ],
                unique=True,
            ),
        ]


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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Settings:
        name = "vocabulary_word_definitions"


class UserVocabularyCard(Document):
    student_id: Optional[PydanticObjectId] = None
    word: Link[VocabularyWord]
    language: str = "it"  # denormalized from VocabularyWord.language
    discovered_at: datetime = Field(default_factory=utcnow)
    ease_factor: float = 2.5
    interval: int = 1
    repetitions: int = 0
    next_review: date = Field(default_factory=date.today)
    excluded: bool = False

    class Settings:
        name = "user_vocabulary_cards"
        indexes = [
            IndexModel(
                [
                    ("student_id", ASCENDING),
                    ("language", ASCENDING),
                    ("excluded", ASCENDING),
                    ("next_review", ASCENDING),
                ]
            ),
            IndexModel([("student_id", ASCENDING), ("word", ASCENDING)]),
        ]


# --- Learning outcome taxonomy ---


class Explanation(BaseModel):
    """Language-specific explanation stored inline on GrammarPoint or CommunicativeFunction."""

    title: str = ""
    tip: str = ""  # 2-3 sentence plain-language summary; shown as tooltip on incorrect usage in activity feedback
    why_this_matters: str = ""
    explanation: str
    language: str = "en"  # "en" or "it"


class GrammarPoint(Document):
    code: str
    label: str
    cefr_level: str
    category: str
    subcategory: str = ""
    description: str = ""
    examples: List[str] = Field(default_factory=list)
    source_note: str = ""
    chunk_ref: Optional[str] = (
        None  # GrammarChunk.ref — set from mapping file at ingest
    )
    prerequisites: List[str] = Field(
        default_factory=list
    )  # GP codes that must be introduced first
    explanations: dict[str, Explanation] = Field(default_factory=dict)
    language: str = "it"

    class Settings:
        name = "grammar_points"


class CommunicativeFunction(Document):
    code: str
    label: str
    category: str
    cefr_level: str
    patterns: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    description: str = ""  # built from patterns at ingest; used in analyzer prompt
    explanations: dict[str, Explanation] = Field(default_factory=dict)
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
    evidence_type: Optional[str] = None  # "targeted" | "productive" | "receptive"
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
    target_language: str = "it"
    persona: StudentPersona = Field(default_factory=StudentPersona)
    progress: dict[str, LanguageProgress] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def active_progress(self) -> LanguageProgress:
        """Return LanguageProgress for the current target_language.

        Lazily initializes an empty LanguageProgress if the language key
        doesn't exist yet (e.g. when switching to a new language).
        """
        lang = self.target_language
        if lang not in self.progress:
            self.progress[lang] = LanguageProgress()
        return self.progress[lang]

    class Settings:
        name = "learning_profile"
        indexes = [
            IndexModel([("student_id", ASCENDING)], unique=True),
        ]


# --- Drills ---


class QuestionItem(BaseModel):
    """Structured comprehension question for reading/listening activities."""

    text: str
    correct_answer: str = ""
    grammar_point_codes: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_string(cls, data):
        """Accept plain strings (legacy DB docs / LLM output) as question text."""
        if isinstance(data, str):
            return {"text": data}
        return data


class DrillItem(BaseModel):
    prompt: str
    correct_answer: Optional[str] = None
    grammar_point_code: Optional[str] = None  # overrides drill-level GP


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
            IndexModel([("grammar_point_code", ASCENDING), ("used", ASCENDING)]),
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


# --- Lezione ---


class LessonActivity(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_questions(cls, data):
        """Coerce pre-QuestionItem documents: questions=[str] + correct_answers=[str]."""
        if isinstance(data, dict):
            qs = data.get("questions")
            if qs and isinstance(qs, list) and qs and isinstance(qs[0], str):
                answers = data.pop("correct_answers", [])
                data["questions"] = [
                    {
                        "text": q,
                        "correct_answer": answers[i] if i < len(answers) else "",
                    }
                    for i, q in enumerate(qs)
                ]
            elif "correct_answers" in data:
                data.pop("correct_answers")
        return data

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
    review_scope: Optional[Literal["due", "discovered"]] = None
    content: Optional[str] = None  # generated text for reading/writing/grammar
    questions: List[QuestionItem] = Field(
        default_factory=list
    )  # structured comprehension questions for reading/listening
    grammar_point_codes: List[str] = Field(
        default_factory=list
    )  # GP codes for writing/speaking activities
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
    grammar_label: Optional[str] = (
        None  # short label for grammar activities (e.g. "Articoli")
    )
    cf_codes: List[str] = Field(default_factory=list)  # communicative function codes
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
    generation_started_at: Optional[datetime] = None  # set when generation begins
    generation_error: Optional[str] = None  # set when background generation fails
    archetype: Optional[str] = None  # "introduction", "consolidation", "application"
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


class InterestRegistration(Document):
    email: str
    token: str
    verified: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "interest_registrations"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("token", ASCENDING)], unique=True),
        ]


ALL_DOCUMENT_MODELS = [
    Student,
    Account,
    InterestRegistration,
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
