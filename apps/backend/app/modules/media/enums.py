"""Перечисления медиатеки."""

from __future__ import annotations

from enum import StrEnum


class MediaStatus(StrEnum):
    """Состояние файла в объектном хранилище.

    PENDING    — presigned URL выдан, файл ещё не загружен.
    PROCESSING — загрузка подтверждена и проверена, воркер строит варианты.
    READY      — варианты готовы, файл можно показывать на витрине.
    FAILED     — файл отвергнут; объект в хранилище удалён.

    Записи, застрявшие в PENDING дольше суток, вычищаются
    периодической задачей — иначе бакет зарастает брошенными загрузками.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class ImageKind(StrEnum):
    """Роль изображения в карточке товара.

    Схемы и чертежи выводятся отдельным блоком галереи, а не вперемешку
    с фотографиями.
    """

    PHOTO = "PHOTO"
    SCHEME = "SCHEME"
    DRAWING = "DRAWING"
    CERTIFICATE = "CERTIFICATE"


class MediaPurpose(StrEnum):
    """Назначение файла — определяет только префикс ключа в бакете.

    Префиксы совпадают с политикой доступа бакета
    (infra/docker/minio/init.sh): публично читаются лишь
    `products/*/variants/*` и `content/*/variants/*`, оригиналы — нет.
    В БД назначение отдельно не хранится: оно видно по ключу, а один
    и тот же файл при этом может использоваться где угодно.
    """

    PRODUCT = "PRODUCT"
    CONTENT = "CONTENT"


class MediaFailureReason(StrEnum):
    """Почему файл отвергнут. Код, а не текст: админка показывает своё сообщение."""

    OBJECT_MISSING = "object_missing"
    SIZE_EXCEEDED = "size_exceeded"
    EMPTY_FILE = "empty_file"
    TYPE_MISMATCH = "type_mismatch"
    DECODE_FAILED = "decode_failed"
    TOO_MANY_PIXELS = "too_many_pixels"
    PROCESSING_ERROR = "processing_error"
