"""Конфигурация приложения.

Единственный источник настроек. Ничего не читается из os.environ напрямую
в остальном коде — только через get_settings().
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]

# Списки задаются строкой "A,B,C" — так их пишут в .env и в docker compose.
# NoDecode отключает встроенный разбор значения как JSON: без него
# pydantic-settings падает на первой же запятой ещё до наших валидаторов,
# и запуск с готовым .env.example был бы невозможен.
CsvList = Annotated[list[str], NoDecode]

# Значение-заглушка. В production запуск с ним запрещён (см. _validate_production).
INSECURE_PLACEHOLDER = "change-me-in-env"  # nosec

# RFC 7518 §3.2: ключ HMAC-SHA256 короче 32 байт снижает стойкость подписи.
# Ровно столько даёт `openssl rand -hex 32`.
MIN_SECRET_KEY_LENGTH = 32

# Хосты, которые в production означают неверную конфигурацию, а не
# «пока не настроили»: с ними ссылки в письмах и адреса картинок
# указывают на машину, куда посетитель попасть не может.
LOCAL_HOSTNAMES = ("localhost", "127.0.0.1", "0.0.0.0", "::1")  # noqa: S104

# Локальные заглушки почты: письма из них наружу не уходят.
DEV_SMTP_HOSTS = ("mailpit", "mailhog", "localhost", "127.0.0.1")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------ общее
    ENV: Environment = "local"
    DEBUG: bool = False
    PROJECT_NAME: str = "OINAU-PRO API"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "console"

    # Регион по умолчанию. Не хардкодим Алматы в коде — только дефолт настройки.
    DEFAULT_REGION_CODE: str = "almaty"
    DEFAULT_CURRENCY: str = "KZT"
    DEFAULT_LOCALE: str = "ru"
    SUPPORTED_LOCALES: CsvList = ["ru"]  # "kk" добавляется без миграции схемы

    # -------------------------------------------------------------- PostgreSQL
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "oinau"
    POSTGRES_PASSWORD: str = INSECURE_PLACEHOLDER
    POSTGRES_DB: str = "oinau"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ------------------------------------------------------------------- Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # -------------------------------------------------- Object storage (R2/S3)
    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_REGION: str = "auto"
    S3_ACCESS_KEY_ID: str = INSECURE_PLACEHOLDER
    S3_SECRET_ACCESS_KEY: str = INSECURE_PLACEHOLDER
    S3_BUCKET: str = "oinau-media"
    # Адрес хранилища, которым подписываются presigned URL для браузера.
    # Пусто = S3_ENDPOINT_URL (так для R2). Локально backend ходит
    # в http://minio:9000, а браузеру нужен http://localhost:9000.
    S3_PUBLIC_ENDPOINT_URL: str | None = None
    # Базовый URL CDN. URL изображений собирается как CDN_BASE_URL + storage_key.
    # В БД хранится только storage_key — смена CDN не требует UPDATE.
    CDN_BASE_URL: str = "http://localhost:9000/oinau-media"
    UPLOAD_MAX_SIZE_MB: int = 15
    UPLOAD_PRESIGN_TTL_SECONDS: int = 600
    UPLOAD_ALLOWED_MIME: CsvList = ["image/jpeg", "image/png", "image/webp"]
    # Защита воркера от «декомпрессионной бомбы»: PNG в 100 КБ может
    # распаковаться в гигабайты пикселей. 50 Мп — с запасом для фото
    # с любой современной камеры.
    UPLOAD_MAX_IMAGE_PIXELS: int = 50_000_000
    # Документы медиатеки — схемы и чертежи товаров. Отдельный список
    # и лимит: PDF и DWG заметно тяжелее фотографий, а изображения
    # продолжают ограничиваться UPLOAD_ALLOWED_MIME / UPLOAD_MAX_SIZE_MB.
    UPLOAD_ALLOWED_DOCUMENT_MIME: CsvList = ["application/pdf", "image/vnd.dwg", "image/vnd.dxf"]
    UPLOAD_MAX_DOCUMENT_SIZE_MB: int = 50
    # Файл к запросу КП из окна «Быстрый заказ» (спецификация, ТЗ,
    # чертёж). Хранится в PostgreSQL, поэтому лимит не бесконечный.
    REQUEST_ATTACHMENT_MAX_SIZE_MB: int = 20

    # ------------------------------------------------------ Excel-импорт
    # Размер самого XLSX ограничен общим UPLOAD_MAX_SIZE_MB. XLSX — это
    # ZIP: 15 МБ сжатого XML могут распаковаться в гигабайты («ZIP-бомба»),
    # поэтому отдельно ограничен суммарный распакованный размер.
    IMPORT_MAX_UNCOMPRESSED_MB: int = 100
    # Строк данных на одном листе. С запасом для каталога в тысячи
    # товаров по двадцать ценовых ступеней, но не бесконечно.
    IMPORT_MAX_ROWS_PER_SHEET: int = 20_000
    # Сколько живёт предпросмотр: подтверждать импорт по отчёту
    # недельной давности бессмысленно, каталог успел измениться.
    IMPORT_PREVIEW_TTL_HOURS: int = 24

    # ------------------------------------------- массовый импорт (ZIP-пакет)
    # ZIP с products.xlsx, photos/ и schemes/ загружается браузером прямо
    # в приватный префикс хранилища (presigned PUT) — мимо API и лимита
    # тела запроса на прокси. Проверку и применение выполняет воркер.
    IMPORT_BUNDLE_MAX_MB: int = 1024
    # Защита от ZIP-бомбы: суммарный распакованный размер, число файлов
    # и степень сжатия каждого файла. Фото и PDF почти не сжимаются —
    # коэффициент 100 честному архиву не мешает.
    IMPORT_BUNDLE_MAX_UNCOMPRESSED_MB: int = 3072
    IMPORT_BUNDLE_MAX_FILES: int = 5000
    IMPORT_BUNDLE_MAX_RATIO: int = 100
    # Выполнять проверку и применение прямо в запросе, без воркера.
    # Только для локальной разработки без arq; в проде — false.
    IMPORT_BUNDLE_INLINE: bool = False

    # ---------------------------------------------------------------- Security
    SECRET_KEY: str = INSECURE_PLACEHOLDER
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14
    PASSWORD_HASH_SCHEME: Literal["argon2"] = "argon2"  # noqa: S105
    PASSWORD_MIN_LENGTH: int = 12

    # Блокировка после серии неудачных входов. Защищает конкретную
    # учётную запись; rate limit по IP защищает от перебора вообще.
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Refresh-токен живёт в httpOnly cookie: JS до него не добирается,
    # поэтому XSS в админке не даёт угнать долгоживущий доступ.
    REFRESH_COOKIE_NAME: str = "oinau_refresh"
    # SameSite=strict работает, потому что admin.oinau-pro.kz и
    # api.oinau-pro.kz — один сайт (общий eTLD+1). Если API вынесут
    # на другой домен, значение придётся менять на "none" вместе
    # с обязательным Secure.
    COOKIE_SAMESITE: Literal["strict", "lax", "none"] = "strict"
    COOKIE_SECURE: bool | None = None  # None = включать автоматически в production
    COOKIE_DOMAIN: str | None = None

    # ------------------------------------------------- B2B-кабинет клиентов
    # Отдельная cookie: сессия клиента и сессия сотрудника в одном браузере
    # не должны перезаписывать друг друга.
    CUSTOMER_REFRESH_COOKIE_NAME: str = "oinau_customer_refresh"
    CUSTOMER_REFRESH_TOKEN_TTL_DAYS: int = 30
    # Ссылка подтверждения email живёт сутки, сброса пароля — час:
    # письмо со сбросом даёт полный доступ к аккаунту, его окно короче.
    CUSTOMER_EMAIL_VERIFICATION_TTL_HOURS: int = 24
    CUSTOMER_PASSWORD_RESET_TTL_MINUTES: int = 60
    # Адрес витрины для ссылок в письмах: /account/verify?token=…
    PUBLIC_SITE_URL: str = "http://localhost:3000"

    CORS_ORIGINS: CsvList = ["http://localhost:3000", "http://localhost:3001"]

    # Сколько ПОСЛЕДНИХ записей в X-Forwarded-For добавлены нашими
    # собственными прокси. 0 = заголовок игнорируется полностью.
    #
    # Клиент подделывает X-Forwarded-For тривиально, поэтому доверять
    # ему можно только зная точное число доверенных прокси перед
    # приложением: nginx -> 1, Cloudflare + nginx -> 2. При 0 берётся
    # адрес peer-соединения. Безопасный дефолт — именно 0: в худшем
    # случае весь трафик считается одним клиентом (ограничение частоты
    # становится строже), тогда как доверие заголовку по умолчанию
    # позволило бы обойти ограничение одной строкой в запросе.
    TRUSTED_PROXY_HOPS: int = 0
    # Ключи интеграции (1С) валидируются по таблице api_keys, здесь — только
    # список разрешённых IP. Пусто = проверка IP отключена (только для local).
    INTEGRATION_IP_ALLOWLIST: CsvList = []

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PUBLIC_FORM: str = "5/hour"
    RATE_LIMIT_LOGIN: str = "10/minute"
    # Выдача presigned URL: без ограничения украденный токен сотрудника
    # превращается в бесплатный генератор ссылок на запись в бакет.
    RATE_LIMIT_MEDIA_UPLOAD: str = "60/minute"
    # Разбор XLSX — самая тяжёлая по CPU операция админки.
    RATE_LIMIT_CATALOG_IMPORT: str = "30/minute"
    # Кабинет клиента: регистрация, вход и письма ограничиваются отдельно
    # от админки — у них другой профиль нагрузки и другие атакующие.
    RATE_LIMIT_CUSTOMER_REGISTER: str = "5/hour"
    RATE_LIMIT_CUSTOMER_LOGIN: str = "10/minute"
    # Письма (подтверждение, сброс пароля) — и по IP, и по адресу:
    # иначе форма превращается в инструмент рассылки на чужой ящик.
    RATE_LIMIT_CUSTOMER_EMAIL: str = "5/hour"
    RATE_LIMIT_CUSTOMER_EMAIL_PER_ADDRESS: str = "3/hour"
    RATE_LIMIT_CUSTOMER_TOKEN: str = "20/hour"  # noqa: S105 — не секрет, а норма частоты
    # Обмен с 1С идёт по расписанию, а не потоком: норма щедрая,
    # но защищает от зацикленной обработки, дёргающей эндпоинт без пауз.
    RATE_LIMIT_INTEGRATION: str = "120/minute"

    # ----------------------------------------------------------- Уведомления
    # Общий выключатель. При false ни один канал не отправляет:
    # события всё равно копятся в notification_outbox и помечаются
    # пропущенными, так что историю видно, а писем нет.
    NOTIFICATIONS_ENABLED: bool = True
    # Сколько раз воркер пробует доставить событие. Дальше — failed.
    NOTIFY_MAX_ATTEMPTS: int = 5
    # Пауза перед повтором: base * 2^(attempt-1), но не дольше суток.
    NOTIFY_RETRY_BASE_SECONDS: int = 60

    SMTP_HOST: str = "mailpit"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # STARTTLS на открытом порту (587). Для неявного TLS (465) — SMTP_SSL.
    SMTP_TLS: bool = False
    SMTP_SSL: bool = False
    SMTP_FROM: str = "noreply@oinau-pro.kz"
    SMTP_FROM_NAME: str = "OINAU PRO"
    SMTP_TIMEOUT_SECONDS: float = 15.0
    # Куда уходят деловые письма (новая заявка). Пусто = канал выключен.
    NOTIFY_EMAILS: CsvList = []

    TELEGRAM_BOT_TOKEN: str = ""
    # Один чат или несколько через запятую: заявку обычно хотят видеть
    # и в общем чате отдела, и в личке руководителя.
    TELEGRAM_CHAT_ID: CsvList = []
    # Тема («топик») форумной супергруппы: message_thread_id из Bot API.
    # Пусто = сообщение уходит в общий поток чата, как и раньше.
    #
    # Значение применяется ко ВСЕМ чатам из TELEGRAM_CHAT_ID. Telegram
    # принимает message_thread_id только у супергрупп с включёнными
    # темами: для обычной группы или лички тот же запрос вернёт 400
    # «message thread not found». Поэтому смешивать в одном списке
    # форумную супергруппу и обычный чат при заданной теме нельзя.
    TELEGRAM_MESSAGE_THREAD_ID: int | None = None
    # Адрес API вынесен в настройку ради тестов и корпоративного прокси.
    TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"
    TELEGRAM_TIMEOUT_SECONDS: float = 10.0

    # Адрес админки для ссылок в деловых уведомлениях («открыть заявку»).
    PUBLIC_ADMIN_URL: str = "http://localhost:3001/admin"

    # ------------------------------------------------------- Интеграция (1С)
    # Выключатель обмена. При false эндпоинты интеграции отвечают 503:
    # ключ может быть заведён заранее, а обмен — ещё не разрешён.
    ONE_C_INTEGRATION_ENABLED: bool = False
    # Позиций в одном пакете. Соответствует docs/architecture.md, 7.3.
    INTEGRATION_MAX_BATCH_ITEMS: int = 1000
    # Потолок размера тела запроса интеграции. Пакет в 1000 позиций
    # заведомо меньше; всё, что больше, — ошибка формирования на стороне 1С.
    INTEGRATION_MAX_BODY_BYTES: int = 5_000_000

    SENTRY_DSN: str = ""

    # ------------------------------------------------------------- валидаторы
    @field_validator(
        "CORS_ORIGINS",
        "NOTIFY_EMAILS",
        "TELEGRAM_CHAT_ID",
        "INTEGRATION_IP_ALLOWLIST",
        "UPLOAD_ALLOWED_MIME",
        "UPLOAD_ALLOWED_DOCUMENT_MIME",
        "SUPPORTED_LOCALES",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Позволяет задавать списки строкой: A,B,C — так удобнее в .env и Docker.

        Поля помечены `NoDecode`, поэтому разбор значения целиком наш:
        принимаем и JSON-массив, и список через запятую.
        """
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return v

    @field_validator("TELEGRAM_MESSAGE_THREAD_ID", mode="before")
    @classmethod
    def _optional_thread_id(cls, v: object) -> object:
        """Пустая строка — это «тема не задана», а не ошибка разбора.

        В .env необязательные значения принято оставлять пустыми
        (`TELEGRAM_MESSAGE_THREAD_ID=`). Без этого шага pydantic пытался
        бы превратить пустую строку в число и валил бы запуск
        сообщением про целое, из которого непонятно, что делать.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("TELEGRAM_MESSAGE_THREAD_ID", mode="after")
    @classmethod
    def _thread_id_is_positive(cls, v: int | None) -> int | None:
        """message_thread_id у Telegram — положительное число.

        Ноль или отрицательное обычно означают, что сюда по ошибке
        скопировали id чата (он как раз отрицательный у супергрупп).
        Ловим это при старте, а не в отчёте о неудачной доставке.
        """
        if v is not None and v <= 0:
            raise ValueError(
                "TELEGRAM_MESSAGE_THREAD_ID должен быть положительным числом "
                "(это id темы, а не id чата)"
            )
        return v

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.ENV != "production":
            return self
        insecure = [
            name
            for name in ("SECRET_KEY", "POSTGRES_PASSWORD", "S3_SECRET_ACCESS_KEY")
            if getattr(self, name) == INSECURE_PLACEHOLDER
        ]
        if insecure:
            raise ValueError(
                "В production запрещены значения по умолчанию для: " + ", ".join(insecure)
            )
        if self.DEBUG:
            raise ValueError("DEBUG=true недопустим в production")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS='*' недопустим в production")
        if not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS не может быть пустым в production")
        insecure_origins = [
            origin for origin in self.CORS_ORIGINS if not origin.startswith("https://")
        ]
        if insecure_origins:
            raise ValueError(
                "В production допустимы только https-origin: " + ", ".join(insecure_origins)
            )
        if self.COOKIE_SECURE is False:
            raise ValueError("COOKIE_SECURE=false недопустим в production")
        if self.COOKIE_SAMESITE == "none" and not self.cookie_secure:
            # SameSite=None без Secure браузеры просто отбрасывают
            raise ValueError("COOKIE_SAMESITE=none требует COOKIE_SECURE=true")
        # RFC 7518 §3.2: ключ HMAC-SHA256 короче 32 байт снижает
        # стойкость подписи. Ровно столько даёт `openssl rand -hex 32`.
        if len(self.SECRET_KEY) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY должен быть не короче {MIN_SECRET_KEY_LENGTH} символов "
                "(сгенерируйте: openssl rand -hex 32)"
            )

        # Адреса, которые уезжают наружу: ссылки в письмах клиенту,
        # ссылки «открыть заявку» в деловых уведомлениях и URL картинок
        # товаров. Локальный адрес здесь не ломает старт, но делает
        # письма и витрину нерабочими у всех, кроме самого сервера, —
        # и замечают это обычно уже клиенты.
        public_urls = {
            "PUBLIC_SITE_URL": self.PUBLIC_SITE_URL,
            "PUBLIC_ADMIN_URL": self.PUBLIC_ADMIN_URL,
            "CDN_BASE_URL": self.CDN_BASE_URL,
            # Ключи S3 уходят в подписи запросов: по http их видно в сети.
            "S3_ENDPOINT_URL": self.S3_ENDPOINT_URL,
        }
        not_https = [
            name for name, value in public_urls.items() if not value.startswith("https://")
        ]
        if not_https:
            raise ValueError(
                "В production эти адреса обязаны быть https: " + ", ".join(sorted(not_https))
            )
        local_urls = [
            name
            for name, value in public_urls.items()
            if any(host in value for host in LOCAL_HOSTNAMES)
        ]
        if local_urls:
            raise ValueError(
                "В production недопустимы локальные адреса в: " + ", ".join(sorted(local_urls))
            )

        # Mailpit — локальный перехватчик почты. В production он означает,
        # что письма не уходят вообще: ни подтверждение адреса, ни сброс
        # пароля. Молчаливая потеря писем хуже отказа при старте.
        if self.SMTP_HOST in DEV_SMTP_HOSTS:
            raise ValueError(
                f"SMTP_HOST={self.SMTP_HOST} — это локальная заглушка, "
                "в production нужен настоящий почтовый сервер"
            )
        return self

    # ---------------------------------------------------------------- свойства
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def database_url(self) -> str:
        """Async DSN для приложения."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def database_url_sync(self) -> str:
        """Sync DSN — нужен Alembic и утилитам."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def docs_url(self) -> str | None:
        """Swagger отключён в production: он раскрывает карту admin API."""
        return None if self.is_production else "/docs"

    @property
    def openapi_url(self) -> str | None:
        return None if self.is_production else "/openapi.json"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production if self.COOKIE_SECURE is None else self.COOKIE_SECURE

    @property
    def upload_max_size_bytes(self) -> int:
        return self.UPLOAD_MAX_SIZE_MB * 1024 * 1024

    @property
    def upload_max_document_size_bytes(self) -> int:
        return self.UPLOAD_MAX_DOCUMENT_SIZE_MB * 1024 * 1024

    @property
    def import_bundle_max_bytes(self) -> int:
        return self.IMPORT_BUNDLE_MAX_MB * 1024 * 1024

    @property
    def import_bundle_max_uncompressed_bytes(self) -> int:
        return self.IMPORT_BUNDLE_MAX_UNCOMPRESSED_MB * 1024 * 1024

    @property
    def request_attachment_max_size_bytes(self) -> int:
        return self.REQUEST_ATTACHMENT_MAX_SIZE_MB * 1024 * 1024

    @property
    def import_max_uncompressed_bytes(self) -> int:
        return self.IMPORT_MAX_UNCOMPRESSED_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

__all__ = ["Settings", "get_settings", "settings"]
