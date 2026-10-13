"""Запросы Admin API заявок.

Число запросов к БД фиксировано и не зависит ни от размера страницы,
ни от числа позиций, комментариев и записей истории в карточке.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import selectinload, undefer

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.customers.models import Customer
from app.modules.geo.models import Region
from app.modules.requests.models import (
    Request,
    RequestAttachment,
    RequestComment,
    RequestItem,
    RequestStatusHistory,
)
from app.modules.users.models import User

# Как и в каталоге: длинный шаблон превращает ILIKE в дорогое сканирование.
MAX_SEARCH_LENGTH = 100

# Телефон хранится нормализованным (+77011234567), поэтому запрос
# «701 123-45» ищется ещё и по одним цифрам. Короче трёх цифр —
# совпадения со всеми подряд.
MIN_PHONE_SEARCH_DIGITS = 3


class RequestAdminSort(StrEnum):
    """Белый список сортировок: значение приходит из query-параметра."""

    NEWEST = "newest"
    OLDEST = "oldest"
    UPDATED = "updated"


@dataclass(frozen=True)
class RequestAdminFilters:
    status: str | None = None
    source: str | None = None
    region_id: int | None = None
    # Полуинтервал [created_from, created_to): соседние периоды
    # не пересекаются и не требуют «23:59:59.999».
    created_from: datetime | None = None
    created_to: datetime | None = None
    search: str | None = None


@dataclass(frozen=True)
class RequestListRow:
    request: Request
    region: Region | None
    items_count: int


class AdminRequestRepository(BaseRepository[Request]):
    model = Request

    # ---------------------------------------------------------------- список
    def _search_clause(self, raw: str) -> ColumnElement[bool]:
        term = raw.strip()[:MAX_SEARCH_LENGTH]
        pattern = f"%{term}%"
        conditions: list[ColumnElement[bool]] = [
            Request.number.ilike(pattern),
            Request.customer_name.ilike(pattern),
            Request.phone.ilike(pattern),
            Request.email.ilike(pattern),
            Request.company.ilike(pattern),
        ]
        digits = re.sub(r"\D", "", term)
        if len(digits) >= MIN_PHONE_SEARCH_DIGITS and digits != term:
            conditions.append(Request.phone.like(f"%{digits}%"))
        return or_(*conditions)

    async def list_requests(
        self, *, filters: RequestAdminFilters, sort: RequestAdminSort, params: PageParams
    ) -> tuple[list[RequestListRow], int]:
        # Коррелированный подзапрос считается только для строк страницы
        # и идёт по индексу ix_request_items_request_id. Агрегат по всей
        # таблице позиций с последующим JOIN считал бы лишнее.
        items_count = (
            select(func.count(RequestItem.id))
            .where(RequestItem.request_id == Request.id)
            .correlate(Request)
            .scalar_subquery()
        )

        query = (
            select(Request, Region, items_count.label("items_count"))
            .outerjoin(Region, Region.id == Request.region_id)
            .where(Request.deleted_at.is_(None))
        )

        if filters.status is not None:
            query = query.where(Request.status == filters.status)
        if filters.source is not None:
            query = query.where(Request.source == filters.source)
        if filters.region_id is not None:
            query = query.where(Request.region_id == filters.region_id)
        if filters.created_from is not None:
            query = query.where(Request.created_at >= filters.created_from)
        if filters.created_to is not None:
            query = query.where(Request.created_at < filters.created_to)
        if filters.search and filters.search.strip():
            query = query.where(self._search_clause(filters.search))

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Request.id).subquery())
            )
        ).scalar_one()

        # Request.id последним — устойчивый тай-брейкер: без него
        # соседние страницы могут повторить или потерять заявку.
        order_options: dict[RequestAdminSort, list[Any]] = {
            RequestAdminSort.NEWEST: [Request.created_at.desc(), Request.id.desc()],
            RequestAdminSort.OLDEST: [Request.created_at.asc(), Request.id.asc()],
            RequestAdminSort.UPDATED: [Request.updated_at.desc(), Request.id.desc()],
        }
        rows = (
            await self.session.execute(
                query.order_by(*order_options[sort]).limit(params.limit).offset(params.offset)
            )
        ).all()
        return [
            RequestListRow(request=row[0], region=row[1], items_count=int(row.items_count))
            for row in rows
        ], total

    # -------------------------------------------------------------- карточка
    async def get_detail(self, request_id: int) -> tuple[Request, Region | None] | None:
        """Заявка со всеми вложенными коллекциями.

        Позиции, комментарии и история — по одному selectinload-запросу
        на коллекцию, сколько бы строк в них ни было.

        populate_existing: сервис меняет заявку, коммитит и читает её
        снова в той же сессии — нужны свежие коллекции, а не копия из
        identity map.
        """
        query = (
            select(Request, Region)
            .outerjoin(Region, Region.id == Request.region_id)
            .where(Request.id == request_id, Request.deleted_at.is_(None))
            .options(
                selectinload(Request.items),
                selectinload(Request.comments),
                selectinload(Request.status_history),
                # Без содержимого: `data` отложен в модели.
                selectinload(Request.attachments),
            )
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(query)).first()
        if row is None:
            return None
        return row[0], row[1]

    async def get_for_update(self, request_id: int) -> Request | None:
        """Блокирует строку заявки до конца транзакции.

        Две одновременные смены статуса иначе записали бы в историю
        один и тот же «прежний» статус, и цепочка переходов разошлась
        бы с тем, что происходило на самом деле.
        """
        query = (
            select(Request)
            .where(Request.id == request_id, Request.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(query)).scalars().first()

    async def get_customer_link(self, request_id: int) -> tuple[int | None, str] | None:
        """(customer_id, номер) живой заявки — для уведомления клиента."""
        query = select(Request.customer_id, Request.number).where(
            Request.id == request_id, Request.deleted_at.is_(None)
        )
        row = (await self.session.execute(query)).first()
        return (row[0], row[1]) if row is not None else None

    async def get_verified_customer(self, customer_id: int) -> tuple[str, str] | None:
        """(email, имя) клиента с ПОДТВЕРЖДЁННЫМ адресом.

        Письмо на неподтверждённый адрес отправлять нельзя: он не
        доказан, и рассылка по нему превращает нас в инструмент
        досаждения тому, кого вписали в форму.
        """
        query = select(Customer.email, Customer.contact_name).where(
            Customer.id == customer_id,
            Customer.deleted_at.is_(None),
            Customer.is_active.is_(True),
            Customer.email_verified_at.is_not(None),
        )
        row = (await self.session.execute(query)).first()
        return (row[0], row[1]) if row is not None else None

    async def get_attachment(self, request_id: int, attachment_id: int) -> RequestAttachment | None:
        """Файл живой заявки вместе с содержимым.

        Принадлежность заявке проверяется в том же запросе: номер файла
        от другой заявки неотличим от несуществующего.
        """
        query = (
            select(RequestAttachment)
            .join(Request, Request.id == RequestAttachment.request_id)
            .where(
                RequestAttachment.id == attachment_id,
                RequestAttachment.request_id == request_id,
                Request.deleted_at.is_(None),
            )
            .options(undefer(RequestAttachment.data))
        )
        return (await self.session.execute(query)).scalars().first()

    async def exists(self, request_id: int) -> bool:
        query = select(Request.id).where(Request.id == request_id, Request.deleted_at.is_(None))
        return (await self.session.execute(query)).scalar_one_or_none() is not None

    async def list_comments(self, request_id: int) -> Sequence[RequestComment]:
        query = (
            select(RequestComment)
            .where(RequestComment.request_id == request_id)
            .order_by(RequestComment.created_at, RequestComment.id)
        )
        return (await self.session.execute(query)).scalars().all()

    async def list_history(self, request_id: int) -> Sequence[RequestStatusHistory]:
        query = (
            select(RequestStatusHistory)
            .where(RequestStatusHistory.request_id == request_id)
            .order_by(RequestStatusHistory.created_at, RequestStatusHistory.id)
        )
        return (await self.session.execute(query)).scalars().all()

    async def get_users(self, user_ids: Sequence[int]) -> dict[int, User]:
        """Авторы комментариев и переходов — одним запросом на всю карточку.

        Удалённые (мягко) сотрудники тоже возвращаются: они остаются
        авторами своих записей.
        """
        if not user_ids:
            return {}
        query = select(User).where(User.id.in_(set(user_ids)))
        return {user.id: user for user in (await self.session.execute(query)).scalars().all()}
