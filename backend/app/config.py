from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "sqlite:///./migrationpilot.db"
    nvidia_api_key: str = ""
    nvidia_base_url: AnyHttpUrl = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "openai/gpt-oss-20b"
    jwt_secret: str = Field(default="change-me-for-local-demo", min_length=16)
    jwt_expires_minutes: int = 5_256_000
    auth_disabled: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )
    langgraph_strict_msgpack: bool = True
    langgraph_checkpoint_path: str = "storage/langgraph_checkpoints.sqlite"
    upload_storage_dir: str = "storage/source_files"


@lru_cache
def get_settings() -> Settings:
    return Settings()
