"""Бизнес-правила Admin API медиатеки и изображений товаров.

Поток загрузки (docs/architecture.md, раздел 9):

    1. upload-intent  -> запись PENDING + presigned PUT (файл идёт мимо API)
    2. PUT в хранилище (браузер напрямую)
    3. complete       -> HEAD: объект есть, размер в пределах; сигнатура
                         совпадает с типом -> PROCESSING, задача в очередь
    4. воркер         -> декодирование, варианты WebP -> READY | FAILED

Бинарные данные через FastAPI не проходят ни на одном шаге.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.logging import get_logger
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.infrastructure.storage.base import ObjectStorage
from app.modules.audit.service import AuditService
from app.modules.catalog.models import Product
from app.modules.catalog.mutability import ensure_mutable
from app.modules.media.audit import MEDIA_ENTITY, PRODUCT_ENTITY, MediaAuditAction
from app.modules.media.documents import (
    DOCUMENT_EXTENSIONS,
    DOCUMENT_SNIFF_BYTES,
    is_document,
    sniff_document_mime,
)
from app.modules.media.enums import ImageKind, MediaFailureReason, MediaPurpose, MediaStatus
from app.modules.media.exceptions import (
    DocumentKindError,
    ImageAlreadyAttachedError,
    ImageOrderMismatchError,
    MediaFailedError,
    MediaInUseError,
    MediaNotFoundError,
    MediaUploadMissingError,
    MediaUploadRejectedError,
    ProductImageLimitError,
    ProductImageNotFoundError,
)
from app.modules.media.images import MIME_EXTENSIONS, SNIFF_BYTES, sniff_mime
from app.modules.media.integrity import MEDIA_CONSTRAINT_ERRORS
from app.modules.media.models import MediaFile, ProductImage
from app.modules.media.queue import MediaQueue
from app.modules.media.repository_admin import (
    AdminMediaRepository,
    AdminProductImageRepository,
    MediaAdminFilters,
)
from app.modules.media.schemas_admin import (
    MAX_PRODUCT_IMAGES,
    MediaDetail,
    MediaProductUsage,
    MediaRead,
    MediaUploadCreate,
    MediaUploadCreated,
    ProductImageCreate,
    ProductImageList,
    ProductImageRead,
    ProductImagesOrder,
    ProductImageUpdate,
    ProductMainImage,
    UploadInstructions,
)
from app.modules.media.urls import is_ready, primary_size, primary_url, variant_urls
from app.modules.users.models import User

logger = get_logger(__name__)

_KEY_PREFIXES: dict[MediaPurpose, str] = {
    MediaPurpose.PRODUCT: "products",
    MediaPurpose.CONTENT: "content",
}


def build_original_key(purpose: MediaPurpose, media_uuid: uuid.UUID, mime_type: str) -> str:
    """Ключ оригинала: `products/{uuid}/original.jpg`.

    Только UUID и расширение из проверенного MIME. Имя файла клиента,
    кириллица, пробелы и `../` в ключ не попадают в принципе. Ключ
    иммутабелен: замена изображения — новый файл с новым UUID, поэтому
    CDN может кэшировать вечно.
    """
    extension = MIME_EXTENSIONS.get(mime_type) or DOCUMENT_EXTENSIONS[mime_type]
    return f"{_KEY_PREFIXES[purpose]}/{media_uuid}/original.{extension}"


def sniff_upload_mime(head: bytes, declared: str) -> str | None:
    """Тип файла по сигнатуре — по правилам изображений или документов."""
    if is_document(declared):
        return sniff_document_mime(head)
    return sniff_mime(head)


def max_upload_bytes(mime_type: str) -> int:
    if is_document(mime_type):
        return settings.upload_max_document_size_bytes
    return settings.upload_max_size_bytes


# Роли, в которых может выступать документ: он не фотография и не
# может быть обложкой карточки — картинки у него нет.
DOCUMENT_KINDS = frozenset({ImageKind.SCHEME, ImageKind.DRAWING, ImageKind.CERTIFICATE})


def storage_keys(media: MediaFile) -> list[str]:
    """Все объекты файла в хранилище: оригинал и варианты."""
    keys = [media.storage_key]
    for data in (media.variants or {}).values():
        if isinstance(data, dict) and data.get("key"):
            keys.append(str(data["key"]))
    return keys


def media_to_read(media: MediaFile, usage_count: int = 0) -> MediaRead:
    width, height = media.width, media.height
    return MediaRead(
        uuid=media.uuid,
        status=MediaStatus(media.status),
        original_filename=media.original_filename,
        content_type=media.mime_type,
        size_bytes=media.size_bytes,
        width=width,
        height=height,
        url=primary_url(media),
        variants=variant_urls(media),
        failure_reason=media.failure_reason,
        usage_count=usage_count,
        uploaded_by_id=media.uploaded_by_id,
        created_at=media.created_at,
        updated_at=media.updated_at,
    )


class AdminMediaService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage,
        queue: MediaQueue | None = None,
    ) -> None:
        super().__init__(session)
        self.repository = AdminMediaRepository(session)
        self.audit = AuditService(session)
        self.storage = storage
        self.queue = queue

    # -------------------------------------------------------------- чтение
    async def list_media(
        self, *, filters: MediaAdminFilters, params: PageParams
    ) -> Page[MediaRead]:
        rows, total = await self.repository.list_media(filters=filters, params=params)
        return Page.create([media_to_read(media, usage) for media, usage in rows], total, params)

    async def get_media(self, media_uuid: uuid.UUID) -> MediaDetail:
        media = await self._require(media_uuid)
        usages = await self.repository.list_usages(media.id)
        sections = await self.repository.content_sections_referencing(media.uuid)
        return MediaDetail(
            **media_to_read(media, len(usages)).model_dump(),
            products=[
                MediaProductUsage(
                    product_id=usage.product_id,
                    sku=usage.sku,
                    image_id=usage.image_id,
                    is_deleted=usage.is_deleted,
                )
                for usage in usages
            ],
            content_sections=sections,
        )

    # --------------------------------------------------------- загрузка
    async def create_upload(self, payload: MediaUploadCreate, actor: User) -> MediaUploadCreated:
        media_uuid = uuid.uuid4()
        media = MediaFile(
            uuid=media_uuid,
            storage_key=build_original_key(payload.purpose, media_uuid, payload.content_type),
            bucket=settings.S3_BUCKET,
            mime_type=payload.content_type,
            # Заявленный размер; фактический запишется после HEAD.
            size_bytes=payload.size_bytes,
            original_filename=payload.filename,
            status=MediaStatus.PENDING.value,
            uploaded_by_id=actor.id,
        )
        self.session.add(media)
        await self.session.flush()

        # Подпись не требует обращения к хранилищу — это чистая
        # криптография. Ссылка выдаётся до коммита: если подпись
        # не удастся, запись не останется висеть в PENDING.
        upload = await self.storage.create_upload_url(
            media.storage_key,
            content_type=media.mime_type,
            expires_in=settings.UPLOAD_PRESIGN_TTL_SECONDS,
        )

        self.audit.record(
            action=MediaAuditAction.UPLOAD_REQUESTED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            user_id=actor.id,
            changes={
                "content_type": media.mime_type,
                "declared_size": media.size_bytes,
                "purpose": payload.purpose.value,
            },
        )
        await self.commit()
        await self.session.refresh(media)
        return MediaUploadCreated(
            media=media_to_read(media),
            upload=UploadInstructions(
                url=upload.url,
                method=upload.method,
                headers=upload.headers,
                expires_in=upload.expires_in,
            ),
        )

    async def complete_upload(self, media_uuid: uuid.UUID, actor: User) -> MediaRead:
        """Подтверждение загрузки. Идемпотентно.

        READY возвращается как есть; PROCESSING повторно ставится в очередь
        (на случай, если постановка в прошлый раз не удалась); FAILED —
        конфликт: файл отвергнут, нужна новая загрузка.
        """
        media = await self._require(media_uuid, for_update=True)

        if media.status == MediaStatus.READY.value:
            return media_to_read(media, await self.repository.count_usage(media.id))
        if media.status == MediaStatus.FAILED.value:
            raise MediaFailedError(details={"failure_reason": media.failure_reason})
        if media.status == MediaStatus.PROCESSING.value:
            # Изменений нет; коммит только снимает блокировку строки,
            # чтобы воркер мог её взять.
            await self.commit()
            await self._enqueue(media.id)
            return media_to_read(media, await self.repository.count_usage(media.id))

        stored = await self.storage.stat(media.storage_key)
        if stored is None:
            # Статус не меняется: пока ссылка жива, загрузку можно повторить.
            raise MediaUploadMissingError

        reason: MediaFailureReason | None = None
        if stored.size <= 0:
            reason = MediaFailureReason.EMPTY_FILE
        elif stored.size > max_upload_bytes(media.mime_type):
            # Presigned PUT у R2 не ограничивает размер тела, поэтому
            # предел проверяется здесь, по факту.
            reason = MediaFailureReason.SIZE_EXCEEDED
        else:
            head = await self.storage.read(
                media.storage_key, max_bytes=max(SNIFF_BYTES, DOCUMENT_SNIFF_BYTES)
            )
            if sniff_upload_mime(head, media.mime_type) != media.mime_type:
                # Заявлен image/png, а внутри что-то другое — например,
                # скрипт с переименованным расширением.
                reason = MediaFailureReason.TYPE_MISMATCH

        if reason is not None:
            await self._reject(media, reason, actor, actual_size=stored.size)

        media.size_bytes = stored.size
        media.status = MediaStatus.PROCESSING.value
        self.audit.record(
            action=MediaAuditAction.UPLOAD_COMPLETED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            user_id=actor.id,
            changes={
                "status": {"old": MediaStatus.PENDING.value, "new": media.status},
                "size_bytes": stored.size,
            },
        )
        await self.commit()
        # В очередь — только после коммита: воркер обязан увидеть PROCESSING.
        await self._enqueue(media.id)
        await self.session.refresh(media)
        return media_to_read(media)

    async def _reject(
        self, media: MediaFile, reason: MediaFailureReason, actor: User, *, actual_size: int
    ) -> None:
        media.status = MediaStatus.FAILED.value
        media.failure_reason = reason.value
        self.audit.record(
            action=MediaAuditAction.UPLOAD_REJECTED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            user_id=actor.id,
            changes={"failure_reason": reason.value, "actual_size": actual_size},
        )
        await self.commit()
        # Отвергнутый объект удаляется сразу: хранить в бакете файл,
        # который никогда не будет показан, незачем.
        await self._delete_objects([media.storage_key])
        raise MediaUploadRejectedError(details={"failure_reason": reason.value})

    async def _enqueue(self, media_id: int) -> None:
        if self.queue is None:
            return
        try:
            await self.queue.enqueue_processing(media_id)
        except Exception as exc:
            # Файл остаётся в PROCESSING; повторный complete поставит
            # задачу снова. Отказ очереди не должен превращаться в 500
            # после того, как загрузка уже подтверждена и сохранена.
            logger.warning("media_enqueue_failed", media_id=media_id, error=type(exc).__name__)

    # ------------------------------------------------------------ удаление
    @guard_unique(MEDIA_CONSTRAINT_ERRORS)
    async def delete_media(self, media_uuid: uuid.UUID, actor: User) -> None:
        """Удаление файла из медиатеки.

        Запрещено, пока файл привязан к товару (включая удалённые товары:
        их можно восстановить), стоит обложкой раздела каталога или
        упомянут в CMS. Внешние ключи product_images -> media_files и
        categories.image_media_id -> media_files (оба RESTRICT)
        страхуют от гонки.
        Объекты в хранилище удаляются после коммита: если хранилище
        недоступно, в бакете останется сирота, которого уберёт уборка,
        но в БД не останется записи без файла.
        """
        media = await self._require(media_uuid, for_update=True)

        products = await self.repository.count_usage(media.id)
        categories = await self.repository.categories_using(media.id)
        sections = await self.repository.content_sections_referencing(media.uuid)
        if products or categories or sections:
            raise MediaInUseError(
                details={
                    "products_count": products,
                    "categories": categories,
                    "content_sections": sections,
                }
            )

        keys = storage_keys(media)
        self.audit.record(
            action=MediaAuditAction.DELETED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            user_id=actor.id,
            changes={
                "uuid": str(media.uuid),
                "status": media.status,
                "original_filename": media.original_filename,
            },
        )
        await self.repository.delete(media)
        await self.commit()
        await self._delete_objects(keys)

    async def _delete_objects(self, keys: list[str]) -> None:
        try:
            await self.storage.delete(keys)
        except Exception as exc:
            logger.warning("media_storage_delete_failed", error=type(exc).__name__)

    async def _require(self, media_uuid: uuid.UUID, *, for_update: bool = False) -> MediaFile:
        media = await self.repository.get_by_uuid(media_uuid, for_update=for_update)
        if media is None:
            raise MediaNotFoundError
        return media


class AdminProductImageService(BaseService):
    """Галерея товара: привязка, подписи, порядок, главное изображение.

    Инвариант: если у товара есть изображения, ровно одно из них главное.
    Первое привязанное становится главным автоматически, при отвязке
    главного главным становится первое из оставшихся. Так витрина
    никогда не остаётся без обложки из-за забытого флажка.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminProductImageRepository(session)
        self.media = AdminMediaRepository(session)
        self.audit = AuditService(session)

    async def list_images(self, product_id: int) -> ProductImageList:
        product = await self._require_product(product_id)
        return await self._to_list(product.id)

    @guard_unique(MEDIA_CONSTRAINT_ERRORS)
    async def attach(
        self, product_id: int, payload: ProductImageCreate, actor: User
    ) -> ProductImageList:
        product = await self._require_mutable_product(product_id)
        await self.repository.lock_product(product.id)

        media = (await self.media.get_by_uuids([payload.media_uuid], for_share=True)).get(
            payload.media_uuid
        )
        if media is None:
            raise MediaNotFoundError(details={"media_uuid": str(payload.media_uuid)})
        if media.status == MediaStatus.FAILED.value:
            # PENDING/PROCESSING привязать можно — витрина покажет файл,
            # когда он станет READY. FAILED готовым не станет никогда.
            raise MediaFailedError(details={"media_uuid": str(media.uuid)})

        document = is_document(media.mime_type)
        if document and payload.kind not in DOCUMENT_KINDS:
            raise DocumentKindError(details={"kind": payload.kind.value})
        if document and payload.is_main:
            raise DocumentKindError("Документ не может быть обложкой товара")

        images = await self.repository.list_images(product.id)
        if any(image.media_file_id == media.id for image in images):
            raise ImageAlreadyAttachedError
        if len(images) >= MAX_PRODUCT_IMAGES:
            raise ProductImageLimitError(details={"max": MAX_PRODUCT_IMAGES})

        # Обложкой становится первое изображение, но не документ: у схемы
        # в PDF нет картинки для карточки.
        make_main = not document and (payload.is_main or not any(image.is_main for image in images))
        if make_main:
            await self.repository.clear_main(product.id)

        image = ProductImage(
            product_id=product.id,
            media_file_id=media.id,
            kind=payload.kind.value,
            alt_i18n=dict(payload.alt),
            sort_order=await self.repository.next_sort_order(product.id),
            is_main=make_main,
        )
        self.session.add(image)
        await self.session.flush()

        self.audit.record(
            action=MediaAuditAction.IMAGE_ATTACHED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={
                "image_id": image.id,
                "media_uuid": str(media.uuid),
                "kind": image.kind,
                "is_main": image.is_main,
            },
        )
        await self.commit()
        return await self._to_list(product.id)

    async def update(
        self, product_id: int, image_id: int, payload: ProductImageUpdate, actor: User
    ) -> ProductImageList:
        product = await self._require_mutable_product(product_id)
        await self.repository.lock_product(product.id)
        image = self._find(await self.repository.list_images(product.id), image_id)

        changes: dict[str, Any] = {}
        if (
            payload.kind is not None
            and payload.kind not in DOCUMENT_KINDS
            and is_document(image.media_file.mime_type)
        ):
            raise DocumentKindError(details={"kind": payload.kind.value})
        if payload.kind is not None and payload.kind.value != image.kind:
            changes["kind"] = {"old": image.kind, "new": payload.kind.value}
            image.kind = payload.kind.value
        if payload.alt is not None and payload.alt != (image.alt_i18n or {}):
            changes["alt"] = {"old": image.alt_i18n, "new": payload.alt}
            image.alt_i18n = dict(payload.alt)

        if changes:
            await self.session.flush()
            self.audit.record(
                action=MediaAuditAction.IMAGE_UPDATED,
                entity_type=PRODUCT_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes={"image_id": image.id, **changes},
            )
        await self.commit()
        return await self._to_list(product.id)

    async def detach(self, product_id: int, image_id: int, actor: User) -> None:
        """Отвязка. Файл остаётся в медиатеке — удаляется отдельно."""
        product = await self._require_mutable_product(product_id)
        await self.repository.lock_product(product.id)
        images = await self.repository.list_images(product.id)
        image = self._find(images, image_id)

        was_main = image.is_main
        media_uuid = str(image.media_file.uuid)
        await self.repository.delete(image)

        promoted: int | None = None
        remaining = [
            item
            for item in images
            if item.id != image.id and not is_document(item.media_file.mime_type)
        ]
        if was_main and remaining:
            remaining[0].is_main = True
            promoted = remaining[0].id
            await self.session.flush()

        self.audit.record(
            action=MediaAuditAction.IMAGE_DETACHED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={
                "image_id": image_id,
                "media_uuid": media_uuid,
                "was_main": was_main,
                "promoted_main_image_id": promoted,
            },
        )
        await self.commit()

    async def reorder(
        self, product_id: int, payload: ProductImagesOrder, actor: User
    ) -> ProductImageList:
        """Полный новый порядок.

        Частичный список не принимается: непонятно, куда деть
        неупомянутые изображения, а угадывать — значит однажды
        перемешать галерею.
        """
        product = await self._require_mutable_product(product_id)
        await self.repository.lock_product(product.id)
        images = await self.repository.list_images(product.id)

        current = [image.id for image in images]
        if set(current) != set(payload.image_ids):
            raise ImageOrderMismatchError(
                details={"expected": sorted(current), "received": sorted(payload.image_ids)}
            )

        by_id = {image.id: image for image in images}
        for position, image_id in enumerate(payload.image_ids):
            by_id[image_id].sort_order = position
        await self.session.flush()

        if current != payload.image_ids:
            self.audit.record(
                action=MediaAuditAction.IMAGES_REORDERED,
                entity_type=PRODUCT_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes={"order": {"old": current, "new": payload.image_ids}},
            )
        await self.commit()
        return await self._to_list(product.id)

    @guard_unique(MEDIA_CONSTRAINT_ERRORS)
    async def set_main(
        self, product_id: int, payload: ProductMainImage, actor: User
    ) -> ProductImageList:
        product = await self._require_mutable_product(product_id)
        await self.repository.lock_product(product.id)
        images = await self.repository.list_images(product.id)
        image = self._find(images, payload.image_id)
        if is_document(image.media_file.mime_type):
            raise DocumentKindError("Документ не может быть обложкой товара")

        previous = next((item.id for item in images if item.is_main), None)
        if previous != image.id:
            await self.repository.clear_main(product.id)
            image.is_main = True
            await self.session.flush()
            self.audit.record(
                action=MediaAuditAction.MAIN_IMAGE_CHANGED,
                entity_type=PRODUCT_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes={"main_image_id": {"old": previous, "new": image.id}},
            )
        await self.commit()
        return await self._to_list(product.id)

    # ---------------------------------------------------------- внутреннее
    async def _require_product(self, product_id: int) -> Product:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise NotFoundError("Товар не найден")
        return product

    async def _require_mutable_product(self, product_id: int) -> Product:
        """Удалённый товар только читается — правило общее для всех модулей."""
        return ensure_mutable(await self._require_product(product_id))

    def _find(self, images: list[ProductImage], image_id: int) -> ProductImage:
        image = next((item for item in images if item.id == image_id), None)
        if image is None:
            raise ProductImageNotFoundError(details={"image_id": image_id})
        return image

    async def _to_list(self, product_id: int) -> ProductImageList:
        images = await self.repository.list_images(product_id)
        return ProductImageList(
            product_id=product_id,
            items=[self._to_read(image) for image in images],
        )

    def _to_read(self, image: ProductImage) -> ProductImageRead:
        media = image.media_file
        width, height = primary_size(media)
        return ProductImageRead(
            id=image.id,
            media_uuid=media.uuid,
            kind=image.kind,
            alt=dict(image.alt_i18n or {}),
            is_main=image.is_main,
            sort_order=image.sort_order,
            status=MediaStatus(media.status),
            is_publicly_visible=is_ready(media),
            url=primary_url(media),
            variants=variant_urls(media),
            width=width,
            height=height,
            original_filename=media.original_filename,
            content_type=media.mime_type,
            size_bytes=media.size_bytes,
            created_at=image.created_at,
        )
