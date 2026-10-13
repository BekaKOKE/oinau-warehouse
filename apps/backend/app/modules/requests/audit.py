"""События журнала аудита для заявок.

Общие для публичного и админского сервисов. Персональные данные
(имя, телефон, email, тексты комментариев) в журнал не пишутся:
журнал читают шире, чем карточку заявки, и хранят дольше.
"""

from __future__ import annotations

REQUEST_ENTITY = "request"

# Заявку создаёт не сотрудник, а посетитель сайта: user_id пуст,
# источник описан полем actor.
PUBLIC_ACTOR = "public"


class RequestAuditAction:
    CREATED = "request.created"
    STATUS_UPDATED = "request.status_updated"
    COMMENT_CREATED = "request.comment_created"
