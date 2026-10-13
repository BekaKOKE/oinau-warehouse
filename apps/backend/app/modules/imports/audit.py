"""События аудита импорта и экспорта каталога.

Итог импорта пишется одной записью на задачу (`import_job`), а
изменения отдельных товаров, категорий и цен — теми же действиями, что
и в Admin API (`catalog.product_updated`, `pricing.updated`, ...),
с actor="import" и ссылкой на задачу в `changes.import_job`. Так история
товара читается одинаково, каким бы каналом его ни меняли.

Содержимое файла в журнал не пишется — только метаданные и счётчики.
"""

from __future__ import annotations

IMPORT_JOB_ENTITY = "import_job"
# Значение audit_log.actor для изменений, пришедших из файла.
IMPORT_ACTOR = "import"
# Значение sync_source у строк, которые последним записал Excel-импорт.
SYNC_SOURCE = "excel"


class ImportAuditAction:
    PREVIEWED = "catalog_import.previewed"
    COMMITTED = "catalog_import.committed"
    COMMIT_FAILED = "catalog_import.commit_failed"
    # Пакетный импорт (ZIP): шаги, которых нет у обычного.
    BUNDLE_UPLOAD_REQUESTED = "catalog_import.bundle_upload_requested"
    BUNDLE_CHECK_STARTED = "catalog_import.bundle_check_started"
    BUNDLE_APPLY_STARTED = "catalog_import.bundle_apply_started"
    BUNDLE_CANCELLED = "catalog_import.bundle_cancelled"
