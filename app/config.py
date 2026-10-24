"""
app/config.py
Application configuration using pydantic-settings.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AI Settings
    primary_ai_provider: str = "auto"

    # Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # App Settings
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = False

    # Database
    database_path: str = "./quiz_assistant.db"

    # Browser
    browser_headless: bool = False
    browser_timeout_ms: int = 30000

    # Security
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Moodle Credentials (optional auto-login)
    moodle_username: str = ""
    moodle_password: str = ""

    # Groq API Fallback
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Ollama Local Fallback
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key != "your_gemini_api_key_here")

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key != "your_groq_api_key_here")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
