"""События аудита обмена с учётной системой.

Изменения объектов пишутся ТЕМИ ЖЕ действиями, что и в Admin API, но
с actor="1c". Так история товара читается одинаково, каким бы каналом
его ни меняли: руками, Excel-импортом или обменом. Отдельный набор
действий заставил бы читать журнал дважды.

Технические подробности самого обмена (объём пакета, длительность,
счётчики) живут в sync_log, а не здесь: иначе история товара утонула
бы в записях о каждой выгрузке остатков.
"""

from __future__ import annotations

# Значение audit_log.actor для изменений, пришедших из учётной системы.
INTEGRATION_ACTOR = "1c"
# Значение sync_source у строк, которые последним записал обмен.
SYNC_SOURCE_1C = "1c"


class IntegrationAuditAction:
    # Те же коды, что у Admin API: см. app/modules/catalog/audit.py и др.
    PRODUCT_UPDATED = "catalog.product_updated"
    PRICING_UPDATED = "pricing.updated"
    STOCK_UPDATED = "inventory.stock_updated"
    # Собственные события обмена.
    REQUEST_EXPORTED = "integration.request_exported"
