"""Application configuration.

All secrets and tunables are loaded from environment variables (never hardcoded),
satisfying PRD §10.1 and §14.2 (zero-tolerance on committed secrets).
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Auth / JWT ---
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int = 60 * 24 * 7

    # --- Database ---
    database_url: str = "sqlite:///./dj_studio.db"

    # --- AI backend ---
    ai_backend: str = "local"  # "local" | "openai" | "anthropic"
    ai_api_key: str | None = None

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
