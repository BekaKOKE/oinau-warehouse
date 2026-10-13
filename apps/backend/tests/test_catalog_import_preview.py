"""Предпросмотр импорта: проверка файла без изменения каталога."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Attribute, Category, Product
from app.modules.imports.models import ImportJob
from app.modules.pricing.models import PriceTier
from tests.conftest import Headers
from tests.helpers import count_queries
from tests.import_helpers import (
    IMPORTS,
    PREVIEW,
    SPECS,
    attribute_row,
    build_workbook,
    category_row,
    count_rows,
    errors_by,
    preview,
    product_row,
    upload,
)


def one_issue(report: dict[str, Any], code: str) -> dict[str, Any]:
    found = errors_by(report, code)
    assert found, report["errors"]
    return found[0]


# ================================================================= валидный файл
async def test_valid_file_preview_does_not_touch_catalog(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    before = {
        model.__name__: await count_rows(committed_session, model)
        for model in (Product, Category, Attribute, PriceTier)
    }
    data = build_workbook(
        {
            "Categories": [category_row("novaya", parent_slug="komplektuyushchie")],
            "Attributes": [attribute_row("color", "OPTION")],
            "AttributeOptions": [
                {"attribute_code": "color", "slug": "red", "value_ru": "Красный", "sort_order": 0}
            ],
            "Products": [
                product_row("NEW-1", categories="novaya; kanaty", pricing_type="FIXED"),
            ],
            "Prices": [{"sku": "NEW-1", "min_qty": 1, "price": 500}],
            "ProductAttributes": [
                {"sku": "NEW-1", "attribute_code": "color", "value": "red"},
                {"sku": "NEW-1", "attribute_code": "diameter", "value": 10},
            ],
        }
    )

    report = await preview(api, admin, data)

    assert report["valid"] is True
    assert report["error_count"] == 0
    assert report["summary"]["products"] == {"create": 1, "update": 0, "unchanged": 0}
    assert report["summary"]["categories"]["create"] == 1
    assert report["summary"]["attributes"]["create"] == 1
    assert report["summary"]["attribute_options"]["create"] == 1
    assert report["summary"]["rows_total"] == 7
    assert report["changes"] == [{"row": 2, "sku": "NEW-1", "action": "create", "changed": []}]

    job = report["job"]
    assert job["status"] == "VALID"
    assert job["can_commit"] is True
    assert job["filename"] == "catalog.xlsx"
    assert job["products_created"] == 1
    assert len(job["file_sha256"]) == 64

    committed_session.expire_all()
    after = {
        model.__name__: await count_rows(committed_session, model)
        for model in (Product, Category, Attribute, PriceTier)
    }
    assert after == before

    audit = (
        (await committed_session.execute(select(AuditLog).where(AuditLog.action.like("catalog%"))))
        .scalars()
        .all()
    )
    assert [entry.action for entry in audit] == ["catalog_import.previewed"]
    # Содержимое файла в журнал не пишется — только метаданные.
    assert "NEW-1" not in str(audit[0].changes)


async def test_preview_is_recorded_in_history(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(api, admin, build_workbook({"Products": [product_row("HIST-1")]}))

    listing = (await api.get(IMPORTS, headers=admin)).json()
    assert listing["total"] == 1
    assert listing["items"][0]["uuid"] == report["job"]["uuid"]

    detail = (await api.get(f"{IMPORTS}/{report['job']['uuid']}", headers=admin)).json()
    assert detail["status"] == "VALID"
    assert detail["summary"]["products"]["create"] == 1
    assert detail["errors"] == []

    invalid = await preview(api, admin, build_workbook({"Products": [product_row("bad sku")]}))
    assert invalid["job"]["status"] == "INVALID"
    only_invalid = (await api.get(IMPORTS, headers=admin, params={"status": "INVALID"})).json()
    assert [item["uuid"] for item in only_invalid["items"]] == [invalid["job"]["uuid"]]
    detail = (await api.get(f"{IMPORTS}/{invalid['job']['uuid']}", headers=admin)).json()
    assert detail["errors"][0]["column"] == "sku"


async def test_unknown_job_returns_404(api: AsyncClient, admin: Headers) -> None:
    response = await api.get(f"{IMPORTS}/00000000-0000-0000-0000-000000000000", headers=admin)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "import_job_not_found"


# ============================================================ структура книги
async def test_empty_file_is_rejected(api: AsyncClient, admin: Headers) -> None:
    response = await upload(api, PREVIEW, admin, b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "import_file_empty"


async def test_workbook_without_data_is_invalid(api: AsyncClient, admin: Headers) -> None:
    report = await preview(api, admin, build_workbook())
    assert report["valid"] is False
    assert one_issue(report, "empty_workbook")["sheet"] is None


async def test_missing_sheet(api: AsyncClient, admin: Headers) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("A-1")]}, omit={"Prices"})
    )
    assert report["valid"] is False
    issue = one_issue(report, "missing_sheet")
    assert issue["sheet"] == "Prices"


async def test_missing_required_column(api: AsyncClient, admin: Headers) -> None:
    columns = [name for name in SPECS["Products"].column_names if name != "slug"]
    data = build_workbook({"Products": [product_row("A-1")]}, headers={"Products": columns})

    report = await preview(api, admin, data)
    assert report["valid"] is False
    issue = one_issue(report, "missing_column")
    assert (issue["sheet"], issue["row"], issue["column"]) == ("Products", 1, "slug")


async def test_unknown_column_is_an_error_but_comment_column_is_ignored(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    columns = [*SPECS["Products"].column_names, "#примечание"]
    row = product_row("A-1")
    row["#примечание"] = "=SUM(1,2)"  # даже формула в колонке-пометке не мешает
    report = await preview(
        api, admin, build_workbook({"Products": [row]}, headers={"Products": columns})
    )
    assert report["valid"] is True, report["errors"]

    columns = [*SPECS["Products"].column_names, "prce"]
    report = await preview(
        api,
        admin,
        build_workbook({"Products": [product_row("A-1")]}, headers={"Products": columns}),
    )
    assert report["valid"] is False
    assert one_issue(report, "unknown_column")["column"] == "prce"


async def test_headers_are_case_insensitive(api: AsyncClient, admin: Headers, catalog) -> None:
    columns = [name.upper() for name in SPECS["Products"].column_names]
    row = {name.upper(): value for name, value in product_row("CASE-1").items()}
    report = await preview(
        api, admin, build_workbook({"Products": [row]}, headers={"Products": columns})
    )
    assert report["valid"] is True, report["errors"]


# ================================================================== артикулы
async def test_missing_sku(api: AsyncClient, admin: Headers) -> None:
    row = product_row("X-1")
    row["sku"] = None
    report = await preview(api, admin, build_workbook({"Products": [row]}))

    issue = one_issue(report, "required")
    assert (issue["sheet"], issue["row"], issue["column"]) == ("Products", 2, "sku")


async def test_duplicate_sku_in_file(api: AsyncClient, admin: Headers) -> None:
    data = build_workbook(
        {"Products": [product_row("DUP-1"), product_row("DUP-1", slug="dup-1-second")]}
    )
    report = await preview(api, admin, data)

    issue = one_issue(report, "duplicate_row")
    assert (issue["row"], issue["column"]) == (3, "sku")
    assert "строке 2" in issue["message"]


async def test_sku_differing_only_by_case(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("kan-16-pp", slug="kanat-lower")]})
    )
    issue = one_issue(report, "sku_case_conflict")
    assert "KAN-16-PP" in issue["message"]


async def test_slug_taken_by_other_product(api: AsyncClient, admin: Headers, catalog) -> None:
    """Смена артикула — не переименование: новый артикул упирается в slug старого."""
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("KAN-16-NEW", slug="kanat-16-pp")]})
    )
    issue = one_issue(report, "slug_taken")
    assert issue["column"] == "slug"
    assert "KAN-16-PP" in issue["message"]


async def test_external_id_conflict(api: AsyncClient, admin: Headers, catalog) -> None:
    await api.patch(
        f"/api/v1/admin/products/{catalog.products['fastener'].id}",
        headers=admin,
        json={"external_id": "1c-guid-1"},
    )
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("EXT-1", external_id="1c-guid-1")]})
    )
    assert "KRP-M10" in one_issue(report, "external_id_taken")["message"]


async def test_invalid_sku_characters(api: AsyncClient, admin: Headers) -> None:
    report = await preview(api, admin, build_workbook({"Products": [product_row("КАН 16")]}))
    issue = one_issue(report, "invalid_value")
    assert issue["column"] == "sku"
    assert issue["value"] == "КАН 16"


async def test_deleted_sku_reuse_is_a_warning(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {"Products": [product_row("DEL-1", slug="udalennyj-novyj", categories="kanaty")]}
        ),
    )
    assert report["valid"] is True
    assert report["summary"]["products"]["create"] == 1
    assert [item["code"] for item in report["warnings"]] == ["deleted_sku_reused"]


# ================================================================= категории
async def test_unknown_and_deleted_category(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    from datetime import UTC, datetime

    hidden = await committed_session.get(Category, catalog.categories["hidden"].id)
    assert hidden is not None
    hidden.deleted_at = datetime.now(UTC)
    await committed_session.commit()

    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [
                    product_row("C-1", categories="net-takoj"),
                    product_row("C-2", categories="skrytaya"),
                ]
            }
        ),
    )
    assert one_issue(report, "category_not_found")["row"] == 2
    assert one_issue(report, "category_deleted")["row"] == 3


async def test_category_cycle_is_rejected(api: AsyncClient, admin: Headers, catalog) -> None:
    data = build_workbook(
        {
            "Categories": [
                # komplektuyushchie под своего же ребёнка kanaty -> кольцо
                category_row("komplektuyushchie", parent_slug="kanaty"),
                category_row("kanaty", parent_slug="komplektuyushchie"),
            ]
        }
    )
    report = await preview(api, admin, data)
    assert report["valid"] is False
    assert {issue["row"] for issue in errors_by(report, "category_cycle")} == {2, 3}

    self_parent = await preview(
        api, admin, build_workbook({"Categories": [category_row("petlya", parent_slug="petlya")]})
    )
    assert one_issue(self_parent, "category_cycle")["column"] == "parent_slug"


async def test_unknown_parent_category(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api, admin, build_workbook({"Categories": [category_row("sirota", parent_slug="net")]})
    )
    assert one_issue(report, "category_not_found")["column"] == "parent_slug"


async def test_category_attributes_only_for_categories_in_file(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Categories": [category_row("novaya")],
                "CategoryAttributes": [
                    {
                        "category_slug": "kanaty",
                        "attribute_code": "diameter",
                        "sort_order": 0,
                        "is_required": False,
                    }
                ],
            }
        ),
    )
    assert one_issue(report, "unknown_category")["sheet"] == "CategoryAttributes"


# ============================================================ характеристики
async def test_unknown_attribute(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("A-1")],
                "ProductAttributes": [{"sku": "A-1", "attribute_code": "weight", "value": 5}],
            }
        ),
    )
    issue = one_issue(report, "attribute_not_found")
    assert (issue["sheet"], issue["row"], issue["column"]) == (
        "ProductAttributes",
        2,
        "attribute_code",
    )


async def test_wrong_option(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("A-1")],
                "ProductAttributes": [
                    {"sku": "A-1", "attribute_code": "material", "value": "steel"}
                ],
            }
        ),
    )
    issue = one_issue(report, "option_not_found")
    assert issue["column"] == "value"
    assert "steel" in issue["message"]


async def test_option_of_another_attribute_is_rejected(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    """Вариант ищется только внутри своей характеристики."""
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Attributes": [attribute_row("color", "OPTION")],
                "AttributeOptions": [
                    {
                        "attribute_code": "color",
                        "slug": "red",
                        "value_ru": "Красный",
                        "sort_order": 0,
                    }
                ],
                "Products": [product_row("A-1")],
                "ProductAttributes": [{"sku": "A-1", "attribute_code": "material", "value": "red"}],
            }
        ),
    )
    assert one_issue(report, "option_not_found")["sheet"] == "ProductAttributes"


async def test_attribute_value_must_match_type(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("A-1")],
                "ProductAttributes": [
                    {"sku": "A-1", "attribute_code": "diameter", "value": "толстый"},
                    {"sku": "A-1", "attribute_code": "certified", "value": "может быть"},
                ],
            }
        ),
    )
    rows = {issue["row"] for issue in errors_by(report, "invalid_value")}
    assert rows == {2, 3}


async def test_scalar_attribute_cannot_have_two_values(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("A-1")],
                "ProductAttributes": [
                    {"sku": "A-1", "attribute_code": "diameter", "value": 10},
                    {"sku": "A-1", "attribute_code": "diameter", "value": 12},
                ],
            }
        ),
    )
    assert one_issue(report, "duplicate_row")["row"] == 3


async def test_attribute_type_cannot_change(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api, admin, build_workbook({"Attributes": [attribute_row("diameter", "STRING")]})
    )
    issue = one_issue(report, "attribute_type_change")
    assert "NUMBER" in issue["message"]


async def test_options_only_for_option_attributes(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "AttributeOptions": [
                    {
                        "attribute_code": "diameter",
                        "slug": "big",
                        "value_ru": "Большой",
                        "sort_order": 0,
                    }
                ]
            }
        ),
    )
    assert one_issue(report, "attribute_not_option")["sheet"] == "AttributeOptions"


# ===================================================================== числа
@pytest.mark.parametrize(
    ("price", "fragment"),
    [
        ("дорого", "Ожидается число"),
        (1200.555, "2 знаков"),
        (-5, "не меньше 0"),
        ("1e20", "Слишком большое"),
    ],
)
async def test_invalid_price_decimal(
    api: AsyncClient, admin: Headers, catalog, price: Any, fragment: str
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("P-1", pricing_type="FIXED")],
                "Prices": [{"sku": "P-1", "min_qty": 1, "price": price}],
            }
        ),
    )
    issue = one_issue(report, "invalid_value")
    assert (issue["sheet"], issue["column"]) == ("Prices", "price")
    assert fragment in issue["message"]


async def test_russian_decimal_text_is_accepted(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("P-1", pricing_type="FIXED", min_order_qty="2,5")],
                "Prices": [{"sku": "P-1", "min_qty": "1", "price": "1 200,50"}],
            }
        ),
    )
    assert report["valid"] is True, report["errors"]


@pytest.mark.parametrize("value", [0, -1, "много", 1.2345])
async def test_invalid_min_order_qty(api: AsyncClient, admin: Headers, value: Any) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("Q-1", min_order_qty=value)]})
    )
    issue = one_issue(report, "invalid_value")
    assert (issue["sheet"], issue["column"]) == ("Products", "min_order_qty")


# ====================================================================== цены
@pytest.mark.parametrize(
    ("pricing_type", "tiers", "fragment"),
    [
        (
            "FIXED",
            [(1, 9, 100), (10, None, 90)],
            "ровно одна ступень",
        ),
        ("FIXED", [(5, None, 100)], "min_qty=1"),
        ("TIERED", [(1, 10, 100), (10, None, 90)], "пересекаются"),
        ("TIERED", [], "хотя бы одна ступень"),
        ("ON_REQUEST", [(1, None, 100)], "ON_REQUEST"),
        ("TIERED", [(index * 10 + 1, index * 10 + 10, 100) for index in range(21)], "20"),
    ],
)
async def test_invalid_pricing(
    api: AsyncClient,
    admin: Headers,
    catalog,
    pricing_type: str,
    tiers: list[tuple[Any, Any, Any]],
    fragment: str,
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("P-1", pricing_type=pricing_type)],
                "Prices": [
                    {"sku": "P-1", "min_qty": low, "max_qty": high, "price": price}
                    for low, high, price in tiers
                ],
            }
        ),
    )
    assert report["valid"] is False
    issue = one_issue(report, "invalid_pricing")
    assert (issue["sheet"], issue["column"]) == ("Products", "pricing_type")
    assert fragment in issue["message"]


async def test_tier_range_is_checked_per_row(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("P-1", pricing_type="TIERED")],
                "Prices": [{"sku": "P-1", "min_qty": 10, "max_qty": 5, "price": 100}],
            }
        ),
    )
    issue = one_issue(report, "invalid_value")
    assert (issue["sheet"], issue["row"]) == ("Prices", 2)


async def test_child_rows_require_product_in_file(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [product_row("A-1")],
                "Prices": [{"sku": "KAN-16-PP", "min_qty": 1, "price": 100}],
            }
        ),
    )
    issue = one_issue(report, "unknown_sku")
    assert (issue["sheet"], issue["value"]) == ("Prices", "KAN-16-PP")


# ============================================================ ячейки и тексты
async def test_formula_cells_are_rejected(api: AsyncClient, admin: Headers) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("F-1", name_ru='=CONCAT("a","b")')]})
    )
    issue = one_issue(report, "formula_not_allowed")
    assert (issue["row"], issue["column"]) == (2, "name_ru")
    # Одна ошибка на ячейку, без повторного «значение обязательно».
    assert errors_by(report, "required") == []


async def test_html_and_control_characters_are_rejected(api: AsyncClient, admin: Headers) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [
                    product_row("H-1", name_ru="<script>alert(1)</script>"),
                    product_row("H-2", description_ru="текст‮перевёрнутый"),
                ]
            }
        ),
    )
    issues = errors_by(report, "invalid_value")
    assert {(issue["row"], issue["column"]) for issue in issues} == {
        (2, "name_ru"),
        (3, "description_ru"),
    }


async def test_boolean_and_enum_spellings(api: AsyncClient, admin: Headers, catalog) -> None:
    report = await preview(
        api,
        admin,
        build_workbook(
            {
                "Products": [
                    product_row("B-1", is_active="да", is_featured="нет", status="published"),
                    product_row("B-2", is_active=1, is_featured=0, pricing_type="on_request"),
                    product_row("B-3", is_active="TRUE", is_featured="false"),
                ]
            }
        ),
    )
    assert report["valid"] is True, report["errors"]

    report = await preview(
        api, admin, build_workbook({"Products": [product_row("B-4", is_active="возможно")]})
    )
    assert one_issue(report, "invalid_value")["column"] == "is_active"


async def test_required_fields_cannot_be_empty(api: AsyncClient, admin: Headers) -> None:
    row = product_row("E-1")
    for column in (
        "slug",
        "name_ru",
        "status",
        "is_active",
        "unit",
        "min_order_qty",
        "pricing_type",
    ):
        row[column] = None
    report = await preview(api, admin, build_workbook({"Products": [row]}))
    assert {issue["column"] for issue in errors_by(report, "required")} == {
        "slug",
        "name_ru",
        "status",
        "is_active",
        "unit",
        "min_order_qty",
        "pricing_type",
    }


# ============================================================ отчёт о правках
async def test_preview_reports_what_changes(api: AsyncClient, admin: Headers, catalog) -> None:
    data = build_workbook(
        {
            "Products": [
                product_row(
                    "KRP-M10",
                    slug="kreplenie-m10",
                    name_ru="Крепление М10 оцинкованное",
                    categories="krepleniya",
                    pricing_type="FIXED",
                    is_featured=True,
                ),
            ],
            "Prices": [{"sku": "KRP-M10", "min_qty": 1, "price": 1300}],
        }
    )
    report = await preview(api, admin, data)
    assert report["valid"] is True, report["errors"]
    assert report["changes"] == [
        {"row": 2, "sku": "KRP-M10", "action": "update", "changed": ["is_featured", "pricing"]}
    ]


async def test_new_product_without_price_is_a_warning(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("W-1", pricing_type="FIXED")]})
    )
    assert report["valid"] is True
    assert {item["code"] for item in report["warnings"]} == {
        "product_without_price",
        "product_without_category",
    }


async def test_errors_across_all_sheets_are_reported_at_once(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    data = build_workbook(
        {
            "Products": [product_row("M-1", min_order_qty=0), product_row("M-2", unit=None)],
            "Prices": [{"sku": "M-1", "min_qty": 1, "price": "x"}],
            "Categories": [category_row("Плохой slug")],
        }
    )
    report = await preview(api, admin, data)
    assert {issue["sheet"] for issue in report["errors"]} == {"Products", "Prices", "Categories"}
    assert report["error_count"] == len(report["errors"]) == 4


async def test_preview_query_count_does_not_grow_with_rows(
    api: AsyncClient, admin: Headers, catalog, test_engine: AsyncEngine
) -> None:
    def workbook(count: int) -> bytes:
        return build_workbook(
            {
                "Products": [
                    product_row(f"N-{index}", categories="kanaty", pricing_type="FIXED")
                    for index in range(count)
                ]
                + [product_row("KAN-16-PP", slug="kanat-16-pp", categories="kanaty")],
                "Prices": [
                    {"sku": f"N-{index}", "min_qty": 1, "price": 10} for index in range(count)
                ],
                "ProductAttributes": [
                    {"sku": f"N-{index}", "attribute_code": "diameter", "value": index}
                    for index in range(count)
                ],
            }
        )

    small, large = workbook(3), workbook(60)
    with count_queries(test_engine) as few:
        await preview(api, admin, small)
    with count_queries(test_engine) as many:
        await preview(api, admin, large)
    assert len(many) == len(few)


async def test_import_jobs_store_no_file_content(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    report = await preview(
        api, admin, build_workbook({"Products": [product_row("SECRET-1", name_ru="Тайное имя")]})
    )
    job = (
        await committed_session.execute(
            select(ImportJob).where(ImportJob.uuid == report["job"]["uuid"])
        )
    ).scalar_one()
    stored = f"{job.summary} {job.errors} {job.warnings}"
    assert "Тайное имя" not in stored
