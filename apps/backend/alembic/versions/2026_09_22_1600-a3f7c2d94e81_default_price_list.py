"""Прайс-лист по умолчанию.

Вся работа с ценами жёстко привязана к прайсу `default`: админка
не показывает выбор прайс-листа, а `AdminPricingService` на его
отсутствие отвечает `DefaultPriceListMissingError` — 500. До сих пор
эту строку создавал только `app.scripts.seed`, то есть демо-набор,
запуск которого в production запрещён. На чистой базе вкладка «Цены»
у любого товара отдавала 500, и завести прайс было нечем: API для
управления прайс-листами нет по замыслу.

Строка вставляется здесь, а не кодом при старте: это часть схемы
данных, без которой приложение не работает, и её появление должно
быть видно в истории миграций.

Валюта — KZT, как `server_default` колонки и `settings.DEFAULT_CURRENCY`.
Настройки из окружения миграция не читает намеренно: значение колонки
не должно зависеть от того, с каким env её прогнали.

Revision ID: a3f7c2d94e81
Revises: 5c1f0a9e7b21
Create Date: 2026-09-22 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c2d94e81"
down_revision: str | None = "5c1f0a9e7b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE_LIST_CODE = "default"


def upgrade() -> None:
    # Идемпотентно: на базе, поднятой через seed, прайс уже есть, и
    # второй такой строки быть не должно.
    op.execute(
        sa.text(
            """
            INSERT INTO price_lists (code, name, currency, is_default, is_active)
            SELECT :code, 'Основной прайс', 'KZT', true, true
            WHERE NOT EXISTS (SELECT 1 FROM price_lists WHERE code = :code)
            """
        ).bindparams(code=PRICE_LIST_CODE)
    )
    # Прайс есть, но признак снят — цены всё равно не читаются.
    op.execute(
        sa.text(
            """
            UPDATE price_lists
               SET is_default = true, is_active = true
             WHERE code = :code
               AND NOT (is_default AND is_active)
               AND NOT EXISTS (
                   SELECT 1 FROM price_lists
                    WHERE is_default AND is_active AND code <> :code
               )
            """
        ).bindparams(code=PRICE_LIST_CODE)
    )


def downgrade() -> None:
    # Удаляем только нетронутый прайс: если по нему уже проставлены
    # цены, откат миграции не должен их уносить вместе с ним.
    op.execute(
        sa.text(
            """
            DELETE FROM price_lists
             WHERE code = :code
               AND NOT EXISTS (
                   SELECT 1 FROM price_tiers
                    WHERE price_tiers.price_list_id = price_lists.id
               )
            """
        ).bindparams(code=PRICE_LIST_CODE)
    )
