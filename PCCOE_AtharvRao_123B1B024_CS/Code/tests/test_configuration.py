from app.core.config import Settings
from pytest import MonkeyPatch


def test_settings_have_safe_development_defaults(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.database_url is None
