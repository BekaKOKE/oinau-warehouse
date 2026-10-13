"""Фото, схемы и остатки пакетного импорта: план и применение.

Правила для колонок «Фото» и «Схема» (подробно —
docs/api-catalog-import-export.md):

* пустая ячейка — фото (схемы) товара не меняются;
* заполненная ячейка — полный набор фото (схем) товара в указанном
  порядке; первое фото — обложка. Привязки этого вида, которых нет
  в списке, снимаются; сами файлы остаются в медиатеке;
* файл, уже привязанный к товару, повторно не загружается: совпадение
  по SHA-256 или (если файла нет в архиве) по имени привязанного файла.
  Так при повторном импорте можно не класть в архив старые фото;
* файл с тем же содержимым, что уже есть в медиатеке, не загружается
  второй раз — привязывается существующий. Один файл, указанный у
  нескольких товаров, загружается один раз;
* тот же файл с другим содержимым (новая редакция схемы) — новый файл
  медиатеки, старая привязка снимается.

Схема — отдельная роль привязки (ImageKind.SCHEME), в галерею фото
не попадает. Остатки пишутся на склад по умолчанию (первый активный)
с `sync_source=excel`, как ручная правка из админки.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.modules.audit.service import AuditService
from app.modules.imports.audit import IMPORT_ACTOR
from app.modules.imports.bundle_archive import BundleArchive, BundleFile
from app.modules.imports.bundle_files import FileCheck
from app.modules.imports.bundle_format import PHOTOS, PHOTOS_DIR, SCHEMES, SCHEMES_DIR
from app.modules.imports.issues import IssueCode, IssueCollector
from app.modules.imports.validator import ProductPlan
from app.modules.imports.xlsx_format import Sheet
from app.modules.inventory.enums import StockSource
from app.modules.inventory.models import Stock, Warehouse
from app.modules.inventory.service_admin import STOCK_ENTITY, InventoryAuditAction
from app.modules.media.audit import MEDIA_ENTITY, PRODUCT_ENTITY, MediaAuditAction
from app.modules.media.enums import ImageKind, MediaStatus
from app.modules.media.models import MediaFile, ProductImage
from app.modules.media.schemas_admin import MAX_PRODUCT_IMAGES, sanitize_filename

ROLE_KINDS: dict[str, ImageKind] = {PHOTOS_DIR: ImageKind.PHOTO, SCHEMES_DIR: ImageKind.SCHEME}
ROLE_COLUMNS: dict[str, str] = {PHOTOS_DIR: PHOTOS, SCHEMES_DIR: SCHEMES}
ROLE_LABELS: dict[str, str] = {PHOTOS_DIR: "фото", SCHEMES_DIR: "схема"}
QUANTITY_EXPONENT = Decimal("0.001")
# Сколько неиспользованных файлов перечислять поимённо.
MAX_LISTED_FILES = 50


# ================================================================= контекст
@dataclass
class BundleContext:
    """Состояние базы, нужное плану: галереи, дубликаты по хешу, склад."""

    images: dict[int, list[ProductImage]] = field(default_factory=dict)
    media_by_checksum: dict[str, MediaFile] = field(default_factory=dict)
    warehouse: Warehouse | None = None
    stocks: dict[int, Stock] = field(default_factory=dict)


async def load_context(
    session: AsyncSession, product_ids: list[int], checksums: list[str]
) -> BundleContext:
    """Фиксированное число запросов независимо от размера файла."""
    context = BundleContext()
    if product_ids:
        links = (
            (
                await session.execute(
                    select(ProductImage)
                    .where(ProductImage.product_id.in_(product_ids))
                    .options(joinedload(ProductImage.media_file))
                    .order_by(ProductImage.product_id, ProductImage.sort_order, ProductImage.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            context.images.setdefault(link.product_id, []).append(link)

    if checksums:
        media = (
            (
                await session.execute(
                    select(MediaFile)
                    .where(
                        MediaFile.checksum.in_(sorted(set(checksums))),
                        MediaFile.status.in_(
                            [MediaStatus.READY.value, MediaStatus.PROCESSING.value]
                        ),
                    )
                    # Готовый файл предпочтительнее обрабатываемого,
                    # старый — нового: так выбор детерминирован.
                    .order_by(MediaFile.status.desc(), MediaFile.id)
                )
            )
            .scalars()
            .all()
        )
        for item in media:
            if item.checksum is not None:
                context.media_by_checksum.setdefault(item.checksum, item)

    context.warehouse = (
        (
            await session.execute(
                select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.id)
            )
        )
        .scalars()
        .first()
    )
    if context.warehouse is not None and product_ids:
        stocks = (
            (
                await session.execute(
                    select(Stock)
                    .where(
                        Stock.product_id.in_(product_ids),
                        Stock.warehouse_id == context.warehouse.id,
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        context.stocks = {stock.product_id: stock for stock in stocks}
    return context


# ===================================================================== план
@dataclass
class MediaTarget:
    """Одна позиция итогового набора: существующая привязка, существующий
    файл медиатеки или новый файл из архива."""

    reference: str
    link: ProductImage | None = None
    media: MediaFile | None = None
    file_path: str | None = None

    @property
    def identity(self) -> tuple[str, Any]:
        if self.link is not None:
            return ("media", self.link.media_file_id)
        if self.media is not None:
            return ("media", self.media.id)
        return ("file", self.file_path)


@dataclass
class ProductMediaPlan:
    photos: list[MediaTarget] | None = None
    schemes: list[MediaTarget] | None = None
    detach: list[ProductImage] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


@dataclass
class StockPlan:
    quantity: Decimal
    reserved: Decimal
    existing: Stock | None


@dataclass
class BundlePlan:
    media: dict[str, ProductMediaPlan] = field(default_factory=dict)
    # Файлы архива, для которых создаётся новая запись медиатеки.
    new_files: dict[str, FileCheck] = field(default_factory=dict)
    stock: dict[str, StockPlan] = field(default_factory=dict)
    warehouse: Warehouse | None = None
    stats: dict[str, Any] = field(default_factory=dict)


def referenced_files(archive: BundleArchive, products: list[ProductPlan]) -> dict[str, BundleFile]:
    """Файлы архива, на которые однозначно ссылается книга, — их проверяют."""
    found: dict[str, BundleFile] = {}
    for plan in products:
        for folder, references in ((PHOTOS_DIR, plan.photos), (SCHEMES_DIR, plan.schemes)):
            for reference in references or []:
                matches = archive.lookup(folder, reference)
                if len(matches) == 1:
                    found[matches[0].path] = matches[0]
    return found


class BundlePlanner:
    def __init__(
        self,
        products: list[ProductPlan],
        archive: BundleArchive,
        checks: dict[str, FileCheck],
        context: BundleContext,
        *,
        errors: IssueCollector,
        warnings: IssueCollector,
        labels: dict[str, str],
    ) -> None:
        self.products = products
        self.archive = archive
        self.checks = checks
        self.context = context
        self.errors = errors
        self.warnings = warnings
        self.labels = labels
        self.plan = BundlePlan(warehouse=context.warehouse)
        self._used_paths: set[str] = set()
        self._warehouse_reported = False

    def build(self) -> BundlePlan:
        stats: dict[str, Any] = {
            "photos": {"total": 0, "added": 0, "removed": 0, "uploaded": 0, "reused": 0},
            "schemes": {"total": 0, "added": 0, "removed": 0, "uploaded": 0, "reused": 0},
            "stock_updated": 0,
            "files_in_archive": 0,
            "files_unused": 0,
        }
        for product in self.products:
            self._plan_media(product, stats)
            self._plan_stock(product, stats)

        for folder, key in ((PHOTOS_DIR, "photos"), (SCHEMES_DIR, "schemes")):
            stats[key]["uploaded"] = sum(
                1 for check in self.plan.new_files.values() if check.file.folder == folder
            )
        self._report_unused(stats)
        self.plan.stats = stats
        return self.plan

    # ------------------------------------------------------------ фото, схемы
    def _plan_media(self, product: ProductPlan, stats: dict[str, Any]) -> None:
        if product.photos is None and product.schemes is None:
            return
        links = (
            self.context.images.get(product.existing.id, []) if product.existing is not None else []
        )
        media_plan = ProductMediaPlan()
        failed = False
        for folder, references in ((PHOTOS_DIR, product.photos), (SCHEMES_DIR, product.schemes)):
            if references is None:
                continue
            targets = self._targets(product, folder, references, links)
            if targets is None:
                failed = True
                continue
            setattr(media_plan, "photos" if folder == PHOTOS_DIR else "schemes", targets)

        if failed:
            return
        if not self._check_kind_conflicts(product, media_plan):
            return

        kept_ids = {
            target.link.id
            for targets in (media_plan.photos or [], media_plan.schemes or [])
            for target in targets
            if target.link is not None
        }
        for folder, targets in ((PHOTOS_DIR, media_plan.photos), (SCHEMES_DIR, media_plan.schemes)):
            if targets is None:
                continue
            kind = ROLE_KINDS[folder]
            current = [link for link in links if link.kind == kind.value]
            detach = [link for link in current if link.id not in kept_ids]
            media_plan.detach.extend(detach)
            added = sum(1 for target in targets if target.link is None)
            key = "photos" if folder == PHOTOS_DIR else "schemes"
            stats[key]["total"] += len(targets)
            stats[key]["added"] += added
            stats[key]["removed"] += len(detach)
            stats[key]["reused"] += sum(1 for target in targets if target.media is not None)
            order_changed = [link.id for link in current] != [
                target.link.id if target.link is not None else None for target in targets
            ]
            main_changed = (
                kind is ImageKind.PHOTO
                and bool(targets)
                and targets[0].link is not None
                and not targets[0].link.is_main
            )
            if added or detach or order_changed or main_changed:
                media_plan.changed.append(key)

        remaining = (
            len(links)
            - len(media_plan.detach)
            + sum(
                1
                for targets in (media_plan.photos or [], media_plan.schemes or [])
                for target in targets
                if target.link is None
            )
        )
        if remaining > MAX_PRODUCT_IMAGES:
            self._error(
                product,
                PHOTOS_DIR,
                IssueCode.IMAGE_LIMIT,
                f"Артикул {product.sku}: у товара было бы {remaining} файлов — больше "
                f"{MAX_PRODUCT_IMAGES}",
            )
            return

        for targets in (media_plan.photos or [], media_plan.schemes or []):
            for target in targets:
                if target.file_path is not None:
                    self.plan.new_files[target.file_path] = self.checks[target.file_path]
        if media_plan.changed:
            product.extra_changes.extend(media_plan.changed)
            self.plan.media[product.sku] = media_plan

    def _targets(
        self,
        product: ProductPlan,
        folder: str,
        references: list[str],
        links: list[ProductImage],
    ) -> list[MediaTarget] | None:
        kind = ROLE_KINDS[folder]
        kind_links = [link for link in links if link.kind == kind.value]
        targets: list[MediaTarget] = []
        seen: set[tuple[str, Any]] = set()
        used_links: set[int] = set()
        ok = True
        for reference in references:
            target = self._resolve(product, folder, reference, links, kind_links, used_links)
            if target is None:
                ok = False
                continue
            if target.identity in seen:
                self._warning(
                    product,
                    folder,
                    IssueCode.FILE_DUPLICATE,
                    f"Артикул {product.sku}: файл «{reference}» указан повторно — "
                    "привязывается один раз",
                )
                continue
            seen.add(target.identity)
            if target.link is not None:
                used_links.add(target.link.id)
            targets.append(target)
        return targets if ok else None

    def _resolve(
        self,
        product: ProductPlan,
        folder: str,
        reference: str,
        links: list[ProductImage],
        kind_links: list[ProductImage],
        used_links: set[int],
    ) -> MediaTarget | None:
        matches = self.archive.lookup(folder, reference)
        if len(matches) > 1:
            self._error(
                product,
                folder,
                IssueCode.FILE_AMBIGUOUS,
                f"Артикул {product.sku}: имени «{reference}» соответствует несколько файлов: "
                + ", ".join(item.path for item in matches),
            )
            return None

        if len(matches) == 1:
            item = matches[0]
            self._used_paths.add(item.path)
            check = self.checks.get(item.path)
            if check is None or not check.ok:
                self._error(
                    product,
                    folder,
                    check.code if check is not None and check.code else IssueCode.FILE_UNSUPPORTED,
                    f"Артикул {product.sku}: "
                    + (check.message if check is not None and check.message else item.path),
                )
                return None
            same = next(
                (
                    link
                    for link in kind_links
                    if link.id not in used_links and link.media_file.checksum == check.sha256
                ),
                None,
            )
            if same is not None:
                return MediaTarget(reference, link=same)
            assert check.sha256 is not None
            media = self.context.media_by_checksum.get(check.sha256)
            if media is not None and media.mime_type == check.mime:
                other = next((link for link in links if link.media_file_id == media.id), None)
                if other is not None:
                    self._error(
                        product,
                        folder,
                        IssueCode.FILE_KIND_CONFLICT,
                        f"Артикул {product.sku}: файл {item.path} уже привязан к товару "
                        f"в другой роли ({other.kind})",
                    )
                    return None
                return MediaTarget(reference, media=media)
            return MediaTarget(reference, file_path=item.path)

        # Файла нет в архиве — допустимо, если он уже привязан к товару
        # (повторный импорт без старых фото в архиве).
        name = PurePosixPath(reference.replace("\\", "/")).name.casefold()
        kept = next(
            (
                link
                for link in kind_links
                if link.id not in used_links
                and (link.media_file.original_filename or "").casefold() == name
            ),
            None,
        )
        if kept is not None:
            return MediaTarget(reference, link=kept)
        self._error(
            product,
            folder,
            IssueCode.FILE_NOT_FOUND,
            f"Артикул {product.sku}: не найден файл {folder}/{reference.strip()}",
        )
        return None

    def _check_kind_conflicts(self, product: ProductPlan, media_plan: ProductMediaPlan) -> bool:
        photos = {target.identity for target in media_plan.photos or []}
        schemes = {target.identity for target in media_plan.schemes or []}
        if photos & schemes:
            self._error(
                product,
                SCHEMES_DIR,
                IssueCode.FILE_KIND_CONFLICT,
                f"Артикул {product.sku}: один и тот же файл указан и как фото, и как схема",
            )
            return False
        return True

    # ----------------------------------------------------------------- склад
    def _plan_stock(self, product: ProductPlan, stats: dict[str, Any]) -> None:
        if product.stock is None and product.reserved is None:
            return
        column = "stock" if product.stock is not None else "reserved"
        if self.context.warehouse is None:
            if not self._warehouse_reported:
                self._warehouse_reported = True
                self.errors.add(
                    sheet=Sheet.PRODUCTS,
                    row=product.row,
                    column=self._label(column),
                    code=IssueCode.WAREHOUSE_MISSING,
                    message="Нет активного склада: остатки импортировать некуда",
                )
            return
        existing = (
            self.context.stocks.get(product.existing.id) if product.existing is not None else None
        )
        quantity = (
            product.stock
            if product.stock is not None
            else (existing.quantity if existing is not None else None)
        )
        if quantity is None:
            self._stock_error(
                product, "reserved", "Резерв указан без остатка — заполните «Остаток»"
            )
            return
        reserved = (
            product.reserved
            if product.reserved is not None
            else (existing.reserved if existing is not None else Decimal(0))
        )
        if reserved > quantity:
            self._stock_error(
                product,
                column,
                f"Остаток {_qty(quantity)} меньше резерва {_qty(reserved)}",
            )
            return
        if (
            existing is not None
            and _qty(existing.quantity) == _qty(quantity)
            and _qty(existing.reserved) == _qty(reserved)
        ):
            return
        self.plan.stock[product.sku] = StockPlan(
            quantity=quantity, reserved=reserved, existing=existing
        )
        product.extra_changes.append("stock")
        stats["stock_updated"] += 1

    def _stock_error(self, product: ProductPlan, column: str, message: str) -> None:
        self.errors.add(
            sheet=Sheet.PRODUCTS,
            row=product.row,
            column=self._label(column),
            code=IssueCode.STOCK_INVALID,
            message=f"Артикул {product.sku}: {message}",
        )

    # ---------------------------------------------------------------- отчёт
    def _report_unused(self, stats: dict[str, Any]) -> None:
        all_files = [
            *self.archive.all_files(PHOTOS_DIR),
            *self.archive.all_files(SCHEMES_DIR),
        ]
        stats["files_in_archive"] = len(all_files)
        unused = sorted(item.path for item in all_files if item.path not in self._used_paths)
        stats["files_unused"] = len(unused)
        for path in unused[:MAX_LISTED_FILES]:
            self.warnings.add(
                sheet=None,
                row=None,
                column=None,
                code=IssueCode.FILE_UNUSED,
                message=f"Файл {path} не указан ни у одного товара — не загружается",
            )
        if len(unused) > MAX_LISTED_FILES:
            self.warnings.add(
                sheet=None,
                row=None,
                column=None,
                code=IssueCode.FILE_UNUSED,
                message=f"И ещё {len(unused) - MAX_LISTED_FILES} неиспользованных файлов",
            )
        for path in self.archive.ignored[:MAX_LISTED_FILES]:
            self.warnings.add(
                sheet=None,
                row=None,
                column=None,
                code=IssueCode.FILE_IGNORED,
                message=f"Файл {path} лежит вне папок photos и schemes — пропущен",
            )

    def _label(self, column: str) -> str:
        return self.labels.get(column, column)

    def _error(self, product: ProductPlan, folder: str, code: str, message: str) -> None:
        self.errors.add(
            sheet=Sheet.PRODUCTS,
            row=product.row,
            column=self._label(ROLE_COLUMNS[folder]),
            code=code,
            message=message,
        )

    def _warning(self, product: ProductPlan, folder: str, code: str, message: str) -> None:
        self.warnings.add(
            sheet=Sheet.PRODUCTS,
            row=product.row,
            column=self._label(ROLE_COLUMNS[folder]),
            code=code,
            message=message,
        )


def _qty(value: Decimal) -> str:
    return str(value.quantize(QUANTITY_EXPONENT))


# =============================================================== применение
@dataclass(frozen=True)
class UploadedFile:
    media_uuid: uuid.UUID
    storage_key: str


class BundleApplier:
    """Записывает фото, схемы и остатки. Внутри транзакции импорта, не коммитит."""

    def __init__(
        self,
        session: AsyncSession,
        plan: BundlePlan,
        context: BundleContext,
        *,
        uploaded: dict[str, UploadedFile],
        actor_id: int,
        job_reference: str,
    ) -> None:
        self.session = session
        self.plan = plan
        self.context = context
        self.uploaded = uploaded
        self.actor_id = actor_id
        self.job_reference = job_reference
        self.audit = AuditService(session)
        self.created_media: dict[str, MediaFile] = {}

    async def apply(self, product_ids: dict[str, int]) -> list[int]:
        """Возвращает id новых файлов медиатеки — их обработает воркер."""
        await self._create_media()
        for sku, media_plan in self.plan.media.items():
            await self._apply_media(product_ids[sku], media_plan)
        await self._apply_stock(product_ids)
        return [media.id for media in self.created_media.values()]

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

    async def _create_media(self) -> None:
        for path, check in self.plan.new_files.items():
            uploaded = self.uploaded[path]
            assert check.mime is not None and check.sha256 is not None
            media = MediaFile(
                uuid=uploaded.media_uuid,
                storage_key=uploaded.storage_key,
                bucket=settings.S3_BUCKET,
                mime_type=check.mime,
                size_bytes=check.file.size,
                original_filename=sanitize_filename(check.file.name),
                checksum=check.sha256,
                # Объект уже в хранилище и проверен: дальше — воркер.
                status=MediaStatus.PROCESSING.value,
                uploaded_by_id=self.actor_id,
            )
            self.session.add(media)
            self.created_media[path] = media
        if not self.created_media:
            return
        await self.session.flush()
        for media in self.created_media.values():
            self._record(
                MediaAuditAction.UPLOAD_COMPLETED,
                MEDIA_ENTITY,
                media.id,
                {
                    "status": {"old": None, "new": media.status},
                    "content_type": media.mime_type,
                    "size_bytes": media.size_bytes,
                },
            )

    def _link_for(self, product_id: int, target: MediaTarget, kind: ImageKind) -> ProductImage:
        if target.link is not None:
            return target.link
        media = (
            target.media if target.media is not None else self.created_media[str(target.file_path)]
        )
        link = ProductImage(
            product_id=product_id,
            media_file_id=media.id,
            kind=kind.value,
            alt_i18n={},
            sort_order=0,
            is_main=False,
        )
        self.session.add(link)
        return link

    async def _apply_media(self, product_id: int, media_plan: ProductMediaPlan) -> None:
        links = self.context.images.get(product_id, [])
        detached = {link.id for link in media_plan.detach}
        for link in media_plan.detach:
            await self.session.delete(link)
        remaining = [link for link in links if link.id not in detached]
        # Обложка снимается через ORM, а не UPDATE-запросом: иначе объект
        # в сессии «помнил» бы старое значение и не записал бы новое.
        if media_plan.photos is not None:
            for link in remaining:
                link.is_main = False
        await self.session.flush()

        def ordered(kind: ImageKind, targets: list[MediaTarget] | None) -> list[ProductImage]:
            if targets is None:
                return [link for link in remaining if link.kind == kind.value]
            return [self._link_for(product_id, target, kind) for target in targets]

        photos = ordered(ImageKind.PHOTO, media_plan.photos)
        schemes = ordered(ImageKind.SCHEME, media_plan.schemes)
        others = [
            link
            for link in remaining
            if link.kind not in (ImageKind.PHOTO.value, ImageKind.SCHEME.value)
        ]
        for position, link in enumerate([*photos, *others, *schemes]):
            link.sort_order = position
        await self.session.flush()
        if media_plan.photos is not None and photos:
            photos[0].is_main = True
            await self.session.flush()

        new_ids = {link.id for link in [*photos, *schemes]} - {link.id for link in links}
        for link in [*photos, *schemes]:
            if link.id in new_ids:
                self._record(
                    MediaAuditAction.IMAGE_ATTACHED,
                    PRODUCT_ENTITY,
                    product_id,
                    {"image_id": link.id, "kind": link.kind, "is_main": link.is_main},
                )
        for image_id in sorted(detached):
            self._record(
                MediaAuditAction.IMAGE_DETACHED, PRODUCT_ENTITY, product_id, {"image_id": image_id}
            )
        self._record(
            MediaAuditAction.IMAGES_REORDERED,
            PRODUCT_ENTITY,
            product_id,
            {
                "order": {
                    "old": [link.id for link in links],
                    "new": [link.id for link in [*photos, *others, *schemes]],
                }
            },
        )

    async def _apply_stock(self, product_ids: dict[str, int]) -> None:
        warehouse = self.plan.warehouse
        if not self.plan.stock:
            return
        assert warehouse is not None
        now = datetime.now(UTC)
        for sku, stock_plan in self.plan.stock.items():
            product_id = product_ids[sku]
            entry = stock_plan.existing
            old = (
                {"quantity": _qty(entry.quantity), "reserved": _qty(entry.reserved)}
                if entry is not None
                else None
            )
            if entry is None:
                entry = Stock(
                    product_id=product_id,
                    warehouse_id=warehouse.id,
                    quantity=stock_plan.quantity,
                    reserved=stock_plan.reserved,
                    sync_source=StockSource.EXCEL.value,
                )
                self.session.add(entry)
            else:
                entry.quantity = stock_plan.quantity
                entry.reserved = stock_plan.reserved
                entry.sync_source = StockSource.EXCEL.value
                entry.updated_at = now
            self._record(
                InventoryAuditAction.STOCK_UPDATED,
                STOCK_ENTITY,
                product_id,
                {
                    warehouse.code: {
                        "old": old,
                        "new": {
                            "quantity": _qty(stock_plan.quantity),
                            "reserved": _qty(stock_plan.reserved),
                        },
                    }
                },
            )
        await self.session.flush()


__all__ = [
    "BundleApplier",
    "BundleContext",
    "BundlePlan",
    "BundlePlanner",
    "UploadedFile",
    "load_context",
    "referenced_files",
]
