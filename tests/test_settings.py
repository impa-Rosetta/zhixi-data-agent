import pytest
from pydantic import ValidationError

from packages.platform_core.settings import Settings


def test_empty_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(app_secret_key="")


def test_secret_is_not_exposed_in_repr() -> None:
    settings = Settings(app_secret_key="top-secret")
    assert "top-secret" not in repr(settings)
