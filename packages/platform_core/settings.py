import base64
import binascii
import json
from functools import lru_cache
from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_DATA_SOURCE_KEYRING = '{"dev-v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}'


def decode_master_keyring(raw: str) -> dict[str, bytes]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("DATA_SOURCE_MASTER_KEYS must be a JSON object") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("DATA_SOURCE_MASTER_KEYS must contain at least one key")
    decoded: dict[str, bytes] = {}
    for version, encoded in parsed.items():
        if not isinstance(version, str) or not version or not isinstance(encoded, str):
            raise ValueError("DATA_SOURCE_MASTER_KEYS entries must be string pairs")
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Master key {version!r} is not valid base64") from exc
        if len(key) != 32:
            raise ValueError(f"Master key {version!r} must decode to 32 bytes")
        decoded[version] = key
    return decoded


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"
    app_secret_key: SecretStr = SecretStr("development-only-secret-change-me-32")
    data_source_master_keys: SecretStr = SecretStr(DEVELOPMENT_DATA_SOURCE_KEYRING)
    data_source_active_key_version: str = "dev-v1"
    data_source_allowed_private_cidrs: list[str] = []
    data_source_allowed_ports: list[int] = [5432, 3306]
    database_url: str = "postgresql+psycopg://zhixi:zhixi-local-only@localhost:5432/zhixi"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("zhixi-local")
    s3_secret_key: SecretStr = SecretStr("zhixi-local-secret")
    s3_bucket: str = "zhixi-artifacts"
    cors_origins: list[str] = ["http://localhost:5173"]
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60

    @field_validator("app_secret_key")
    @classmethod
    def reject_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("APP_SECRET_KEY must not be empty")
        return value

    @model_validator(mode="after")
    def validate_data_source_security(self) -> Self:
        keys = decode_master_keyring(self.data_source_master_keys.get_secret_value())
        if self.data_source_active_key_version not in keys:
            raise ValueError("DATA_SOURCE_ACTIVE_KEY_VERSION is missing from the keyring")
        if self.app_env.lower() in {"prod", "production"} and (
            self.data_source_master_keys.get_secret_value() == DEVELOPMENT_DATA_SOURCE_KEYRING
        ):
            raise ValueError("Production must provide a non-development data source master key")
        if not self.data_source_allowed_ports or any(
            port < 1 or port > 65535 for port in self.data_source_allowed_ports
        ):
            raise ValueError("DATA_SOURCE_ALLOWED_PORTS must contain valid TCP ports")
        return self

    def data_source_master_keyring(self) -> dict[str, bytes]:
        return decode_master_keyring(self.data_source_master_keys.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
