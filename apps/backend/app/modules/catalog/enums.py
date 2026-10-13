"""Перечисления каталога."""

from __future__ import annotations

from enum import StrEnum


class ProductStatus(StrEnum):
    """Жизненный цикл карточки товара.

    Отдельный статус, а не булев is_published: нужны как минимум черновик,
    публикация и архив, и список будет расти (например, DISCONTINUED —
    снят с производства, но остаётся в истории заявок).
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class AttributeValueType(StrEnum):
    """Тип значения характеристики.

    OPTION — значение из справочника attribute_options. Только такие
    характеристики дают корректные фасетные фильтры со счётчиками.
    """

    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    OPTION = "OPTION"


class ProductUnit(StrEnum):
    """Типовые единицы измерения.

    В БД колонка unit намеренно БЕЗ CHECK-ограничения: 1С может прислать
    единицу, которой нет в этом списке, и импорт не должен падать из-за
    незнакомого справочника. Перечисление используется приложением для
    подсказок в админке и подписей в интерфейсе.
    """

    PIECE = "pcs"
    METER = "m"
    SQUARE_METER = "m2"
    KILOGRAM = "kg"
    SET = "set"
    PACK = "pack"
    LITER = "l"


class ProductSort(StrEnum):
    """Разрешённые варианты сортировки списка товаров.

    Белый список: значение приходит из query-параметра и превращается
    в ORDER BY. Без перечисления это была бы прямая дорога к передаче
    произвольного SQL в сортировку.
    """

    RELEVANCE = "relevance"
    NEWEST = "newest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NAME = "name"
    # Для таблицы товаров раздела: B2B-покупатель часто ищет по артикулу.
    SKU = "sku"
