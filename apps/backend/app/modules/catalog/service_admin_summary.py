"""Сводка каталога для главного экрана админки."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.service import BaseService
from app.modules.catalog.repository_admin_summary import CatalogSummaryRepository
from app.modules.catalog.schemas_admin_summary import (
    AvailabilityCounts,
    CatalogSummaryRead,
    CategoryCounts,
    ProductContentCounts,
    ProductCounts,
)


def _section[ModelT: BaseModel](model: type[ModelT], counts: dict[str, int], prefix: str) -> ModelT:
    """Колонки запроса названы `<раздел>_<поле>` — раскладываем по схемам."""
    return model(**{name: counts[f"{prefix}_{name}"] for name in model.model_fields})


class AdminCatalogSummaryService(BaseService):
    async def get_summary(self) -> CatalogSummaryRead:
        counts = await CatalogSummaryRepository(self.session).summary_counts()
        return CatalogSummaryRead(
            products=_section(ProductCounts, counts, "products"),
            content=_section(ProductContentCounts, counts, "content"),
            availability=_section(AvailabilityCounts, counts, "availability"),
            categories=_section(CategoryCounts, counts, "categories"),
        )
