from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_transcription_model: str = "whisper-1"
    openai_vision_model: str = "gpt-4o-mini"

    redis_url: str = "redis://localhost:6379/0"

    buffer_debounce_seconds: float = 8.0
    buffer_max_messages: int = 20
    buffer_key_ttl_seconds: int = 3600

    whatsapp_provider: Literal["zapi", "meta_cloud"] = "zapi"

    zapi_instance_id: str = ""
    zapi_token: str = ""
    zapi_client_token: str = ""

    log_level: str = "INFO"
    log_pretty: bool = False

    webhook_dedup_ttl_seconds: int = 3600

    leads_fake_path: str = "data/leads_fake.json"


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
