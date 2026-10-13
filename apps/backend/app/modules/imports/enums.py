"""Перечисления импорта."""

from __future__ import annotations

from enum import StrEnum


class ImportJobKind(StrEnum):
    """Что импортируется.

    Пока только каталог. Колонка заведена сразу: следующий импорт
    (например, контрагенты) не потребует миграции истории.
    """

    CATALOG = "catalog"
    # Пакет: ZIP с products.xlsx, фотографиями и схемами товаров.
    CATALOG_BUNDLE = "catalog_bundle"


class ImportJobStatus(StrEnum):
    """Жизненный цикл импорта: предпросмотр -> подтверждение.

    VALID     — предпросмотр без ошибок, можно подтверждать;
    INVALID   — в файле есть ошибки, подтверждение невозможно;
    COMMITTED — изменения применены (конечный статус);
    FAILED    — подтверждение отклонено повторной проверкой или базой
                (конечный статус: нужен новый предпросмотр).

    Только у пакетного импорта (ZIP) — он загружается в хранилище
    и обрабатывается воркером, поэтому у него есть промежуточные шаги:

    UPLOADING — выдана ссылка на загрузку архива, архив ещё не проверен;
    CHECKING  — воркер проверяет архив (предпросмотр);
    APPLYING  — воркер применяет проверенный архив;
    CANCELLED — пользователь отменил импорт (конечный статус).
    """

    UPLOADING = "UPLOADING"
    CHECKING = "CHECKING"
    VALID = "VALID"
    INVALID = "INVALID"
    APPLYING = "APPLYING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
