"""Перечисления заявок."""

from __future__ import annotations

from enum import StrEnum


class RequestKind(StrEnum):
    """Тип заявки.

    CART    — пользователь собрал товары и отправил заявку.
    GENERAL — форма "Не нашли нужный товар?": состава нет, есть описание.

    Одна таблица вместо orders и leads: у них совпадают контактные данные,
    статусная модель, воронка, комментарии, уведомления и права доступа.
    Отличается только наличие позиций. Две таблицы означали бы два набора
    статусов, два отчёта и вечный вопрос "где искать эту заявку".
    В админке это по-прежнему два раздела — с разным фильтром по kind.
    """

    CART = "CART"
    GENERAL = "GENERAL"


class RequestStatus(StrEnum):
    """Статус обработки заявки.

    VARCHAR + CHECK, а не PostgreSQL ENUM: добавление значения в нативный
    ENUM — миграция с блокировкой типа, а CHECK переписывается обычным
    ALTER. Список заведомо будет расти.

    SPAM вместо удаления: заявка остаётся в базе для анализа источников
    спама и не искажает статистику воронки.
    """

    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_CLIENT = "WAITING_CLIENT"
    QUOTE_SENT = "QUOTE_SENT"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SPAM = "SPAM"


class RequestSource(StrEnum):
    """Откуда пришла заявка. Нужен для оценки эффективности форм.

    Колонка `source` без CHECK-ограничения: новый источник не требует
    миграции. Последние четыре — окно «Быстрый заказ» (QuickRequestMode).
    """

    CATALOG_CART = "CATALOG_CART"
    PRODUCT_PAGE = "PRODUCT_PAGE"
    NOT_FOUND_FORM = "NOT_FOUND_FORM"
    CONTACT_FORM = "CONTACT_FORM"
    ADMIN = "ADMIN"
    QUICK_CALLBACK = "QUICK_CALLBACK"
    ONE_CLICK = "ONE_CLICK"
    SKU_LIST = "SKU_LIST"
    QUOTE_REQUEST = "QUOTE_REQUEST"


class QuickRequestMode(StrEnum):
    """Вкладка окна «Быстрый заказ».

    CALLBACK — только контакты: менеджер перезванивает и подбирает сам.
               С артикулом товара это «заказ в 1 клик».
    SKU_LIST — вставленный список «артикул × количество»; сервер
               распознаёт позиции сам, нераспознанное видит менеджер.
    QUOTE    — запрос коммерческого предложения: спецификация файлом
               и/или описанием.
    """

    CALLBACK = "CALLBACK"
    SKU_LIST = "SKU_LIST"
    QUOTE = "QUOTE"
