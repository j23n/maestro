from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_HOST: str = "localhost"
    MONGODB_PORT: int = 27017
    MONGODB_DB: str = "maestro"
    MONGODB_USER: str
    MONGODB_PASSWORD: str
    ANTHROPIC_API_KEY: str
    CHAT_MODEL: str = "claude-opus-4-6"
    DRILL_MODEL: str = "claude-haiku-4-5-20251001"
    LESSON_MODEL: str = "claude-sonnet-4-6"
    SCORING_MODEL: str = "claude-sonnet-4-6"
    EVAL_MODEL: str = "claude-opus-4-6"
    DEFINITION_MODEL: str = "claude-sonnet-4-6"
    EXPLANATION_MODEL: str = "claude-sonnet-4-6"
    TARGET_LANGUAGE: str = "it"              # ISO 639-1
    TARGET_LANGUAGE_NAME: str = "Italian"    # for LLM prompts
    SPACY_MODEL: str = "it_core_news_md"    # per-language NLP model

    @property
    def database_url(self) -> str:
        return f"mongodb://{self.MONGODB_USER}:{self.MONGODB_PASSWORD}@{self.MONGODB_HOST}:{self.MONGODB_PORT}/?authSource=admin&directConnection=true"

    model_config = {"env_file": ".env"}
