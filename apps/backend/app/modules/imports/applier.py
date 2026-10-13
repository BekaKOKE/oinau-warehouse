"""Применение проверенного плана импорта.

Работает внутри транзакции вызывающего сервиса и сам не коммитит:
весь файл применяется одной транзакцией или не применяется вовсе.

Правила записи — общие с Admin API:
  * основная категория товара — первая в списке (build_category_links);
  * значение характеристики сверяется с её типом (validate_attribute_value);
  * переводы дополняются по локалям, а не заменяются целиком;
  * связи (категории, характеристики, ступени цен) заменяются полным
    набором: сначала DELETE, затем INSERT — как в replace_* репозиториев,
    только одним запросом на все товары файла;
  * аудит — теми же действиями, что и Admin API.

Материализованный путь категорий пересчитывается по итоговому дереву:
path = цепочка id предков (инвариант модели Category).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryAttribute,
    CategoryTranslation,
    Product,
    ProductAttributeValue,
    ProductTranslation,
)
from app.modules.catalog.repository_admin import AdminCategoryRepository
from app.modules.catalog.repository_admin_products import AdminProductRepository
from app.modules.catalog.schemas_admin_products import ProductAttributeItem, ProductCategoryItem
from app.modules.catalog.service_admin import (
    AuditEntity,
    CatalogAction,
    upsert_category_translations,
)
from app.modules.catalog.service_admin_products import (
    PRODUCT_ENTITY,
    ProductAuditAction,
    build_category_links,
    upsert_product_translations,
    validate_attribute_value,
)
from app.modules.imports.audit import IMPORT_ACTOR, SYNC_SOURCE
from app.modules.imports.snapshot import CatalogSnapshot
from app.modules.imports.validator import CategoryPlan, ImportPlan, ProductPlan
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceTier
from app.modules.pricing.repository_admin import AdminPricingRepository
from app.modules.pricing.service_admin import PRICING_ENTITY, PricingAuditAction, tier_to_dict


class CatalogImportApplier:
    def __init__(
        self,
        session: AsyncSession,
        snapshot: CatalogSnapshot,
        plan: ImportPlan,
        *,
        actor_id: int,
        job_reference: str,
    ) -> None:
        self.session = session
        self.snapshot = snapshot
        self.plan = plan
        self.actor_id = actor_id
        self.job_reference = job_reference
        self.audit = AuditService(session)
        self.product_repository = AdminProductRepository(session)
        self.category_repository = AdminCategoryRepository(session)
        self.pricing_repository = AdminPricingRepository(session)

        self.attributes: dict[str, Attribute] = dict(snapshot.attributes)
        self.options: dict[tuple[str, str], AttributeOption] = {
            (attribute.code, option.slug): option
            for attribute in snapshot.attributes.values()
            for option in attribute.options
        }
        self.categories: dict[str, Category] = dict(snapshot.categories)

    async def apply(self) -> None:
        await self._attributes()
        await self._options()
        await self._categories()
        await self._category_links()
        await self._products()

    def _record(
        self, action: str, entity_type: str, entity_id: int, changes: dict[str, Any]
    ) -> None:
        self.audit.record(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=self.actor_id,
            actor=IMPORT_ACTOR,
            changes={**changes, "import_job": self.job_reference},
        )

    # ------------------------------------------------------- характеристики
    async def _attributes(self) -> None:
        created: list[Attribute] = []
        updated: list[tuple[Attribute, dict[str, Any]]] = []
        for plan in self.plan.attributes:
            if plan.existing is None:
                attribute = Attribute(
                    code=plan.code,
                    value_type=plan.value_type.value,
                    unit=plan.unit,
                    is_filterable=plan.is_filterable,
                    is_visible=plan.is_visible,
                    is_active=plan.is_active,
                    sort_order=plan.sort_order,
                    name_i18n=dict(plan.names),
                )
                self.session.add(attribute)
                self.attributes[plan.code] = attribute
                created.append(attribute)
            elif plan.changes:
                attribute = plan.existing
                for name in ("unit", "is_filterable", "is_visible", "is_active", "sort_order"):
                    setattr(attribute, name, getattr(plan, name))
                # Как в Admin API: названия дополняются по локалям.
                attribute.name_i18n = {**(attribute.name_i18n or {}), **plan.names}
                updated.append((attribute, plan.changes))
        if not created and not updated:
            return
        await self.session.flush()
        for attribute in created:
            self._record(
                CatalogAction.ATTRIBUTE_CREATED,
                AuditEntity.ATTRIBUTE,
                attribute.id,
                {"code": {"old": None, "new": attribute.code}},
            )
        for attribute, changes in updated:
            self._record(
                CatalogAction.ATTRIBUTE_UPDATED, AuditEntity.ATTRIBUTE, attribute.id, changes
            )

    async def _options(self) -> None:
        created: list[AttributeOption] = []
        updated: list[tuple[AttributeOption, dict[str, Any]]] = []
        for plan in self.plan.options:
            if plan.existing is None:
                option = AttributeOption(
                    attribute_id=self.attributes[plan.attribute_code].id,
                    slug=plan.slug,
                    sort_order=plan.sort_order,
                    value_i18n=dict(plan.values),
                )
                self.session.add(option)
                self.options[(plan.attribute_code, plan.slug)] = option
                created.append(option)
            elif plan.changes:
                option = plan.existing
                option.sort_order = plan.sort_order
                option.value_i18n = {**(option.value_i18n or {}), **plan.values}
                updated.append((option, plan.changes))
        if not created and not updated:
            return
        await self.session.flush()
        for option in created:
            self._record(
                CatalogAction.OPTION_CREATED,
                AuditEntity.ATTRIBUTE_OPTION,
                option.id,
                {"attribute_id": option.attribute_id, "slug": option.slug},
            )
        for option, changes in updated:
            self._record(
                CatalogAction.OPTION_UPDATED, AuditEntity.ATTRIBUTE_OPTION, option.id, changes
            )

    # ------------------------------------------------------------ категории
    async def _categories(self) -> None:
        plans = {plan.slug: plan for plan in self.plan.categories}
        created: list[Category] = []
        for plan in self._creation_order(plans):
            parent = self.categories.get(plan.parent_slug) if plan.parent_slug else None
            category = Category(
                slug=plan.slug,
                parent_id=parent.id if parent else None,
                depth=(parent.depth + 1) if parent else 0,
                sort_order=plan.sort_order,
                is_active=plan.is_active,
                external_id=plan.external_id,
                sync_source=SYNC_SOURCE,
                path="",
            )
            self.session.add(category)
            # Путь строится из id — как в AdminCategoryService.create_category.
            await self.session.flush()
            category.path = f"{parent.path}.{category.id}" if parent else str(category.id)
            for locale, texts in plan.translations.items():
                self.session.add(
                    CategoryTranslation(
                        category_id=category.id, locale=locale, **texts.model_dump()
                    )
                )
            self.categories[plan.slug] = category
            created.append(category)

        moved = False
        updated: list[tuple[Category, dict[str, Any]]] = []
        for plan in plans.values():
            if plan.existing is None or not plan.changes:
                continue
            category = plan.existing
            category.sort_order = plan.sort_order
            category.is_active = plan.is_active
            category.external_id = plan.external_id
            if "parent_slug" in plan.changes:
                parent = self.categories.get(plan.parent_slug) if plan.parent_slug else None
                category.parent_id = parent.id if parent else None
                moved = True
            if "translations" in plan.changes:
                upsert_category_translations(self.session, category, plan.translations)
            category.sync_source = SYNC_SOURCE
            updated.append((category, plan.changes))

        if moved or created:
            self._rebuild_paths()
        if created or updated:
            await self.session.flush()

        for category in created:
            self._record(
                CatalogAction.CATEGORY_CREATED,
                AuditEntity.CATEGORY,
                category.id,
                {"slug": {"old": None, "new": category.slug}},
            )
        for category, changes in updated:
            self._record(CatalogAction.CATEGORY_UPDATED, AuditEntity.CATEGORY, category.id, changes)

    @staticmethod
    def _creation_order(plans: dict[str, CategoryPlan]) -> list[CategoryPlan]:
        """Новые категории: родитель раньше потомка.

        Итеративно, а не рекурсией: длинная цепочка вложенности в файле
        не должна упираться в предел глубины рекурсии. Циклы исключены
        проверкой, поэтому на каждом шаге есть хотя бы одна готовая.
        """
        pending = {slug: plan for slug, plan in plans.items() if plan.existing is None}
        ordered: list[CategoryPlan] = []
        while pending:
            ready = sorted(
                slug for slug, plan in pending.items() if plan.parent_slug not in pending
            )
            if not ready:
                raise RuntimeError("Цикл во вложенности новых категорий")
            ordered.extend(pending.pop(slug) for slug in ready)
        return ordered

    def _rebuild_paths(self) -> None:
        """Путь и глубина всех живых категорий по итоговому дереву.

        Меняются только строки, у которых путь действительно изменился:
        перенесённые ветки и новые категории.
        """
        by_id = {category.id: category for category in self.categories.values()}
        resolved: dict[int, tuple[str, int]] = {}
        for node in by_id.values():
            chain: list[Category] = []
            current = node
            for _ in range(len(by_id) + 1):
                if current.id in resolved:
                    break
                chain.append(current)
                parent = by_id.get(current.parent_id) if current.parent_id is not None else None
                if parent is None:
                    break
                current = parent
            else:
                raise RuntimeError("Цикл во вложенности категорий")

            for item in reversed(chain):
                if item.parent_id is None:
                    resolved[item.id] = (str(item.id), 0)
                elif item.parent_id in resolved:
                    parent_path, parent_depth = resolved[item.parent_id]
                    resolved[item.id] = (f"{parent_path}.{item.id}", parent_depth + 1)
                else:
                    # Родитель вне живого дерева — такого быть не должно;
                    # путь не трогаем, чтобы не испортить его догадкой.
                    resolved[item.id] = (item.path, item.depth)

        for category in by_id.values():
            path, depth = resolved[category.id]
            if category.path != path:
                category.path = path
            if category.depth != depth:
                category.depth = depth

    async def _category_links(self) -> None:
        changed = [plan for plan in self.plan.categories if plan.links_changed]
        if not changed:
            return
        await self.category_repository.delete_attribute_links_for(
            [self.categories[plan.slug].id for plan in changed if plan.existing is not None]
        )
        for plan in changed:
            category = self.categories[plan.slug]
            for link in plan.links:
                self.session.add(
                    CategoryAttribute(
                        category_id=category.id,
                        attribute_id=self.attributes[link.attribute_code].id,
                        sort_order=link.sort_order,
                        is_required=link.is_required,
                    )
                )
        await self.session.flush()
        for plan in changed:
            self._record(
                CatalogAction.ATTRIBUTES_ASSIGNED,
                AuditEntity.CATEGORY_ATTRIBUTES,
                self.categories[plan.slug].id,
                {"attribute_ids": [self.attributes[link.attribute_code].id for link in plan.links]},
            )

    # ---------------------------------------------------------------- товары
    async def _products(self) -> None:
        plans = [plan for plan in self.plan.products if plan.action != "unchanged"]
        if not plans:
            return

        new_plans = [plan for plan in plans if plan.existing is None]
        products: dict[str, Product] = {}
        for plan in new_plans:
            product = Product(
                sku=plan.sku,
                slug=plan.slug,
                status=plan.status.value,
                is_active=plan.is_active,
                is_featured=plan.is_featured,
                unit=plan.unit,
                min_order_qty=plan.min_order_qty,
                brand=plan.brand,
                specs=dict(plan.specs),
                external_id=plan.external_id,
                pricing_type=(
                    plan.pricing_type.value if plan.pricing_changed else PricingType.FIXED.value
                ),
                sync_source=SYNC_SOURCE,
            )
            self.session.add(product)
            products[plan.sku] = product
        if new_plans:
            await self.session.flush()
            for plan in new_plans:
                product = products[plan.sku]
                for locale, texts in plan.translations.items():
                    self.session.add(
                        ProductTranslation(
                            product_id=product.id, locale=locale, **texts.model_dump()
                        )
                    )

        # Снимки «до» для аудита — пока старые ступени не удалены.
        previous_pricing = {
            plan.sku: self._pricing_snapshot(plan.existing)
            for plan in plans
            if plan.existing is not None and plan.pricing_changed
        }
        previous_specs = {
            plan.sku: dict(plan.existing.specs or {})
            for plan in plans
            if plan.existing is not None and plan.specs_changed
        }

        for plan in plans:
            if plan.existing is None:
                continue
            product = plan.existing
            products[plan.sku] = product
            self._apply_fields(product, plan)
            product.sync_source = SYNC_SOURCE

        await self._replace_relations(plans, products)

        for plan in plans:
            self._audit_product(
                plan,
                products[plan.sku],
                previous_pricing.get(plan.sku),
                previous_specs.get(plan.sku),
            )

    def _apply_fields(self, product: Product, plan: ProductPlan) -> None:
        for name in ("slug", "is_active", "is_featured", "unit", "brand", "external_id"):
            if name in plan.field_changes:
                setattr(product, name, getattr(plan, name))
        if "status" in plan.field_changes:
            product.status = plan.status.value
        if "min_order_qty" in plan.field_changes:
            product.min_order_qty = plan.min_order_qty
        if "translations" in plan.field_changes:
            upsert_product_translations(self.session, product, plan.translations)
        if plan.specs_changed:
            product.specs = dict(plan.specs)

    async def _replace_relations(
        self, plans: list[ProductPlan], products: dict[str, Product]
    ) -> None:
        existing_ids = {
            name: [
                plan.existing.id
                for plan in plans
                if plan.existing is not None and getattr(plan, f"{name}_changed")
            ]
            for name in ("categories", "attributes", "pricing")
        }
        # Сначала все DELETE, потом все INSERT: иначе новые строки упрутся
        # в уникальный индекс или EXCLUDE-ограничение старых.
        await self.product_repository.delete_categories_for(existing_ids["categories"])
        await self.product_repository.delete_attribute_values_for(existing_ids["attributes"])
        price_list = self.snapshot.price_list
        if existing_ids["pricing"]:
            assert price_list is not None
            await self.pricing_repository.delete_tiers_for(existing_ids["pricing"], price_list.id)
        await self.session.flush()

        options_by_id = {option.id: option for option in self.options.values()}
        for plan in plans:
            product = products[plan.sku]
            if plan.existing is not None:
                # Коллекции загружены снимком и после DELETE устарели.
                stale = [
                    name
                    for name, flag in (
                        ("categories", plan.categories_changed),
                        ("attribute_values", plan.attributes_changed),
                    )
                    if flag
                ]
                if stale:
                    self.session.expire(product, stale)

            if plan.categories_changed:
                items = [
                    ProductCategoryItem(
                        category_id=self.categories[slug].id,
                        is_primary=index == 0,
                        sort_order=index,
                    )
                    for index, slug in enumerate(plan.category_slugs)
                ]
                self.session.add_all(build_category_links(product.id, items))

            if plan.attributes_changed:
                for value in plan.attributes:
                    attribute = self.attributes[value.attribute_code]
                    option = (
                        self.options[(value.attribute_code, value.option_slug)]
                        if value.option_slug is not None
                        else None
                    )
                    item = ProductAttributeItem(
                        attribute_id=attribute.id,
                        value_string=value.value_string,
                        value_numeric=value.value_numeric,
                        value_bool=value.value_bool,
                        option_id=option.id if option is not None else None,
                    )
                    # Последний рубеж — то же правило, что в Admin API.
                    validate_attribute_value(attribute, item, options_by_id)
                    self.session.add(
                        ProductAttributeValue(
                            product_id=product.id,
                            attribute_id=attribute.id,
                            value_string=item.value_string,
                            value_numeric=item.value_numeric,
                            value_bool=item.value_bool,
                            option_id=item.option_id,
                        )
                    )

            if plan.pricing_changed:
                assert price_list is not None
                product.pricing_type = plan.pricing_type.value
                self.session.add_all(
                    PriceTier(
                        product_id=product.id,
                        price_list_id=price_list.id,
                        min_qty=tier.min_qty,
                        max_qty=tier.max_qty,
                        price=tier.price,
                        sync_source=SYNC_SOURCE,
                    )
                    for tier in plan.tiers
                )
        await self.session.flush()

    def _pricing_snapshot(self, product: Product) -> dict[str, Any]:
        return {
            "pricing_type": product.pricing_type,
            "tiers": [
                tier_to_dict(tier.min_qty, tier.max_qty, tier.price)
                for tier in self.snapshot.tiers.get(product.id, [])
            ],
        }

    def _audit_product(
        self,
        plan: ProductPlan,
        product: Product,
        previous_pricing: dict[str, Any] | None,
        previous_specs: dict[str, Any] | None,
    ) -> None:
        if plan.existing is None:
            self._record(
                ProductAuditAction.CREATED,
                PRODUCT_ENTITY,
                product.id,
                {"sku": {"old": None, "new": product.sku}},
            )
        else:
            changes = dict(plan.field_changes)
            if plan.specs_changed:
                changes["specs"] = {"old": previous_specs, "new": plan.specs}
            if changes:
                self._record(ProductAuditAction.UPDATED, PRODUCT_ENTITY, product.id, changes)
            if plan.categories_changed:
                self._record(
                    ProductAuditAction.CATEGORIES_REPLACED,
                    PRODUCT_ENTITY,
                    product.id,
                    {"category_ids": [self.categories[slug].id for slug in plan.category_slugs]},
                )
            if plan.attributes_changed:
                self._record(
                    ProductAuditAction.ATTRIBUTES_REPLACED,
                    PRODUCT_ENTITY,
                    product.id,
                    {
                        "attribute_ids": sorted(
                            {self.attributes[value.attribute_code].id for value in plan.attributes}
                        )
                    },
                )
        if plan.pricing_changed:
            self._record(
                PricingAuditAction.UPDATED,
                PRICING_ENTITY,
                product.id,
                {
                    "old": previous_pricing
                    or {"pricing_type": PricingType.FIXED.value, "tiers": []},
                    "new": {
                        "pricing_type": plan.pricing_type.value,
                        "tiers": [
                            tier_to_dict(tier.min_qty, tier.max_qty, tier.price)
                            for tier in plan.tiers
                        ],
                    },
                },
            )
