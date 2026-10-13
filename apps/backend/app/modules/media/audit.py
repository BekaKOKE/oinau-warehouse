"""События журнала аудита медиатеки.

Изменения изображений товара пишутся на сущность `product`: индекс
ix_audit_log_entity отвечает на вопрос «вся история этого товара»,
и смена главной фотографии должна быть в этой истории.
"""

from __future__ import annotations

MEDIA_ENTITY = "media_file"
PRODUCT_ENTITY = "product"

# Обработку выполняет воркер, а не сотрудник.
SYSTEM_ACTOR = "system"


class MediaAuditAction:
    UPLOAD_REQUESTED = "media.upload_requested"
    UPLOAD_COMPLETED = "media.upload_completed"
    UPLOAD_REJECTED = "media.upload_rejected"
    PROCESSED = "media.processed"
    PROCESSING_FAILED = "media.processing_failed"
    DELETED = "media.deleted"

    IMAGE_ATTACHED = "media.product_image_attached"
    IMAGE_UPDATED = "media.product_image_updated"
    IMAGE_DETACHED = "media.product_image_detached"
    IMAGES_REORDERED = "media.product_images_reordered"
    MAIN_IMAGE_CHANGED = "media.product_main_image_changed"
