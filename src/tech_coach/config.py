"""
Application configuration using pydantic-settings.

In production, sensitive values are loaded from Google Secret Manager,
not from environment variables. This module handles both paths.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Environment = Environment.DEVELOPMENT
    app_secret_key: SecretStr = Field(
        default="change-me-in-production-use-secret-manager",
        description="JWT signing key",
    )
    debug: bool = False
    debug_mode: bool = True  # When True, bypass OAuth; use fixed DEBUG_USER_ID instead
    log_level: str = "INFO"

    # Google Cloud
    gcp_project_id: str = Field(default=..., description="GCP project ID")
    gcp_location: str = "us-central1"
    gcp_service_account_email: str = ""

    # Vertex AI
    vertex_ai_model_id: str = "gemini-1.5-pro-002"
    vertex_ai_embedding_model_id: str = "text-embedding-004"
    vertex_ai_location: str = "us-central1"

    # Database
    database_url: SecretStr = Field(
        default=...,
        description="PostgreSQL async URL. In prod, sourced from Secret Manager.",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_default_ttl_seconds: int = 86400

    # Auth (required when debug_mode=False; unused when debug_mode=True)
    google_client_id: str = Field(default="", description="Google OAuth client ID")
    google_client_secret: SecretStr = Field(
        default="", description="Google OAuth client secret"
    )
    oauth_redirect_uri: str = "http://localhost:8000/auth/callback"
    allowed_user_email: str = Field(
        default="",
        description="Single-user mode: only this email can authenticate",
    )

    # JWT
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480
    jwt_refresh_token_expire_days: int = 30

    # Evaluation
    eval_baseline_prompt_version: str = "coaching_dialogue:1.0.0"
    eval_pass_threshold: float = 0.85

    # Cost tracking (USD per 1k tokens)
    gemini_pro_input_price_per_1k: float = 0.00125
    gemini_pro_output_price_per_1k: float = 0.005
    gemini_flash_input_price_per_1k: float = 0.000075
    gemini_flash_output_price_per_1k: float = 0.0003

    # Frontend
    backend_url: str = "http://localhost:8000"

    @field_validator("app_secret_key", mode="before")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "change-me-in-production-use-secret-manager":
            import os

            if os.getenv("APP_ENV") == "production":
                raise ValueError(
                    "APP_SECRET_KEY must be set to a secure value in production. "
                    "Use Secret Manager."
                )
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return cached settings instance.

    In production, before calling this, Secret Manager values
    should be pre-loaded into the environment by the startup script.
    """
    return Settings()  # type: ignore[call-arg]
