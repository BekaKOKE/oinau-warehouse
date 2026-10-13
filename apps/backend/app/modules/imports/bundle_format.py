"""Формат пакетного импорта: ZIP с книгой, фотографиями и схемами.

    bundle.zip
        products.xlsx          книга каталога
        photos/504-176.jpg     фотографии товаров
        schemes/504-176.pdf    схемы и чертежи

Книга — тот же канонический формат, что у обычного Excel-импорта
(xlsx_format.py), с тремя послаблениями для ручной подготовки файла:

* обязателен только лист товаров («Products», «Товары» или первый лист
  книги); остальные листы необязательны — отсутствующий лист означает
  «эту часть товаров не менять»;
* на листе товаров обязательна только колонка артикула; отсутствующая
  колонка или пустая ячейка — «не менять» (у нового товара — значение
  по умолчанию);
* заголовки можно писать по-русски («Артикул», «Название», «Цена от 100»,
  «Фото», «Схема», ...) — они приводятся к каноническим именам.

И несколько колонок, которых в обычном формате нет: фотографии, схемы,
остатки, одна цена или цены по количеству прямо на листе товаров.
Полное описание — docs/api-catalog-import-export.md.
"""

from __future__ import annotations

import re
import unicodedata

from app.modules.imports.xlsx_format import (
    ColumnSpec,
    Sheet,
    SheetSpec,
    build_sheet_specs,
)

BUNDLE_XLSX_NAME = "products.xlsx"
PHOTOS_DIR = "photos"
SCHEMES_DIR = "schemes"

# Имена листа товаров, которые узнаёт пакетный импорт (без учёта регистра).
PRODUCTS_SHEET_NAMES = ("products", "товары")

# Расширение файла в архиве -> тип, на который оно претендует. Настоящий
# тип проверяется по содержимому (сигнатура), расширение — первое сито.
PHOTO_EXTENSIONS: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
SCHEME_EXTENSIONS: dict[str, str] = {
    **PHOTO_EXTENSIONS,
    "pdf": "application/pdf",
    "dwg": "image/vnd.dwg",
    "dxf": "image/vnd.dxf",
}

# Служебный мусор архиваторов и ОС — пропускается молча.
IGNORED_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
IGNORED_PREFIXES = ("__macosx/",)

# Канонические колонки листа товаров, которых нет в обычном формате.
PHOTOS = "photos"
SCHEMES = "schemes"
STOCK = "stock"
RESERVED = "reserved"
PRICE = "price"
CURRENCY = "currency"
SPECS = "specs"
PRICE_FROM_PREFIX = "price_from_"
PHOTO_COLUMN_PREFIX = "photos_"
SPEC_PREFIX = "spec:"
ATTRIBUTE_PREFIX = "attr:"

# Разделители списков в ячейках «Фото» и «Схема»: «;» — как в обычном
# формате; перевод строки — если файлы перечислены в столбик.
FILE_LIST_SEPARATORS = re.compile(r"[;\n\r]+")

_PRICE_FROM = re.compile(r"^(?:цена\s*от|price\s*from)\s*([0-9][0-9\s  ]*(?:[.,][0-9]+)?)$")
_PHOTO_N = re.compile(r"^(?:фото|photo|photos)\s*[_#№]?\s*([0-9]{1,2})$")
_SPEC = re.compile(r"^(?:хар|характеристика|spec)\s*:\s*(.+)$", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"^(?:attr|атрибут)\s*:\s*([a-z0-9_]+)$", re.IGNORECASE)

# Русские и альтернативные заголовки -> каноническое имя колонки.
_ALIASES: dict[str, str] = {
    "артикул": "sku",
    "код товара": "sku",
    "sku": "sku",
    "название": "name_ru",
    "наименование": "name_ru",
    "name": "name_ru",
    "категория": "categories",
    "категории": "categories",
    "раздел": "categories",
    "описание": "description_ru",
    "краткое описание": "short_description_ru",
    "seo заголовок": "seo_title_ru",
    "seo описание": "seo_description_ru",
    "статус": "status",
    "активен": "is_active",
    "активность": "is_active",
    "активный": "is_active",
    "избранное": "is_featured",
    "избранный": "is_featured",
    "популярный": "is_featured",
    "единица": "unit",
    "ед. изм.": "unit",
    "ед.изм.": "unit",
    "единица измерения": "unit",
    "минимальная партия": "min_order_qty",
    "мин. партия": "min_order_qty",
    "тип цены": "pricing_type",
    "бренд": "brand",
    "производитель": "brand",
    "код 1с": "external_id",
    "внешний код": "external_id",
    "цена": PRICE,
    "валюта": CURRENCY,
    "остаток": STOCK,
    "количество на складе": STOCK,
    "резерв": RESERVED,
    "фото": PHOTOS,
    "фотографии": PHOTOS,
    "изображения": PHOTOS,
    "схема": SCHEMES,
    "схемы": SCHEMES,
    "чертеж": SCHEMES,
    "чертежи": SCHEMES,
    "характеристики": SPECS,
}


