"""Публичные ссылки на файлы медиатеки — одно правило для всего проекта.

Им пользуются витрина каталога, публичный CMS и админка. Правило:
  * ссылка существует только у файла в статусе READY;
  * наружу уходят ссылки на варианты, а не на оригинал: оригинал лежит
    в приватном префиксе бакета и может содержать EXIF;
  * URL собирается существующим `build_public_url` — ключ объекта
    отдельным полем наружу не выходит.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.storage.client import build_public_url
from app.modules.media.enums import MediaStatus
from app.modules.media.models import MediaFile

# Вариант, который отдаётся как основной `url`.
PRIMARY_VARIANT = "large"


def is_ready(media: MediaFile | None) -> bool:
    return media is not None and media.status == MediaStatus.READY.value


def _variants(media: MediaFile) -> dict[str, dict[str, Any]]:
    return {
        str(name): data
        for name, data in (media.variants or {}).items()
        if isinstance(data, dict) and data.get("key")
    }


def variant_urls(media: MediaFile | None) -> dict[str, str]:
    if media is None or not is_ready(media):
        return {}
    return {name: build_public_url(str(data["key"])) for name, data in _variants(media).items()}


def _primary_variant(media: MediaFile | None) -> dict[str, Any] | None:
    if media is None or not is_ready(media):
        return None
    variants = _variants(media)
    return variants.get(PRIMARY_VARIANT) or next(iter(variants.values()), None)


def primary_url(media: MediaFile | None) -> str | None:
    """Основная ссылка на изображение или None, если показывать нечего.

    Строится ТОЛЬКО из ключа варианта. READY-файл без вариантов ссылки
    не получает: оригинал всегда приватен, и `storage_key` в публичный
    URL не превращается ни при каких условиях.
    """
    chosen = _primary_variant(media)
    return build_public_url(str(chosen["key"])) if chosen else None


def primary_size(media: MediaFile | None) -> tuple[int | None, int | None]:
    """Размер того файла, на который ведёт `primary_url` — нужен вёрстке."""
    chosen = _primary_variant(media)
    if chosen is None:
        return None, None
    return _as_int(chosen.get("w")), _as_int(chosen.get("h"))


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None
