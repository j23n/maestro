from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_URL: str = "mongodb://localhost:27017/maestro"
    MONGODB_DB: str = "maestro"
    ANTHROPIC_API_KEY: str
    SECRET_KEY: str
    ENVIRONMENT: str = "development"
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    CHAT_MODEL: str = "claude-opus-4-6"
    DRILL_MODEL: str = "claude-haiku-4-5-20251001"
    LESSON_MODEL: str = "claude-sonnet-4-6"
    SCORING_MODEL: str = "claude-sonnet-4-6"
    EVAL_MODEL: str = "claude-opus-4-6"
    DEFINITION_MODEL: str = "claude-sonnet-4-6"
    EXPLANATION_MODEL: str = "claude-sonnet-4-6"
    TARGET_LANGUAGE: str = "it"  # ISO 639-1
    TARGET_LANGUAGE_NAME: str = "Italian"  # for LLM prompts
    SPACY_MODEL: str = "it_core_news_md"  # per-language NLP model
    LOG_LEVEL: str = "INFO"
    FREE_TIER_LESSON_LIMIT_EX_A0: int = 999
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = "eastus"
    AZURE_TTS_VOICE: str = "it-IT-IsabellaNeural"

    model_config = {"env_file": ".env"}
