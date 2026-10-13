"""Сборка текста уведомлений из payload записи outbox.

Шаблоны живут здесь, а не в базе и не в файлах: их пять, они меняются
вместе с кодом и должны проверяться тестами. Отдельный шаблонизатор
добавил бы зависимость и слой экранирования ради пяти сообщений.

ПРАВИЛО СОДЕРЖИМОГО. В деловой канал (Telegram, почта отдела) уходит
то, что нужно для работы с заявкой: номер, контакт, состав, сумма.
В письмо клиенту — только то, что он и так знает про свою заявку.
Ни токенов, ни паролей, ни служебных идентификаторов в тексте нет,
кроме одноразовой ссылки в письмах аутентификации — она и есть письмо.
"""

from __future__ import annotations

import html
from typing import Any

from app.core.config import settings
from app.infrastructure.notifications.base import NotificationMessage
from app.modules.notifications.enums import NotificationEvent

BRAND = "OINAU PRO"

# Позиций в теле уведомления. Полный состав смотрят в карточке заявки;
# сообщение на сорок позиций не читается и упирается в лимит Telegram.
MAX_LISTED_ITEMS = 10

# Источник заявки словами менеджера. Неизвестный код показывается как есть.
SOURCE_LABELS: dict[str, str] = {
    "CATALOG_CART": "корзина на сайте",
    "PRODUCT_PAGE": "страница товара",
    "NOT_FOUND_FORM": "форма «Не нашли товар»",
    "CONTACT_FORM": "форма контактов",
    "ADMIN": "создана сотрудником",
    "QUICK_CALLBACK": "быстрый заказ — обратный звонок",
    "ONE_CLICK": "заказ в 1 клик",
    "SKU_LIST": "быстрый заказ по артикулам",
    "QUOTE_REQUEST": "запрос коммерческого предложения",
}

# Заголовок сообщения: звонок и запрос КП менеджер должен отличить
# от обычной заявки, не открывая её.
_TITLES: dict[str, str] = {
    "QUICK_CALLBACK": "Обратный звонок",
    "ONE_CLICK": "Заказ в 1 клик",
    "SKU_LIST": "Заказ по артикулам",
    "QUOTE_REQUEST": "Запрос КП",
}


def _title(payload: dict[str, Any]) -> str:
    return _TITLES.get(str(payload.get("source") or ""), "Новая заявка")


def build_message(
    *, event: str, channel: str, recipient: str, payload: dict[str, Any]
) -> NotificationMessage:
    """payload → готовое сообщение.

    Шаблон выбирается парой «событие + канал»: одно и то же событие
    выглядит по-разному в Telegram и в письме. Отсутствие шаблона —
    ошибка кода, а не данных: событие в outbox кладёт наш же сервис.
    """
    builder = _BUILDERS.get(f"{event}:{channel}")
    if builder is None:
        raise ValueError(f"Нет шаблона для события {event} в канале {channel}")
    return builder(recipient, payload)


# ------------------------------------------------------------------ заявки


def _request_lines(payload: dict[str, Any]) -> list[str]:
    """Общая часть: чем заявка полезна тому, кто её обрабатывает."""
    lines = [f"Заявка {payload.get('number', '—')}"]
    if payload.get("customer_name"):
        who = str(payload["customer_name"])
        if payload.get("company"):
            who = f"{who} ({payload['company']})"
        lines.append(f"Клиент: {who}")
    contact = " · ".join(str(value) for key in ("phone", "email") if (value := payload.get(key)))
    if contact:
        lines.append(f"Контакт: {contact}")
    if payload.get("region"):
        lines.append(f"Регион: {payload['region']}")
    if payload.get("source"):
        source = str(payload["source"])
        lines.append(f"Источник: {SOURCE_LABELS.get(source, source)}")
    if payload.get("created_at"):
        lines.append(f"Создана: {payload['created_at']}")
    return lines


def _extra_lines(payload: dict[str, Any]) -> list[str]:
    """Комментарий клиента и приложенные файлы — если они есть."""
    lines: list[str] = []
    if payload.get("comment"):
        lines.extend(["Комментарий:", str(payload["comment"])])
    attachments = payload.get("attachments") or []
    if attachments:
        lines.append("Файлы: " + ", ".join(str(name) for name in attachments))
    return lines


def _item_name(item: dict[str, Any]) -> str:
    """Название позиции с цветом: «Канат 16 мм, цвет: Красный»."""
    name = str(item.get("name") or "—")
    color = item.get("color")
    return f"{name}, цвет: {color}" if color else name


def _items_lines(payload: dict[str, Any]) -> list[str]:
    items = payload.get("items") or []
    if not items:
        return []
    lines = [f"Позиции ({payload.get('items_count', len(items))}):"]
    for item in items[:MAX_LISTED_ITEMS]:
        sku = item.get("sku") or "—"
        name = _item_name(item)
        qty = item.get("quantity") or "—"
        unit = item.get("unit") or ""
        lines.append(f"  • {sku} — {name}: {qty} {unit}".rstrip())
    hidden = len(items) - MAX_LISTED_ITEMS
    if hidden > 0:
        lines.append(f"  … и ещё {hidden}")
    return lines


