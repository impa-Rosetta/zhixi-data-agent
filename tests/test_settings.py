import pytest
from pydantic import ValidationError

from packages.platform_core.settings import DEVELOPMENT_DATA_SOURCE_KEYRING, Settings, get_settings


def test_empty_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(app_secret_key="")


def test_secret_is_not_exposed_in_repr() -> None:
    settings = Settings(app_secret_key="top-secret")
    assert "top-secret" not in repr(settings)


def test_invalid_data_source_keyring_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            data_source_master_keys='{"v1":"dG9vLXNob3J0"}', data_source_active_key_version="v1"
        )


def test_active_data_source_key_must_exist() -> None:
    with pytest.raises(ValidationError):
        Settings(data_source_active_key_version="missing")


def test_production_rejects_development_data_source_key() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", data_source_master_keys=DEVELOPMENT_DATA_SOURCE_KEYRING)


def test_data_source_key_is_not_exposed_in_repr() -> None:
    encoded = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    settings = Settings(
        data_source_master_keys=f'{{"v1":"{encoded}"}}',
        data_source_active_key_version="v1",
    )
    assert encoded not in repr(settings)
    assert settings.data_source_master_keyring() == {"v1": b"a" * 32}


def test_metadata_scan_object_limit_is_bounded() -> None:
    with pytest.raises(ValidationError, match="METADATA_SCAN_MAX_OBJECTS"):
        Settings(metadata_scan_max_objects=1)


def test_cached_settings_factory_returns_settings() -> None:
    get_settings.cache_clear()
    assert isinstance(get_settings(), Settings)
