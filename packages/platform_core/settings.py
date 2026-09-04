from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"
    app_secret_key: SecretStr = SecretStr("development-only-secret")
    database_url: str = "postgresql+psycopg://zhixi:zhixi-local-only@localhost:5432/zhixi"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("zhixi-local")
    s3_secret_key: SecretStr = SecretStr("zhixi-local-secret")
    s3_bucket: str = "zhixi-artifacts"
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("app_secret_key")
    @classmethod
    def reject_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("APP_SECRET_KEY must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