def _total_line(payload: dict[str, Any]) -> list[str]:
    total = payload.get("total_estimate")
    if not total:
        return ["Сумма: по запросу"]
    return [f"Сумма: {total} {payload.get('currency', '')}".rstrip()]


def _admin_link(payload: dict[str, Any]) -> str | None:
    request_id = payload.get("request_id")
    if not request_id:
        return None
    return f"{settings.PUBLIC_ADMIN_URL.rstrip('/')}/requests/{request_id}"


def _telegram_new_request(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    lines = [f"🔔 {_title(payload)}", "", *_request_lines(payload)]
    items = _items_lines(payload)
    if items:
        lines.extend(["", *items])
    extra = _extra_lines(payload)
    if extra:
        lines.extend(["", *extra])
    lines.extend(["", *_total_line(payload)])
    link = _admin_link(payload)
    if link:
        lines.extend(["", link])
    # parse_mode не задаётся намеренно: имя клиента может содержать
    # символы разметки, и экранировать их надёжнее, чем не экранировать.
    return NotificationMessage(recipient=recipient, text="\n".join(lines))


def _email_new_request(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    title = _title(payload)
    subject = f"[{BRAND}] {title} {payload.get('number', '')}".strip()
    extra = _extra_lines(payload)
    body_lines = [
        *_request_lines(payload),
        "",
        *_items_lines(payload),
        *(["", *extra] if extra else []),
        "",
        *_total_line(payload),
    ]
    link = _admin_link(payload)
    if link:
        body_lines.extend(["", f"Открыть в админке: {link}"])
    text = "\n".join(line for line in body_lines if line is not None)

    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{html.escape(str(item.get('sku') or '—'))}</td>"
        f"<td style='padding:4px 12px 4px 0'>{html.escape(_item_name(item))}</td>"
        f"<td style='padding:4px 0'>{html.escape(str(item.get('quantity') or '—'))} "
        f"{html.escape(str(item.get('unit') or ''))}</td></tr>"
        for item in (payload.get("items") or [])[:MAX_LISTED_ITEMS]
    )
    facts = "".join(
        f"<p style='margin:2px 0'>{html.escape(line)}</p>" for line in _request_lines(payload)
    )
    table = f'<table style="margin-top:12px;font-size:14px">{rows}</table>' if rows else ""
    extra_html = "".join(
        f"<p style='margin:8px 0 0;white-space:pre-wrap'>{html.escape(line)}</p>" for line in extra
    )
    html_body = _wrap_html(
        title=title,
        body=(
            f"{facts}"
            f"{table}"
            f"{extra_html}"
            f"<p style='margin-top:12px;font-weight:600'>"
            f"{html.escape(_total_line(payload)[0])}</p>"
        ),
        action_label="Открыть заявку" if link else None,
        action_url=link,
    )
    return NotificationMessage(recipient=recipient, subject=subject, text=text, html=html_body)


def _email_status_changed(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    number = payload.get("number", "")
    status_label = payload.get("status_label") or "обновлён"
    subject = f"[{BRAND}] Заявка {number}: {status_label}"
    link = _customer_request_link(payload)
    text_lines = [
        f"Здравствуйте{_greeting_name(payload)}!",
        "",
        f"Статус заявки {number} изменён: {status_label}.",
    ]
    if link:
        text_lines.extend(["", f"Посмотреть заявку: {link}"])
    text_lines.extend(["", f"С уважением, {BRAND}"])
    html_body = _wrap_html(
        title=f"Заявка {html.escape(str(number))}",
        body=f"<p>Статус заявки изменён: <b>{html.escape(str(status_label))}</b>.</p>",
        action_label="Посмотреть заявку" if link else None,
        action_url=link,
    )
    return NotificationMessage(
        recipient=recipient, subject=subject, text="\n".join(text_lines), html=html_body
    )


def _email_comment_added(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    number = payload.get("number", "")
    subject = f"[{BRAND}] Новый ответ по заявке {number}"
    link = _customer_request_link(payload)
    text_lines = [
        f"Здравствуйте{_greeting_name(payload)}!",
        "",
        f"Менеджер оставил комментарий к заявке {number}.",
    ]
    if link:
        text_lines.extend(["", f"Читать в кабинете: {link}"])
    text_lines.extend(["", f"С уважением, {BRAND}"])
    # Текст комментария в письмо не копируется: он читается в кабинете,
    # а почтовый ящик клиента — не то место, где хранят переписку по сделке.
    html_body = _wrap_html(
        title=f"Заявка {html.escape(str(number))}",
        body="<p>Менеджер оставил комментарий к вашей заявке.</p>",
        action_label="Читать в кабинете" if link else None,
        action_url=link,
    )
    return NotificationMessage(
        recipient=recipient, subject=subject, text="\n".join(text_lines), html=html_body
    )


# --------------------------------------------------------- аутентификация


def _email_verification(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    link = str(payload.get("link", ""))
    subject = f"[{BRAND}] Подтвердите email"
    hours = payload.get("ttl_hours")
    validity = f"Ссылка действует {hours} ч." if hours else ""
    text = "\n".join(
        [
            "Здравствуйте!",
            "",
            f"Подтвердите адрес для входа в кабинет {BRAND}:",
            link,
            "",
            validity,
            "Если вы не регистрировались, просто проигнорируйте это письмо.",
        ]
    )
    html_body = _wrap_html(
        title="Подтверждение адреса",
        body=(
            f"<p>Подтвердите адрес для входа в кабинет {BRAND}.</p>"
            f"{f'<p style="color:#64748b">{html.escape(validity)}</p>' if validity else ''}"
            "<p style='color:#64748b'>Если вы не регистрировались, "
            "просто проигнорируйте это письмо.</p>"
        ),
        action_label="Подтвердить email",
        action_url=link,
    )
    return NotificationMessage(recipient=recipient, subject=subject, text=text, html=html_body)


def _email_password_reset(recipient: str, payload: dict[str, Any]) -> NotificationMessage:
    link = str(payload.get("link", ""))
    subject = f"[{BRAND}] Восстановление пароля"
    minutes = payload.get("ttl_minutes")
    validity = f"Ссылка действует {minutes} мин." if minutes else ""
    text = "\n".join(
        [
            "Здравствуйте!",
            "",
            "Вы запросили смену пароля в кабинете " + BRAND + ".",
            link,
            "",
            validity,
            "Если вы этого не делали, ничего делать не нужно — пароль останется прежним.",
        ]
    )
    html_body = _wrap_html(
        title="Восстановление пароля",
        body=(
            "<p>Вы запросили смену пароля в кабинете " + BRAND + ".</p>"
            f"{f'<p style="color:#64748b">{html.escape(validity)}</p>' if validity else ''}"
            "<p style='color:#64748b'>Если вы этого не делали, ничего делать не нужно — "
            "пароль останется прежним.</p>"
        ),
        action_label="Задать новый пароль",
        action_url=link,
    )
    return NotificationMessage(recipient=recipient, subject=subject, text=text, html=html_body)


# ----------------------------------------------------------------- общее


def _greeting_name(payload: dict[str, Any]) -> str:
    name = payload.get("customer_name")
    return f", {name}" if name else ""


def _customer_request_link(payload: dict[str, Any]) -> str | None:
    number = payload.get("number")
    if not number:
        return None
    return f"{settings.PUBLIC_SITE_URL.rstrip('/')}/account/requests"


def _wrap_html(
    *, title: str, body: str, action_label: str | None = None, action_url: str | None = None
) -> str:
    """Единое оформление письма.

    Разметка намеренно примитивная и вся в атрибутах style: почтовые
    клиенты вырезают внешние стили, а таблицы и inline-стили работают
    везде, включая Outlook.
    """
    button = ""
    if action_label and action_url:
        button = (
            f"<p style='margin:20px 0'><a href='{html.escape(action_url, quote=True)}' "
            "style='display:inline-block;padding:10px 18px;border-radius:8px;"
            "background:#0f2f5c;color:#ffffff;text-decoration:none;font-weight:600'>"
            f"{html.escape(action_label)}</a></p>"
        )
    return (
        "<!doctype html><html lang='ru'><body style='margin:0;padding:24px;"
        "background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a'>"
        "<table role='presentation' style='max-width:560px;margin:0 auto;background:#ffffff;"
        "border-radius:12px;padding:24px'><tr><td>"
        f"<p style='margin:0 0 4px;font-weight:700;letter-spacing:0.04em;color:#0f2f5c'>{BRAND}</p>"
        f"<h1 style='margin:0 0 16px;font-size:18px'>{html.escape(title)}</h1>"
        f"<div style='font-size:14px;line-height:1.5'>{body}</div>"
        f"{button}"
        "<p style='margin:24px 0 0;font-size:12px;color:#94a3b8'>"
        "Письмо отправлено автоматически, отвечать на него не нужно.</p>"
        "</td></tr></table></body></html>"
    )


_BUILDERS = {
    f"{NotificationEvent.REQUEST_CREATED}:telegram": _telegram_new_request,
    f"{NotificationEvent.REQUEST_CREATED}:email": _email_new_request,
    f"{NotificationEvent.REQUEST_STATUS_CHANGED}:email": _email_status_changed,
    f"{NotificationEvent.REQUEST_COMMENT_ADDED}:email": _email_comment_added,
    f"{NotificationEvent.CUSTOMER_EMAIL_VERIFICATION}:email": _email_verification,
    f"{NotificationEvent.CUSTOMER_PASSWORD_RESET}:email": _email_password_reset,
}
