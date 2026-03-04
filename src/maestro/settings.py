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

    @property
    def database_url(self) -> str:
        return f"mongodb://{self.MONGODB_USER}:{self.MONGODB_PASSWORD}@{self.MONGODB_HOST}:{self.MONGODB_PORT}/?authSource=admin&directConnection=true"

    model_config = {"env_file": ".env"}
