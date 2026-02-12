import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API Keys
    GEMINI_API_KEY: str
    X_API_KEY: str  # Ye wo key hai jo frontend bhejega API call karte waqt
    REDIS_URL: str = os.getenv("REDIS_URL")
    # Backend Phoenix API
    BASE_URL: str = os.getenv("BASE_URL")

    # Server Config
    PORT: int = 8000

    # Pydantic configuration to read from .env file
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Singleton instance taaki har jagah same settings use hon
settings = Settings()
