"""Публичные схемы географии."""

from __future__ import annotations

from pydantic import BaseModel


class RegionRead(BaseModel):
    """Регион в форме, пригодной для выпадающего списка формы заявки.

    `id` наружу выходит намеренно: публичная заявка принимает именно
    `region_id`, и без него форма не смогла бы указать регион.
    """

    id: int
    code: str
    name: str
