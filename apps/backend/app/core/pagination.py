"""Пагинация списков.

Смещение (`page` + `page_size`), а не курсор.

В архитектурном документе этапа 1 закладывалась курсорная пагинация.
Здесь сделан осознанный отход: витрина сортируется по цене, названию
и релевантности, а курсор для произвольного порядка требует составного
ключа (значение сортировки + id) и отдельной ветки на каждый вариант
сортировки. При каталоге в несколько тысяч позиций `OFFSET` на последней
странице стоит доли миллисекунды и такой сложности не оправдывает.

Порог пересмотра — десятки тысяч товаров либо появление бесконечной
прокрутки, где страницы листаются подряд и глубина смещения растёт.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

# Верхняя граница жёсткая: без неё один запрос с page_size=100000
# выгружает весь каталог и становится бесплатным способом положить сервер.
MAX_PAGE_SIZE = 60
DEFAULT_PAGE_SIZE = 24


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page[ItemT](BaseModel):
    """Страница результатов с метаданными для постраничной навигации."""

    items: list[ItemT]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def create(cls, items: Sequence[ItemT], total: int, params: PageParams) -> Page[ItemT]:
        pages = (total + params.page_size - 1) // params.page_size if total else 0
        return cls(
            items=list(items),
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )
