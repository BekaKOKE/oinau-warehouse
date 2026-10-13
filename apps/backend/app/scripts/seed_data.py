"""Демонстрационный набор данных: что именно создаёт `seed`.

Вынесено из самого скрипта, чтобы код загрузки не тонул в литералах.
Данные выдуманы и помечены как демонстрационные: ни одна позиция,
цена или реквизит не взяты из реальной работы компании.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.catalog.enums import AttributeValueType, ProductUnit
from app.modules.inventory.enums import StockDisplayOverride
from app.modules.pricing.enums import PricingType

# Цвет плашки-заглушки изображения. Товарных фотографий в демо-наборе
# нет — генерируется брендированный прямоугольник с артикулом.
PLACEHOLDER_BG = (14, 22, 32)
PLACEHOLDER_FG = (127, 180, 255)


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    name: str
    description: str | None = None
    parent: str | None = None


@dataclass(frozen=True)
class AttributeSeed:
    code: str
    name: str
    value_type: AttributeValueType
    unit: str | None = None
    sort_order: int = 0
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TierSeed:
    min_qty: Decimal
    price: Decimal
    max_qty: Decimal | None = None


@dataclass(frozen=True)
class ProductSeed:
    sku: str
    slug: str
    name: str
    category: str
    unit: str
    pricing_type: PricingType
    tiers: tuple[TierSeed, ...] = ()
    short_description: str | None = None
    description: str | None = None
    brand: str | None = None
    min_order_qty: Decimal = Decimal("1")
    is_featured: bool = False
    stock: Decimal | None = None
    stock_display_override: StockDisplayOverride | None = None
    attributes: dict[str, str | Decimal | bool] = field(default_factory=dict)
    specs: dict[str, str] = field(default_factory=dict)


ROOT_SLUG = "komplektuyushchie"

CATEGORIES: tuple[CategorySeed, ...] = (
    CategorySeed(
        slug=ROOT_SLUG,
        name="Комплектующие",
        description="Канаты, крепёж, сиденья, втулки и готовые узлы для детских "
        "и спортивных площадок.",
    ),
    CategorySeed(
        slug="kanaty-i-seti",
        name="Канаты и сети",
        parent=ROOT_SLUG,
        description="Армированные канаты, сетки и узлы для лазательных элементов.",
    ),
    CategorySeed(
        slug="krepleniya-i-podvesy",
        name="Крепления и подвесы",
        parent=ROOT_SLUG,
        description="Подвесы качелей, цепи, кронштейны и анкерное крепление стоек.",
    ),
    CategorySeed(
        slug="sidenya-kachelej",
        name="Сиденья качелей",
        parent=ROOT_SLUG,
        description="Сиденья для качелей всех возрастных групп, включая «гнёзда».",
    ),
    CategorySeed(
        slug="vtulki-i-gilzy",
        name="Втулки и гильзы",
        parent=ROOT_SLUG,
        description="Полиамидные и бронзовые втулки для вращающихся узлов.",
    ),
    CategorySeed(
        slug="gorki-i-elementy",
        name="Горки и элементы",
        parent=ROOT_SLUG,
        description="Скаты горок, борта и элементы игровых комплексов.",
    ),
    CategorySeed(
        slug="soediniteli-i-furnitura",
        name="Соединители и фурнитура",
        parent=ROOT_SLUG,
        description="Крестовые и угловые соединители, заглушки, фурнитура канатных сетей.",
    ),
    CategorySeed(
        slug="plastikovye-detali",
        name="Пластиковые детали",
        parent=ROOT_SLUG,
        description="HDPE-панели, зацепы скалодрома, декоративные элементы.",
    ),
    CategorySeed(
        slug="metizy-i-antivandal",
        name="Метизы и антивандальный крепёж",
        parent=ROOT_SLUG,
        description="Карабины, хомуты, антивандальные болты и гайки.",
    ),
)

ATTRIBUTES: tuple[AttributeSeed, ...] = (
    AttributeSeed(
        code="diameter",
        name="Диаметр",
        value_type=AttributeValueType.NUMBER,
        unit="мм",
        sort_order=1,
    ),
    AttributeSeed(
        code="material",
        name="Материал",
        value_type=AttributeValueType.OPTION,
        sort_order=2,
        options=(
            ("pp", "Полипропилен"),
            ("steel", "Оцинкованная сталь"),
            ("inox", "Нержавеющая сталь"),
            ("hdpe", "HDPE"),
            ("pa6", "Полиамид"),
            ("rubber", "Резина"),
            ("bronze", "Бронза"),
        ),
    ),
    AttributeSeed(
        code="color",
        name="Цвет",
        value_type=AttributeValueType.OPTION,
        sort_order=3,
        options=(
            ("blue", "Синий"),
            ("red", "Красный"),
            ("yellow", "Жёлтый"),
            ("green", "Зелёный"),
            ("black", "Чёрный"),
            ("grey", "Серый"),
        ),
    ),
    AttributeSeed(
        code="certified",
        name="Сертификат ЕАЭС",
        value_type=AttributeValueType.BOOLEAN,
        sort_order=4,
    ),
)

_M = ProductUnit.METER.value
_PCS = ProductUnit.PIECE.value

PRODUCTS: tuple[ProductSeed, ...] = (
    ProductSeed(
        sku="RP-016",
        slug="kanat-armirovannyj-16-mm",
        name="Канат армированный Ø16 мм",
        short_description="Шестипрядный канат с оцинкованным сердечником для "
        "лазательных сетей и переходов.",
        description="Канат с полипропиленовой оплёткой и стальным сердечником. "
        "Применяется в канатных переходах, лазательных сетях и ограждениях "
        "игровых комплексов. Стойкость к ультрафиолету и перепадам температур "
        "от −45 до +60 °C.",
        category="kanaty-i-seti",
        unit=_M,
        brand="OINAU",
        min_order_qty=Decimal("5"),
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("3500.00"), Decimal("49")),
            TierSeed(Decimal("50"), Decimal("3200.00"), Decimal("199")),
            TierSeed(Decimal("200"), Decimal("2900.00"), Decimal("499")),
            TierSeed(Decimal("500"), Decimal("2600.00")),
        ),
        is_featured=True,
        stock=Decimal("1840.500"),
        attributes={
            "diameter": Decimal("16"),
            "material": "pp",
            "color": "blue",
            "certified": True,
        },
        specs={"Страна производства": "Казахстан", "Разрывная нагрузка": "2 400 кгс"},
    ),
    ProductSeed(
        sku="RP-024",
        slug="kanat-kombinirovannyj-24-mm",
        name="Канат комбинированный Ø24 мм",
        short_description="Несущий канат для больших канатных пирамид.",
        category="kanaty-i-seti",
        unit=_M,
        brand="OINAU",
        min_order_qty=Decimal("5"),
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("5400.00"), Decimal("99")),
            TierSeed(Decimal("100"), Decimal("4950.00")),
        ),
        stock=Decimal("620.000"),
        attributes={
            "diameter": Decimal("24"),
            "material": "pp",
            "color": "black",
            "certified": True,
        },
    ),
    ProductSeed(
        sku="NT-012",
        slug="uzel-setki-shestiluchevoj",
        name="Узел сетки шестилучевой",
        short_description="Полиамидный узел на шесть канатов Ø16 мм.",
        category="kanaty-i-seti",
        unit=_PCS,
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("3200.00")),),
        stock=Decimal("410"),
        attributes={"diameter": Decimal("16"), "material": "pa6", "color": "black"},
    ),
    ProductSeed(
        sku="HN-301",
        slug="podves-kacheli-otsinkovannyj",
        name="Подвес качели оцинкованный",
        short_description="Подвес с полиамидной втулкой, ресурс не менее 500 000 циклов.",
        description="Подвес рассчитан на подвижные элементы качелей с "
        "нагрузкой до 200 кг. Комплектуется полиамидной втулкой и "
        "антивандальным крепежом.",
        category="krepleniya-i-podvesy",
        unit=_PCS,
        brand="OINAU",
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("1200.00"), Decimal("19")),
            TierSeed(Decimal("20"), Decimal("1080.00"), Decimal("99")),
            TierSeed(Decimal("100"), Decimal("960.00")),
        ),
        is_featured=True,
        stock=Decimal("2130"),
        attributes={"diameter": Decimal("10"), "material": "steel", "certified": True},
        specs={"Ресурс": "500 000 циклов", "Нагрузка": "до 200 кг"},
    ),
    ProductSeed(
        sku="CH-076",
        slug="tsep-otsinkovannaya-6-mm",
        name="Цепь оцинкованная Ø6 мм",
        short_description="Короткозвенная цепь DIN 766 для подвеса сидений.",
        category="krepleniya-i-podvesy",
        unit=_M,
        min_order_qty=Decimal("2"),
        pricing_type=PricingType.FROM,
        tiers=(
            TierSeed(Decimal("1"), Decimal("2800.00"), Decimal("99")),
            TierSeed(Decimal("100"), Decimal("2450.00")),
        ),
        stock=Decimal("980.000"),
        attributes={"diameter": Decimal("6"), "material": "steel", "certified": True},
    ),
    ProductSeed(
        sku="MT-101",
        slug="kronshtejn-krepleniya-stojki",
        name="Кронштейн крепления стойки",
        short_description="Анкерный кронштейн под стойку 100×100 мм.",
        category="krepleniya-i-podvesy",
        unit=_PCS,
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("4300.00")),),
        stock=Decimal("156"),
        attributes={"material": "steel", "color": "grey", "certified": True},
    ),
    ProductSeed(
        sku="SW-205",
        slug="sidene-kacheli-universalnoe",
        name="Сиденье качели универсальное",
        short_description="Резиновое сиденье с армированием, крепление на цепь.",
        description="Сиденье из резиновой смеси с внутренним стальным "
        "армированием. Не трескается на морозе, не нагревается на солнце. "
        "Поставляется в сборе с подвесными пластинами.",
        category="sidenya-kachelej",
        unit=_PCS,
        brand="OINAU",
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("15900.00")),),
        is_featured=True,
        stock=Decimal("74"),
        attributes={"material": "rubber", "color": "black", "certified": True},
        specs={"Возрастная группа": "3–12 лет", "Масса": "2,4 кг"},
    ),
    ProductSeed(
        sku="SW-110",
        slug="sidene-detskoe-s-ogranichitelem",
        name="Сиденье детское с ограничителем",
        short_description="Закрытое сиденье для детей от 1 года.",
        category="sidenya-kachelej",
        unit=_PCS,
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("9500.00")),),
        stock=Decimal("48"),
        attributes={"material": "hdpe", "color": "blue", "certified": True},
    ),
    ProductSeed(
        sku="SW-330",
        slug="sidene-gnezdo-1000-mm",
        name="Сиденье-гнездо Ø1000 мм",
        short_description="Канатное гнездо на стальном ободе, до 150 кг.",
        category="sidenya-kachelej",
        unit=_PCS,
        pricing_type=PricingType.ON_REQUEST,
        stock=Decimal("6"),
        attributes={"diameter": Decimal("1000"), "material": "steel", "certified": True},
    ),
    ProductSeed(
        sku="BU-113",
        slug="vtulka-poliamidnaya-16-mm",
        name="Втулка полиамидная Ø16 мм",
        short_description="Втулка скольжения для подвижных узлов.",
        category="vtulki-i-gilzy",
        unit=_PCS,
        min_order_qty=Decimal("10"),
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("450.00"), Decimal("199")),
            TierSeed(Decimal("200"), Decimal("395.00"), Decimal("999")),
            TierSeed(Decimal("1000"), Decimal("340.00")),
        ),
        stock=Decimal("5400"),
        attributes={"diameter": Decimal("16"), "material": "pa6", "color": "black"},
    ),
    ProductSeed(
        sku="BU-208",
        slug="gilza-bronzovaya-20-mm",
        name="Гильза бронзовая Ø20 мм",
        short_description="Гильза для каруселей с повышенной нагрузкой.",
        category="vtulki-i-gilzy",
        unit=_PCS,
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("1450.00")),),
        stock=Decimal("0"),
        attributes={"diameter": Decimal("20"), "material": "bronze"},
    ),
    ProductSeed(
        sku="SL-250",
        slug="gorka-plastikovaya-h-1200",
        name="Горка пластиковая H-1200 мм",
        short_description="Скат горки для высоты платформы 1200 мм.",
        description="Скат ротационного формования, толщина стенки 6 мм. "
        "Комплектуется бортами и крепёжным набором. Цвет подбирается "
        "под проект.",
        category="gorki-i-elementy",
        unit=_PCS,
        brand="OINAU",
        pricing_type=PricingType.ON_REQUEST,
        stock_display_override=StockDisplayOverride.ON_REQUEST,
        attributes={"material": "hdpe", "color": "red", "certified": True},
        specs={"Высота платформы": "1200 мм", "Длина ската": "2400 мм"},
    ),
    ProductSeed(
        sku="SL-410",
        slug="bort-gorki-hdpe",
        name="Борт горки HDPE",
        short_description="Боковой борт ската, комплект из двух штук.",
        category="gorki-i-elementy",
        unit=ProductUnit.SET.value,
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("34500.00")),),
        stock=Decimal("12"),
        attributes={"material": "hdpe", "color": "yellow"},
    ),
    ProductSeed(
        sku="CN-044",
        slug="soedinitel-krestovoj-42",
        name="Соединитель крестовой Ø42",
        short_description="Узел соединения четырёх труб Ø42 мм.",
        category="soediniteli-i-furnitura",
        unit=_PCS,
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("1950.00"), Decimal("49")),
            TierSeed(Decimal("50"), Decimal("1750.00")),
        ),
        stock=Decimal("320"),
        attributes={"diameter": Decimal("42"), "material": "steel"},
    ),
    ProductSeed(
        sku="PL-077",
        slug="zaglushka-plastikovaya-42",
        name="Заглушка пластиковая Ø42",
        short_description="Заглушка торца трубы, УФ-стабилизированная.",
        category="plastikovye-detali",
        unit=_PCS,
        min_order_qty=Decimal("20"),
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("320.00"), Decimal("499")),
            TierSeed(Decimal("500"), Decimal("270.00")),
        ),
        stock=Decimal("8600"),
        attributes={"diameter": Decimal("42"), "material": "hdpe", "color": "black"},
    ),
    ProductSeed(
        sku="PL-330",
        slug="panel-bortovaya-hdpe-12-mm",
        name="Панель бортовая HDPE 12 мм",
        short_description="Панель ограждения платформы, раскрой по чертежу.",
        category="plastikovye-detali",
        unit=_PCS,
        pricing_type=PricingType.FROM,
        tiers=(
            TierSeed(Decimal("1"), Decimal("12400.00"), Decimal("19")),
            TierSeed(Decimal("20"), Decimal("11200.00")),
        ),
        stock=Decimal("96"),
        attributes={"material": "hdpe", "color": "green", "certified": True},
    ),
    ProductSeed(
        sku="PL-512",
        slug="zatsep-skalodroma",
        name="Зацеп скалодрома",
        short_description="Полимерный зацеп с антивандальным болтом.",
        category="plastikovye-detali",
        unit=_PCS,
        min_order_qty=Decimal("10"),
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("1150.00")),),
        is_featured=True,
        stock=Decimal("1240"),
        attributes={"material": "hdpe", "color": "yellow"},
    ),
    ProductSeed(
        sku="CR-090",
        slug="karabin-stalnoj-s-muftoj",
        name="Карабин стальной с муфтой",
        short_description="Карабин с резьбовой муфтой для канатных элементов.",
        category="metizy-i-antivandal",
        unit=_PCS,
        pricing_type=PricingType.TIERED,
        tiers=(
            TierSeed(Decimal("1"), Decimal("890.00"), Decimal("99")),
            TierSeed(Decimal("100"), Decimal("790.00")),
        ),
        stock=Decimal("2400"),
        attributes={"diameter": Decimal("8"), "material": "inox", "certified": True},
    ),
    ProductSeed(
        sku="CL-016",
        slug="homut-obzhimnoj-16-mm",
        name="Хомут обжимной Ø16 мм",
        short_description="Обжимной хомут каната, оцинковка горячего цинкования.",
        category="metizy-i-antivandal",
        unit=_PCS,
        min_order_qty=Decimal("25"),
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("260.00")),),
        stock=Decimal("7800"),
        attributes={"diameter": Decimal("16"), "material": "steel"},
    ),
    ProductSeed(
        sku="AV-820",
        slug="bolt-antivandalnyj-m10",
        name="Болт антивандальный М10",
        short_description="Болт с потайной головкой под специальный ключ.",
        category="metizy-i-antivandal",
        unit=_PCS,
        min_order_qty=Decimal("50"),
        pricing_type=PricingType.FIXED,
        tiers=(TierSeed(Decimal("1"), Decimal("180.00")),),
        stock=Decimal("0"),
        attributes={"diameter": Decimal("10"), "material": "inox"},
    ),
)


# --------------------------------------------------------------------- CMS
#
# Значения соответствуют схемам app/modules/content/schemas_admin.py:
# локализуемые поля — словари по коду языка.

WHATSAPP_NUMBER = "+77270000000"

CONTENT_SECTIONS: dict[str, dict[str, object]] = {
    "settings": {
        "site_name": {"ru": "OINAU PRO"},
        "seo": {
            "title": {"ru": "OINAU PRO — комплектующие для детских и спортивных площадок"},
            "description": {
                "ru": "Канаты, крепёж, сиденья, втулки и готовые узлы для "
                "производителей и монтажных организаций. Алматы, доставка по Казахстану."
            },
        },
        "social_links": [
            {"network": "INSTAGRAM", "url": "https://instagram.com/oinau.pro"},
            {"network": "TELEGRAM", "url": "https://t.me/oinaupro"},
        ],
    },
    "home": {
        "hero": {
            # Утверждённый текст дизайн-концепта v2. Акцентом на витрине
            # подсвечивается предпоследнее слово — «современных».
            "title": {"ru": "Комплектующие для современных площадок"},
            "subtitle": {
                "ru": "Канаты, крепёж, сиденья, горки и готовые узлы со склада "
                "в Алматы — для производителей, монтажных организаций "
                "и муниципальных проектов."
            },
            "cta_label": {"ru": "Перейти в каталог"},
            "cta_url": "/catalog",
        },
        "advantages": [
            {
                "title": {"ru": "Склад в Алматы"},
                "text": {"ru": "Ходовые позиции отгружаются в течение суток."},
            },
            {
                "title": {"ru": "Документы на каждую позицию"},
                "text": {"ru": "Сертификаты ЕАЭС, паспорта качества, отказные письма."},
            },
            {
                "title": {"ru": "Оптовые условия"},
                "text": {"ru": "Цена от объёма, отсрочка платежа, персональный менеджер."},
            },
            {
                "title": {"ru": "Подбор аналогов"},
                "text": {"ru": "Пришлите спецификацию — подберём замену за один рабочий день."},
            },
        ],
        "about": {
            "title": {"ru": "Поставщик комплектующих, а не магазин игрушек"},
            "text": {
                "ru": "OINAU PRO работает с производителями игрового оборудования, "
                "монтажными организациями и подрядчиками благоустройства. Мы держим "
                "на складе то, что заканчивается в середине монтажа: канат, крепёж, "
                "втулки и подвесы. Заявка обрабатывается менеджером, цена считается "
                "по объёму."
            },
        },
        "seo": {
            "title": {"ru": "OINAU PRO — комплектующие для детских площадок в Казахстане"},
            "description": {
                "ru": "Более 5 000 позиций комплектующих для детских и спортивных "
                "площадок. Канаты, крепления, сиденья качелей, втулки, горки. "
                "Оптовые условия для производителей."
            },
        },
    },
    "contacts": {
        "phones": [
            {"number": WHATSAPP_NUMBER, "label": {"ru": "Отдел продаж"}},
            {"number": "+77271111111", "label": {"ru": "Склад"}},
        ],
        "emails": [
            {"email": "sales@oinau-pro.kz", "label": {"ru": "Заявки и спецификации"}},
        ],
        "whatsapp": {
            "number": WHATSAPP_NUMBER,
            "message": {"ru": "Здравствуйте! Пишу с сайта oinau-pro.kz"},
        },
        "address": {"ru": "Алматы, ул. Рыскулова 103, склад 4"},
        "working_hours": {"ru": "Пн–Пт 09:00–18:00, Сб 10:00–15:00"},
        "map": {"latitude": 43.2971, "longitude": 76.8874},
        "seo": {
            "title": {"ru": "Контакты"},
            "description": {"ru": "Адрес склада, телефоны и реквизиты OINAU PRO в Алматы."},
        },
    },
    "requisites": {
        "company_name": {"ru": "ТОО «OINAU PRO» (демонстрационные данные)"},
        "bin": "010203040506",
        "iban": "KZ233456789012345678",
        "bank_name": {"ru": "АО «Демо Банк»"},
        "bik": "DEMOKZKA",
        "kbe": "17",
        "legal_address": {"ru": "Алматы, ул. Рыскулова 103"},
    },
    "delivery": {
        "intro": {
            "ru": "Отгружаем со склада в Алматы. Крупные позиции (скаты горок, "
            "бухты каната) отправляем транспортными компаниями по всему Казахстану."
        },
        "methods": [
            {
                "title": {"ru": "Самовывоз со склада"},
                "text": {
                    "ru": "Алматы, ул. Рыскулова 103. Готовность заказа — в течение "
                    "рабочего дня после подтверждения."
                },
            },
            {
                "title": {"ru": "Доставка по Алматы"},
                "text": {"ru": "В день заказа при оформлении до 14:00. Тариф зависит от объёма."},
            },
            {
                "title": {"ru": "Транспортные компании по Казахстану"},
                "text": {
                    "ru": "Отправка до терминала перевозчика бесплатно, дальше — "
                    "по тарифу транспортной компании."
                },
            },
        ],
        "payment": {
            "ru": "Безналичный расчёт с НДС и без, оплата по счёту. Для постоянных "
            "клиентов — отсрочка платежа по договору."
        },
        "seo": {
            "title": {"ru": "Доставка и оплата"},
            "description": {
                "ru": "Условия доставки комплектующих по Алматы и Казахстану, "
                "способы оплаты и отсрочка платежа."
            },
        },
    },
    "services": {
        "intro": {
            "ru": "Готовим комплектующие под ваш проект на своём складе в Алматы: "
            "режем и обжимаем канат, режем металл в размер. Работаем по спецификации "
            "или чертежу, срок и стоимость — в ответ на заявку."
        },
        "items": [
            {
                "slug": "obzhimka-kanatov",
                "title": {"ru": "Обжимка канатов"},
                "summary": {
                    "ru": "Опрессовка армированного каната втулками и наконечниками "
                    "для сеток, мостов и лазательных элементов."
                },
                "details": [
                    {"ru": "Алюминиевые и стальные втулки, коуши, наконечники"},
                    {"ru": "Канат диаметром 16 и 18 мм"},
                    {"ru": "Сборка по схеме или по образцу заказчика"},
                ],
                "price_note": {"ru": "Стоимость — по объёму партии"},
            },
            {
                "slug": "obrezka-kanatov",
                "title": {"ru": "Обрезка канатов в размер"},
                "summary": {
                    "ru": "Режем канат из бухты на отрезки нужной длины с оплавлением "
                    "концов, чтобы оплётка не распускалась."
                },
                "details": [
                    {"ru": "Отрезки любой длины по спецификации"},
                    {"ru": "Оплавление и маркировка концов"},
                    {"ru": "Упаковка комплектами под объект"},
                ],
                "price_note": {"ru": "При заказе каната — без доплаты"},
            },
            {
                "slug": "metallorezka",
                "title": {"ru": "Металлорезка"},
                "summary": {
                    "ru": "Резка трубы, профиля и прутка в размер для каркасов "
                    "и закладных деталей площадок."
                },
                "details": [
                    {"ru": "Труба и профильная труба, пруток, полоса"},
                    {"ru": "Резка под прямым углом и под углом"},
                    {"ru": "Снятие заусенцев после резки"},
                ],
                "price_note": {"ru": "Стоимость — по количеству резов"},
            },
            {
                "slug": "podbor-po-specifikacii",
                "title": {"ru": "Подбор по спецификации"},
                "summary": {
                    "ru": "Разберём спецификацию проекта, подберём позиции со склада "
                    "и аналоги, подготовим коммерческое предложение."
                },
                "details": [
                    {"ru": "Проверка совместимости узлов и крепежа"},
                    {"ru": "Аналоги отсутствующих позиций"},
                    {"ru": "КП с ценами от объёма в течение рабочего дня"},
                ],
            },
        ],
        "seo": {
            "title": {"ru": "Услуги: обжимка и обрезка канатов, металлорезка"},
            "description": {
                "ru": "Обжимка и обрезка канатов, резка металла в размер и подбор "
                "комплектующих по спецификации — склад OINAU PRO в Алматы."
            },
        },
    },
    "faq": {
        "items": [
            {
                "question": {"ru": "Работаете ли вы с физическими лицами?"},
                "answer": {
                    "ru": "Да, но основной формат — поставка организациям. "
                    "Минимальная партия указана в карточке каждой позиции."
                },
            },
            {
                "question": {"ru": "Как узнать цену на позицию «по запросу»?"},
                "answer": {
                    "ru": "Добавьте позицию в заявку и отправьте её. Менеджер "
                    "рассчитает стоимость с учётом объёма и цвета в течение "
                    "рабочего дня."
                },
            },
            {
                "question": {"ru": "Есть ли сертификаты на продукцию?"},
                "answer": {
                    "ru": "На комплектующие, подлежащие обязательной сертификации, "
                    "предоставляем сертификаты ЕАЭС и паспорта качества вместе "
                    "с отгрузочными документами."
                },
            },
            {
                "question": {"ru": "Можно ли заказать нестандартный размер?"},
                "answer": {
                    "ru": "Канат, цепь и панели режем в размер. По остальным "
                    "позициям пришлите чертёж — ответим о возможности изготовления."
                },
            },
            {
                "question": {"ru": "Как быстро отвечаете на заявку?"},
                "answer": {
                    "ru": "В рабочие часы — в течение двух часов. Заявки, "
                    "оставленные ночью и в выходные, обрабатываем утром "
                    "следующего рабочего дня."
                },
            },
        ],
        "seo": {
            "title": {"ru": "Частые вопросы"},
            "description": {
                "ru": "Ответы на вопросы о поставке комплектующих для площадок: "
                "минимальные партии, сертификаты, сроки и нестандартные размеры."
            },
        },
    },
}
