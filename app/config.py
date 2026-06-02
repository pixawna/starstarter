from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_api_base_url: str = "https://api.github.com"
    github_token: str | None = None
    github_auth_username: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    app_name: str = "StarStarter"
    app_url: str | None = None
    http_timeout_seconds: float = Field(default=20.0, ge=1.0)
    openrouter_timeout_seconds: float = Field(default=4.0, ge=1.0)
    github_email_scraper_timeout_seconds: float = Field(default=8.0, ge=1.0)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
