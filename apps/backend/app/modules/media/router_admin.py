"""Admin API медиатеки и изображений товаров.

Чтение — `catalog.read`, изменение — `catalog.write`. Выдача ссылки
на загрузку и подтверждение загрузки дополнительно требуют уже
существующего `media.upload`: у ролей сейчас одинаковый состав,
но право на запись в бакет остаётся отдельно управляемым.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import SessionDep, rate_limit, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.infrastructure.storage.base import ObjectStorage
from app.infrastructure.storage.s3 import get_object_storage
from app.modules.media.enums import MediaStatus
from app.modules.media.queue import MediaQueue, get_media_queue
from app.modules.media.repository_admin import MediaAdminFilters
from app.modules.media.schemas_admin import (
    MediaDetail,
    MediaRead,
    MediaUploadCreate,
    MediaUploadCreated,
    ProductImageCreate,
    ProductImageList,
    ProductImagesOrder,
    ProductImageUpdate,
    ProductMainImage,
)
from app.modules.media.service_admin import AdminMediaService, AdminProductImageService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE, MEDIA_UPLOAD

MediaReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
MediaWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]
MediaUploader = Annotated[User, Depends(require_permissions(CATALOG_WRITE, MEDIA_UPLOAD))]

StorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
QueueDep = Annotated[MediaQueue, Depends(get_media_queue)]

IdPath = Annotated[int, Path(ge=1)]

media_router = APIRouter(prefix="/media", tags=["admin:media"])
product_images_router = APIRouter(prefix="/products", tags=["admin:media"])


# ------------------------------------------------------------- медиатека
@media_router.get("", response_model=Page[MediaRead], summary="Медиатека")
async def list_media(
    session: SessionDep,
    storage: StorageDep,
    _: MediaReader,
    media_status: Annotated[MediaStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[MediaRead]:
    return await AdminMediaService(session, storage=storage).list_media(
        filters=MediaAdminFilters(
            status=media_status.value if media_status else None, search=search
        ),
        params=PageParams(page=page, page_size=page_size),
    )


@media_router.post(
    "/upload-intent",
    response_model=MediaUploadCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Ссылка на загрузку файла",
    dependencies=[Depends(rate_limit("media_upload", "RATE_LIMIT_MEDIA_UPLOAD"))],
)
async def create_upload(
    payload: MediaUploadCreate,
    session: SessionDep,
    storage: StorageDep,
    actor: MediaUploader,
) -> MediaUploadCreated:
    """Создаёт запись PENDING и presigned PUT. Файл загружается прямо
    в хранилище, минуя API; затем вызывается `/complete`."""
    return await AdminMediaService(session, storage=storage).create_upload(payload, actor)


@media_router.post(
    "/{media_uuid}/complete",
    response_model=MediaRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Подтвердить загрузку",
)
async def complete_upload(
    media_uuid: UUID,
    session: SessionDep,
    storage: StorageDep,
    queue: QueueDep,
    actor: MediaUploader,
) -> MediaRead:
    """Проверяет объект (наличие, размер, сигнатуру) и ставит обработку
    в очередь. Идемпотентно: повтор для READY/PROCESSING безопасен."""
    return await AdminMediaService(session, storage=storage, queue=queue).complete_upload(
        media_uuid, actor
    )


@media_router.get("/{media_uuid}", response_model=MediaDetail, summary="Файл медиатеки")
async def get_media(
    media_uuid: UUID,
    session: SessionDep,
    storage: StorageDep,
    _: MediaReader,
) -> MediaDetail:
    return await AdminMediaService(session, storage=storage).get_media(media_uuid)


@media_router.delete(
    "/{media_uuid}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить файл"
)
async def delete_media(
    media_uuid: UUID,
    session: SessionDep,
    storage: StorageDep,
    actor: MediaWriter,
) -> None:
    """409, пока файл привязан к товару или используется в CMS."""
    await AdminMediaService(session, storage=storage).delete_media(media_uuid, actor)


# ---------------------------------------------------- изображения товара
@product_images_router.get(
    "/{product_id}/images", response_model=ProductImageList, summary="Изображения товара"
)
async def list_product_images(
    product_id: IdPath,
    session: SessionDep,
    _: MediaReader,
) -> ProductImageList:
    """Все привязки, включая ещё не готовые файлы (витрина видит только READY)."""
    return await AdminProductImageService(session).list_images(product_id)


@product_images_router.post(
    "/{product_id}/images",
    response_model=ProductImageList,
    status_code=status.HTTP_201_CREATED,
    summary="Привязать изображение",
)
async def attach_product_image(
    product_id: IdPath,
    payload: ProductImageCreate,
    session: SessionDep,
    actor: MediaWriter,
) -> ProductImageList:
    return await AdminProductImageService(session).attach(product_id, payload, actor)


@product_images_router.put(
    "/{product_id}/images/order", response_model=ProductImageList, summary="Порядок изображений"
)
async def reorder_product_images(
    product_id: IdPath,
    payload: ProductImagesOrder,
    session: SessionDep,
    actor: MediaWriter,
) -> ProductImageList:
    return await AdminProductImageService(session).reorder(product_id, payload, actor)


@product_images_router.put(
    "/{product_id}/images/main", response_model=ProductImageList, summary="Главное изображение"
)
async def set_main_product_image(
    product_id: IdPath,
    payload: ProductMainImage,
    session: SessionDep,
    actor: MediaWriter,
) -> ProductImageList:
    return await AdminProductImageService(session).set_main(product_id, payload, actor)


@product_images_router.patch(
    "/{product_id}/images/{image_id}",
    response_model=ProductImageList,
    summary="Подпись и тип изображения",
)
async def update_product_image(
    product_id: IdPath,
    image_id: IdPath,
    payload: ProductImageUpdate,
    session: SessionDep,
    actor: MediaWriter,
) -> ProductImageList:
    return await AdminProductImageService(session).update(product_id, image_id, payload, actor)


@product_images_router.delete(
    "/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отвязать изображение",
)
async def detach_product_image(
    product_id: IdPath,
    image_id: IdPath,
    session: SessionDep,
    actor: MediaWriter,
) -> None:
    """Файл остаётся в медиатеке. Если отвязано главное изображение,
    главным становится первое из оставшихся."""
    await AdminProductImageService(session).detach(product_id, image_id, actor)
