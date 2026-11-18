import os
import secrets
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core Application
    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "Real Estate Agentic Voice AI"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # Security & JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-insecure-secret-key-replace-in-production-32chars")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # Short-lived 15 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 7 days rotation lifespan

    # AES-256-GCM Transcript Encryption Key (Must be 32 raw bytes, or 64 hex characters)
    # Default is a deterministic dev key, can be overridden via ENCRYPTION_MASTER_KEY in .env
    ENCRYPTION_MASTER_KEY: str = os.getenv(
        "ENCRYPTION_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"  # 64-char hex = 32 bytes
    )

    # Database URLs
    # Default uses PostgreSQL asyncpg; SQLite aiosqlite can be used for tests and zero-service environments
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/realestate_ai"
    )
    TEST_DATABASE_URL: str = os.getenv(
        "TEST_DATABASE_URL",
        "sqlite+aiosqlite:///:memory:"
    )

    # Voice AI & AWS Bedrock
    USE_MOCK_VOICE: bool = True  # Mandatory default for zero-cost credential-free dev
    LIVE_TEST_APPROVED: bool = False  # Mandatory safety latch: must be True to allow live Bedrock inference
    MAX_CONCURRENT_LIVE_SESSIONS: int = 1  # Maximum concurrent live test sessions
    LIVE_TEST_MAX_SESSION_SECONDS: int = 60  # Strict short duration limit (60 seconds) for preflight/live tests
    DRY_RUN_TEST_MODE: bool = False  # When True, prevents production database writes during live testing
    BEDROCK_MODEL_ID: str = "amazon.nova-2-5-sonic"
    AWS_PROFILE: Optional[str] = os.getenv("AWS_PROFILE", None)
    AWS_REGION: str = os.getenv("AWS_REGION", "ap-northeast-1")
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_SESSION_TOKEN: Optional[str] = None

    # Nova 2.5 Sonic Voice & Inference Configuration
    NOVA_SONIC_VOICE_ID: str = "matthew"
    NOVA_SONIC_TEMPERATURE: float = 0.7
    NOVA_SONIC_TOP_P: float = 0.9
    NOVA_SONIC_MAX_TOKENS: int = 1024
    NOVA_SONIC_INPUT_SAMPLE_RATE: int = 24000
    NOVA_SONIC_OUTPUT_SAMPLE_RATE: int = 24000

    # Storage Paths
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "storage/uploads")
    AUDIO_STORAGE_DIR: str = os.getenv("AUDIO_STORAGE_DIR", "storage/audio")


settings = Settings()