def _normalize(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[\s  ]+", " ", text).strip()
    return text.rstrip(":").strip()


def resolve_header(raw: str) -> str | None:
    """Заголовок колонки листа товаров -> каноническое имя.

    Канонические имена обычного формата (`sku`, `name_ru`, ...) остаются
    как есть — выгруженную книгу можно положить в пакет без правок.
    Колонки-пометки (`# ...`) не трогаются. Имя характеристики в
    `хар: Цвет` сохраняет регистр: это подпись на витрине.
    """
    text = _normalize(raw)
    if not text:
        return None
    if text.startswith("#"):
        return text
    spec = _SPEC.match(text)
    if spec:
        return f"{SPEC_PREFIX}{spec.group(1).strip()}"
    lowered = text.lower()
    attribute = _ATTRIBUTE.match(lowered)
    if attribute:
        return f"{ATTRIBUTE_PREFIX}{attribute.group(1)}"
    price_from = _PRICE_FROM.match(lowered)
    if price_from:
        quantity = re.sub(r"[\s  ]", "", price_from.group(1)).replace(",", ".")
        return f"{PRICE_FROM_PREFIX}{quantity}"
    photo = _PHOTO_N.match(lowered)
    if photo:
        return f"{PHOTO_COLUMN_PREFIX}{int(photo.group(1))}"
    return _ALIASES.get(lowered, lowered)


def is_dynamic_column(name: str) -> bool:
    """Колонки с переменной частью имени: цены «от N», «Фото N», характеристики."""
    return name.startswith((PRICE_FROM_PREFIX, PHOTO_COLUMN_PREFIX, SPEC_PREFIX, ATTRIBUTE_PREFIX))


def build_bundle_sheet_specs(locales: list[str], default_locale: str) -> dict[str, SheetSpec]:
    """Спецификация книги пакета: канонический формат с послаблениями.

    Лист товаров: обязателен только `sku`, добавлены колонки пакета.
    Остальные листы — те же, что в обычном формате, но необязательны.
    """
    specs = build_sheet_specs(locales, default_locale)
    result: dict[str, SheetSpec] = {}
    for name, spec in specs.items():
        if name == Sheet.PRODUCTS:
            columns = tuple(
                ColumnSpec(column.name, required=column.name == "sku", width=column.width)
                for column in spec.columns
            ) + tuple(
                ColumnSpec(extra, required=False, width=width)
                for extra, width in (
                    (PRICE, 12),
                    (CURRENCY, 8),
                    (STOCK, 10),
                    (RESERVED, 10),
                    (PHOTOS, 36),
                    (SCHEMES, 24),
                    (SPECS, 36),
                )
            )
            result[name] = SheetSpec(
                name,
                columns,
                spec.description,
                optional=False,
                alternatives=PRODUCTS_SHEET_NAMES,
                first_sheet_fallback=True,
                resolve_header=resolve_header,
                dynamic=is_dynamic_column,
            )
        else:
            result[name] = SheetSpec(name, spec.columns, spec.description, optional=True)
    return result


# ---------------------------------------------------------------- slug

_TRANSLIT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "ә": "a",
    "ғ": "g",
    "қ": "k",
    "ң": "n",
    "ө": "o",
    "ұ": "u",
    "ү": "u",
    "һ": "h",
    "і": "i",
}
_SLUG_MAX = 200


def slugify(text: str) -> str:
    """То же правило транслитерации, что у кнопки «slug из названия» в админке."""
    translit = "".join(_TRANSLIT.get(char, char) for char in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", translit).strip("-")


def product_slug(name: str, sku: str) -> str:
    """slug нового товара: название + артикул.

    Артикул в хвосте делает slug уникальным даже у одноимённых позиций
    («Сиденье» бывает десятком артикулов) и стабильным при повторном
    импорте.
    """
    sku_part = slugify(sku) or "item"
    name_part = slugify(name)[: _SLUG_MAX - len(sku_part) - 1].strip("-")
    return f"{name_part}-{sku_part}" if name_part else sku_part
