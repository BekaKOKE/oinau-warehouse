"""Пакетный импорт каталога (ZIP) и раздел CMS «Услуги».

Только расширения, существующие данные не меняются:

* import_jobs.kind — новое значение `catalog_bundle`;
* import_jobs.status — промежуточные шаги пакетного импорта
  (UPLOADING, CHECKING, APPLYING) и CANCELLED;
* import_jobs.storage_key — ключ архива в приватном префиксе хранилища;
* import_jobs.file_sha256 — NULL допустим: у пакета хеш известен только
  после загрузки архива. У всех существующих строк он заполнен;
* content_sections.key — новый раздел `services`.

CHECK переписывается обычным ALTER: VARCHAR + CHECK выбран в проекте
именно ради этого (см. app/db/types.py::enum_check).

Revision ID: c4d7e9a1f203
Revises: b8e41d6ca207
Create Date: 2026-09-30 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d7e9a1f203"
down_revision: str | None = "b8e41d6ca207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = "kind IN ('catalog')"
_NEW_KINDS = "kind IN ('catalog', 'catalog_bundle')"
_OLD_STATUSES = "status IN ('VALID', 'INVALID', 'COMMITTED', 'FAILED')"
_NEW_STATUSES = (
    "status IN ('UPLOADING', 'CHECKING', 'VALID', 'INVALID', 'APPLYING', "
    "'COMMITTED', 'FAILED', 'CANCELLED')"
)
_OLD_SECTIONS = "key IN ('home', 'contacts', 'delivery', 'faq', 'requisites', 'settings')"
_NEW_SECTIONS = (
    "key IN ('home', 'contacts', 'delivery', 'faq', 'requisites', 'settings', 'services')"
)


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    _replace_check("import_jobs", "ck_import_jobs_kind", _NEW_KINDS)
    _replace_check("import_jobs", "ck_import_jobs_status", _NEW_STATUSES)
    op.add_column("import_jobs", sa.Column("storage_key", sa.String(length=512), nullable=True))
    op.alter_column(
        "import_jobs", "file_sha256", existing_type=sa.String(length=64), nullable=True
    )
    _replace_check("content_sections", "ck_content_sections_key", _NEW_SECTIONS)


def downgrade() -> None:
    # Строки новых видов откатом не удаляются молча: откат упадёт на
    # CHECK, и администратор решит, что с ними делать.
    _replace_check("content_sections", "ck_content_sections_key", _OLD_SECTIONS)
    op.alter_column(
        "import_jobs", "file_sha256", existing_type=sa.String(length=64), nullable=False
    )
    op.drop_column("import_jobs", "storage_key")
    _replace_check("import_jobs", "ck_import_jobs_status", _OLD_STATUSES)
    _replace_check("import_jobs", "ck_import_jobs_kind", _OLD_KINDS)
