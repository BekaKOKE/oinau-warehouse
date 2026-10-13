from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import INSECURE_PLACEHOLDER, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
PRODUCTION_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.production.example"


def test_csv_lists_are_parsed() -> None:
    settings = Settings(CORS_ORIGINS="http://a.kz, http://b.kz")  # type: ignore[arg-type]
    assert settings.CORS_ORIGINS == ["http://a.kz", "http://b.kz"]


def test_csv_lists_accept_json_form() -> None:
    """Списки помечены NoDecode, поэтому JSON разбираем сами."""
    settings = Settings(CORS_ORIGINS='["http://a.kz","http://b.kz"]')  # type: ignore[arg-type]
    assert settings.CORS_ORIGINS == ["http://a.kz", "http://b.kz"]


def test_env_example_is_a_working_configuration(tmp_path: Path) -> None:
    """Чистая установка начинается с `cp .env.example .env`.

    Проверяется весь файл целиком: одна опечатка в нём — и первый запуск
    падает ещё до старта приложения. Отдельно закреплены пустые списки:
    комментарий в строке с пустым значением python-dotenv считает частью
    значения, и непустой INTEGRATION_IP_ALLOWLIST молча включил бы
    проверку IP, заблокировав интеграцию.
    """
    assert ENV_EXAMPLE.is_file(), f"Не найден {ENV_EXAMPLE}"
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    # Переменные процесса перекрыли бы файл — проверяем именно файл.
    overrides = {
        key: None
        for key in os.environ
        if key.split("_")[0] in {"POSTGRES", "REDIS", "S3", "CORS", "SECRET", "ENV", "RATE"}
    }
    saved = {key: os.environ.pop(key) for key in overrides}
    try:
        settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
    finally:
        os.environ.update(saved)

    assert settings.ENV == "local"
    assert settings.CORS_ORIGINS == ["http://localhost:3000", "http://localhost:3001"]
    assert settings.SUPPORTED_LOCALES == ["ru"]
    assert settings.UPLOAD_ALLOWED_MIME == ["image/jpeg", "image/png", "image/webp"]
    assert settings.NOTIFY_EMAILS == []
    assert settings.INTEGRATION_IP_ALLOWLIST == []
    # Значения по умолчанию рассчитаны на docker compose.
    assert settings.POSTGRES_HOST == "postgres"
    assert settings.REDIS_HOST == "redis"
    assert settings.S3_ENDPOINT_URL == "http://minio:9000"


def test_env_example_has_no_inline_comments_on_empty_values() -> None:
    """`KEY=   # текст` делает значением сам комментарий.

    Значение с содержимым python-dotenv от хвостового комментария очищает,
    а пустое — нет. Правило проверяется по файлу, потому что ошибка тихая:
    настройка получает мусорное значение вместо пустого.
    """
    offenders: list[str] = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        value = stripped.split("=", 1)[1].strip()
        if value.startswith("#"):
            offenders.append(stripped)

    assert offenders == [], f"Комментарий станет значением: {offenders}"


# Минимально корректная production-конфигурация. Тесты ниже портят
# ровно одно поле: так видно, какая именно проверка сработала.
PRODUCTION_SETTINGS: dict[str, object] = {
    "ENV": "production",
    "SECRET_KEY": "x" * 32,
    "POSTGRES_PASSWORD": "s3cret",
    "S3_SECRET_ACCESS_KEY": "s3cret",
    "CORS_ORIGINS": ["https://oinau-pro.kz"],
    "PUBLIC_SITE_URL": "https://oinau-pro.kz",
    "PUBLIC_ADMIN_URL": "https://oinau-pro.kz/admin",
    "CDN_BASE_URL": "https://cdn.oinau-pro.kz",
    "S3_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
    "SMTP_HOST": "smtp.oinau-pro.kz",
}


def production_settings(**overrides: object) -> Settings:
    return Settings(**{**PRODUCTION_SETTINGS, **overrides})  # type: ignore[arg-type]


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_production_example_covers_mandatory_settings() -> None:
    """Шаблон прод-окружения обязан содержать всё, без чего старт падает.

    Проверка по именам, а не по значениям: значения в шаблоне подставные.
    Если поле переименовали в коде и забыли в шаблоне, деплой сломается
    уже на сервере — этот тест ловит расхождение раньше.
    """
    assert PRODUCTION_EXAMPLE.is_file(), f"Не найден {PRODUCTION_EXAMPLE}"
    keys = _env_keys(PRODUCTION_EXAMPLE)
    mandatory = {
        "ENV",
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_ENDPOINT_URL",
        "S3_BUCKET",
        "CDN_BASE_URL",
        "CORS_ORIGINS",
        "PUBLIC_SITE_URL",
        "PUBLIC_ADMIN_URL",
        "SMTP_HOST",
        "TRUSTED_PROXY_HOPS",
    }
    assert mandatory <= keys, f"В шаблоне нет: {sorted(mandatory - keys)}"


