from pydantic import model_validator
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
    # Default/fallback language settings. Per-student language is resolved from
    # LearningProfile.target_language via language.py's LanguageConfig registry.
    TARGET_LANGUAGE: str = "it"  # ISO 639-1
    TARGET_LANGUAGE_NAME: str = "Italian"  # for LLM prompts
    UI_LANGUAGE: str = "en"  # ISO 639-1; language for UI chrome
    SPACY_MODEL: str = "it_core_news_md"  # per-language NLP model
    LOG_LEVEL: str = "INFO"
    FREE_TIER_LESSON_LIMIT_EX_A0: int = 999
    STATIC_DIR: str = "src/maestro/static"
    DATA_DIR: str = ""  # persistent volume for generated files; defaults to STATIC_DIR
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = "eastus"
    AZURE_TTS_VOICE: str = "it-IT-IsabellaNeural"
    MAILJET_API_KEY: str = ""
    MAILJET_SECRET_KEY: str = ""
    MAILJET_FROM_EMAIL: str = "Maestro <noreply@maestro.app>"
    SITE_URL: str = "http://localhost:8000"

    @model_validator(mode="after")
    def _default_data_dir(self) -> "Settings":
        if not self.DATA_DIR:
            self.DATA_DIR = self.STATIC_DIR
        return self

    model_config = {"env_file": ".env"}


settings = Settings()
