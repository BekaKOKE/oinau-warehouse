"""Каталог: категории, товары, переводы, характеристики.

Ключевые решения задокументированы в docs/architecture.md, разделы 6.1–6.3.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    ExternalSyncMixin,
    IntPkMixin,
    PublicUuidMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from app.db.types import (
    LEN_CODE,
    LEN_LOCALE,
    LEN_NAME,
    LEN_SHORT_NAME,
    LEN_SLUG,
    LEN_STATUS,
    LEN_UNIT,
    enum_check,
    qty_type,
)
from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.pricing.enums import PricingType

if TYPE_CHECKING:
    from app.modules.inventory.models import Stock
    from app.modules.media.models import MediaFile, ProductImage
    from app.modules.pricing.models import PriceTier


# ---------------------------------------------------------------------------
# Категории
# ---------------------------------------------------------------------------
class Category(Base, IntPkMixin, TimestampMixin, SoftDeleteMixin, ExternalSyncMixin):
    """Узел дерева категорий.

    Adjacency list (parent_id) + материализованный путь (path).

    parent_id даёт простую нормальную структуру и целостность. path вида
    "1.14.37" позволяет получить всю ветку одним LIKE-запросом без
    рекурсии — это критично для страницы категории, где выводятся товары
    из всех подкатегорий любой глубины.

    Nested Sets отвергнуты: перестройка дерева при каждой вставке и высокий
    риск ошибок ради выигрыша, заметного только на очень больших деревьях.

    ltree не используется: обычный VARCHAR с индексом varchar_pattern_ops
    решает ту же задачу и не добавляет расширение PostgreSQL.
    """

    __tablename__ = "categories"

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), default=None
    )
    slug: Mapped[str] = mapped_column(String(LEN_SLUG), nullable=False)
    path: Mapped[str] = mapped_column(String(255), server_default="", nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    # Обложка раздела из общей медиатеки. Колонка, а не таблица связи:
    # картинка у категории одна, порядок и alt на несколько штук здесь
    # не нужны. RESTRICT — файл, который показывается, удалить нельзя.
    image_media_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT"), default=None
    )

    parent: Mapped[Category | None] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    image_media: Mapped[MediaFile | None] = relationship(lazy="raise")
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    translations: Mapped[list[CategoryTranslation]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        Index(
            "uq_categories_slug", "slug", unique=True, postgresql_where=text("deleted_at IS NULL")
        ),
        Index(
            "ix_categories_image_media_id",
            "image_media_id",
            postgresql_where=text("image_media_id IS NOT NULL"),
        ),
        Index(
            "uq_categories_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_categories_parent_id", "parent_id"),
        # varchar_pattern_ops — для запросов вида path LIKE '1.14.%'
        Index("ix_categories_path", "path", postgresql_ops={"path": "varchar_pattern_ops"}),
        Index(
            "ix_categories_active",
            "is_active",
            "sort_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class CategoryTranslation(Base, IntPkMixin, TimestampMixin):
    """Локализованные тексты категории.

    Отдельная таблица, а не JSONB: name и description участвуют в SEO
    и в поиске, а по JSONB нельзя построить нормальный полнотекстовый
    индекс на конкретный язык.
    """

    __tablename__ = "category_translations"

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(LEN_LOCALE), nullable=False)

    name: Mapped[str] = mapped_column(String(LEN_NAME), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    seo_title: Mapped[str | None] = mapped_column(String(LEN_NAME), default=None)
    seo_description: Mapped[str | None] = mapped_column(Text, default=None)

    category: Mapped[Category] = relationship(back_populates="translations")

    __table_args__ = (
        Index("uq_category_translations_category_id_locale", "category_id", "locale", unique=True),
    )


# ---------------------------------------------------------------------------
# Товары
# ---------------------------------------------------------------------------
class Product(
    Base, IntPkMixin, PublicUuidMixin, TimestampMixin, SoftDeleteMixin, ExternalSyncMixin
):
    """Товарная позиция.

    Ни цены, ни остатка здесь нет — они живут в price_tiers и stocks.
    Поле цены в products сделало бы невозможными ступенчатые цены,
    а поле наличия рассинхронизировалось бы с реальностью в первый же
    день работы 1С.
    """

    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    slug: Mapped[str] = mapped_column(String(LEN_SLUG), nullable=False)

    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=ProductStatus.DRAFT.value, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    # Единица измерения без CHECK: 1С может прислать произвольный код.
    unit: Mapped[str] = mapped_column(String(LEN_UNIT), server_default="pcs", nullable=False)
    min_order_qty: Mapped[Decimal] = mapped_column(qty_type(), server_default="1", nullable=False)

    pricing_type: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=PricingType.FIXED.value, nullable=False
    )
    # Ручное переопределение публичного статуса наличия. Понадобится
    # гарантированно: товар под заказ, снят с продажи, ожидается поставка.
    stock_display_override: Mapped[str | None] = mapped_column(String(LEN_STATUS), default=None)

    brand: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    weight_kg: Mapped[Decimal | None] = mapped_column(qty_type(), default=None)

    # Описательные характеристики, не участвующие в фильтрах.
    # Новая строка в таблице характеристик карточки не требует миграции.
    specs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    translations: Mapped[list[ProductTranslation]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    categories: Mapped[list[ProductCategory]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    attribute_values: Mapped[list[ProductAttributeValue]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    price_tiers: Mapped[list[PriceTier]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    stocks: Mapped[list[Stock]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("status", ProductStatus, "status"),
        enum_check("pricing_type", PricingType, "pricing_type"),
        CheckConstraint(
            "stock_display_override IS NULL OR stock_display_override IN "
            "('IN_STOCK', 'OUT_OF_STOCK', 'ON_REQUEST')",
            name="stock_display_override",
        ),
        CheckConstraint("min_order_qty > 0", name="min_order_qty_positive"),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="weight_non_negative"),
        # Артикул — бизнес-ключ для сопоставления с 1С и Excel-импортом.
        # Частичный индекс: удалённый товар не блокирует повторное
        # заведение того же артикула.
        Index("uq_products_sku", "sku", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_products_slug", "slug", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index(
            "uq_products_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        # Основной запрос витрины: активные опубликованные товары.
        Index(
            "ix_products_published",
            "status",
            "is_active",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Поиск по части артикула ("канат 16" -> KAN-16-PP)
        Index(
            "ix_products_sku_trgm",
            "sku",
            postgresql_using="gin",
            postgresql_ops={"sku": "gin_trgm_ops"},
        ),
    )


class ProductTranslation(Base, IntPkMixin, TimestampMixin):
    """Локализованные тексты товара и полнотекстовый индекс.

    search_vector — генерируемая колонка, а не триггер: PostgreSQL сам
    поддерживает её в актуальном состоянии, рассинхронизация невозможна
    в принципе, включая массовые UPDATE из импорта.

    Индекс строится по каждому языку отдельно, поэтому добавление
    казахской версии не ухудшит русский поиск.
    """

    __tablename__ = "product_translations"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(LEN_LOCALE), nullable=False)

    name: Mapped[str] = mapped_column(String(LEN_NAME), nullable=False)
    short_description: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    seo_title: Mapped[str | None] = mapped_column(String(LEN_NAME), default=None)
    seo_description: Mapped[str | None] = mapped_column(Text, default=None)

    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('russian', coalesce(name, '') || ' ' || coalesce(short_description, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    product: Mapped[Product] = relationship(back_populates="translations")

    __table_args__ = (
        Index("uq_product_translations_product_id_locale", "product_id", "locale", unique=True),
        Index("ix_product_translations_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_product_translations_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class ProductCategory(Base):
    """Связь товара с категориями (many-to-many).

    Один товар почти всегда относится к нескольким разделам: крепление
    попадает и в "Крепления", и в "Элементы качелей". Жёсткое поле
    category_id в products потребовало бы миграции в первый же месяц.

    is_primary задаёт канонический URL и хлебные крошки — без него
    один товар давал бы несколько URL с одинаковым содержимым, что
    штрафуется поисковыми системами.
    """

    __tablename__ = "product_categories"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    product: Mapped[Product] = relationship(back_populates="categories")
    category: Mapped[Category] = relationship()

    __table_args__ = (
        PrimaryKeyConstraint("product_id", "category_id", name="pk_product_categories"),
        Index("ix_product_categories_category_id", "category_id"),
        Index(
            "uq_product_categories_primary",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )


# ---------------------------------------------------------------------------
# Характеристики
# ---------------------------------------------------------------------------
class Attribute(Base, IntPkMixin, TimestampMixin):
    """Справочник характеристик, участвующих в фильтрах.

    Названия хранятся в JSONB name_i18n = {"ru": "Диаметр", "kk": "..."},
    а не в отдельной таблице переводов. Асимметрия с товарами осознанная:
    характеристик десятки, их названия никогда не участвуют в
    полнотекстовом поиске и в SEO, и они всегда загружаются целиком для
    отрисовки блока фильтров. Отдельная таблица дала бы лишний JOIN
    в самом горячем запросе витрины ради нулевого выигрыша.
    """

    __tablename__ = "attributes"

    code: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name_i18n: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    unit: Mapped[str | None] = mapped_column(String(LEN_UNIT), default=None)
    value_type: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)

    is_filterable: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    options: Mapped[list[AttributeOption]] = relationship(
        back_populates="attribute", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("value_type", AttributeValueType, "value_type"),
        Index("uq_attributes_code", "code", unique=True),
    )


class AttributeOption(Base, IntPkMixin, TimestampMixin):
    """Вариант значения для характеристики типа OPTION."""

    __tablename__ = "attribute_options"

    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(LEN_SLUG), nullable=False)
    value_i18n: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    attribute: Mapped[Attribute] = relationship(back_populates="options")

    __table_args__ = (
        Index("uq_attribute_options_attribute_id_slug", "attribute_id", "slug", unique=True),
    )


class CategoryAttribute(Base):
    """Какие характеристики показывать в фильтрах конкретной категории.

    Без этой таблицы фильтр в разделе "Канаты" показывал бы все
    характеристики каталога, включая цвет сиденья качелей.
    """

    __tablename__ = "category_attributes"

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("category_id", "attribute_id", name="pk_category_attributes"),
        Index("ix_category_attributes_attribute_id", "attribute_id"),
    )


class ProductAttributeValue(Base, IntPkMixin):
    """Значение характеристики товара.

    Типизированные колонки вместо одной value VARCHAR: фильтр
    "диаметр от 10 до 20 мм" на строках работать не будет, а приведение
    типа в запросе убивает индекс.

    Одна из колонок значения должна быть заполнена ровно одна — это
    гарантируется CHECK на уровне БД, а не надеждой на код приложения.
    """

    __tablename__ = "product_attribute_values"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attributes.id", ondelete="RESTRICT"), nullable=False
    )

    value_string: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    value_numeric: Mapped[Decimal | None] = mapped_column(qty_type(), default=None)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, default=None)
    option_id: Mapped[int | None] = mapped_column(
        ForeignKey("attribute_options.id", ondelete="RESTRICT"), default=None
    )

    # COALESCE(option_id, 0) в уникальном индексе допускает несколько
    # значений одной характеристики, если это варианты справочника
    # (например, товар доступен в трёх цветах), но запрещает дубль
    # скалярного значения.
    option_key: Mapped[int] = mapped_column(
        BigInteger, Computed("coalesce(option_id, 0)", persisted=True), nullable=True
    )

    product: Mapped[Product] = relationship(back_populates="attribute_values")
    attribute: Mapped[Attribute] = relationship()
    option: Mapped[AttributeOption | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(value_string, value_numeric, value_bool, option_id) = 1",
            name="exactly_one_value",
        ),
        Index(
            "uq_product_attribute_values_key",
            "product_id",
            "attribute_id",
            "option_key",
            unique=True,
        ),
        # Фасетные фильтры: "все товары, у которых материал = полипропилен"
        Index("ix_product_attribute_values_option", "attribute_id", "option_id"),
        Index("ix_product_attribute_values_numeric", "attribute_id", "value_numeric"),
    )