def test_production_example_has_no_inline_comments_on_empty_values() -> None:
    """То же правило python-dotenv, что и для .env.example."""
    offenders = [
        line.strip()
        for line in PRODUCTION_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line
        and not line.strip().startswith("#")
        and line.strip().split("=", 1)[1].strip().startswith("#")
    ]
    assert offenders == [], f"Комментарий станет значением: {offenders}"


def test_production_example_is_not_a_secret_store() -> None:
    """В шаблоне не должно быть настоящих значений.

    Признак настоящего секрета — заполненное поле там, где положена
    заглушка. Проверяются поля, утечка которых даёт доступ наружу.
    """
    filled: list[str] = []
    for line in PRODUCTION_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split("=", 1))
        if key not in {
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "S3_ACCESS_KEY_ID",
            "S3_SECRET_ACCESS_KEY",
            "SMTP_PASSWORD",
            "TELEGRAM_BOT_TOKEN",
            "SENTRY_DSN",
        }:
            continue
        if value and "ЗАПОЛНИТЬ" not in value:
            filled.append(key)
    assert filled == [], f"Похоже на настоящие реквизиты в шаблоне: {filled}"


def test_docs_are_disabled_in_production() -> None:
    settings = production_settings()
    assert settings.docs_url is None
    assert settings.openapi_url is None


def test_production_rejects_default_secrets() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(ENV="production", SECRET_KEY=INSECURE_PLACEHOLDER)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        production_settings(CORS_ORIGINS=["*"])


@pytest.mark.parametrize(
    "field",
    ["PUBLIC_SITE_URL", "PUBLIC_ADMIN_URL", "CDN_BASE_URL", "S3_ENDPOINT_URL"],
)
def test_production_rejects_plain_http_public_urls(field: str) -> None:
    """Адрес по http в этих полях уезжает клиенту: в письмо или в <img>."""
    with pytest.raises(ValueError, match=field):
        production_settings(**{field: "http://oinau-pro.kz"})


@pytest.mark.parametrize(
    "field",
    ["PUBLIC_SITE_URL", "PUBLIC_ADMIN_URL", "CDN_BASE_URL", "S3_ENDPOINT_URL"],
)
def test_production_rejects_local_public_urls(field: str) -> None:
    """Локальный адрес открывается только на самом сервере."""
    with pytest.raises(ValueError, match=field):
        production_settings(**{field: "https://localhost:3000"})


def test_production_rejects_mail_catcher() -> None:
    """Mailpit в проде — это молча несобранные письма клиентам."""
    with pytest.raises(ValueError, match="SMTP_HOST"):
        production_settings(SMTP_HOST="mailpit")


def test_empty_thread_id_means_no_topic() -> None:
    """`TELEGRAM_MESSAGE_THREAD_ID=` в .env — это «темы нет», а не ошибка.

    Необязательные значения в .env принято оставлять пустыми. Без
    отдельного разбора pydantic пытался бы сделать из пустой строки
    число и не дал бы приложению стартовать.
    """

    def thread_id(raw: str) -> int | None:
        settings = Settings(TELEGRAM_MESSAGE_THREAD_ID=raw)  # type: ignore[arg-type]
        return settings.TELEGRAM_MESSAGE_THREAD_ID

    assert thread_id("") is None
    assert thread_id("  ") is None
    assert thread_id("42") == 42


@pytest.mark.parametrize("value", [0, -1, -1001234567890])
def test_thread_id_must_be_positive(value: int) -> None:
    """Отрицательное значение — это id чата, скопированный не в то поле."""
    with pytest.raises(ValueError, match="TELEGRAM_MESSAGE_THREAD_ID"):
        Settings(TELEGRAM_MESSAGE_THREAD_ID=value)


def test_database_urls_use_expected_drivers() -> None:
    settings = Settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.database_url_sync.startswith("postgresql+psycopg://")
