/**
 * Подписи и форматирование кабинета: статусы, даты, суммы, ошибки.
 *
 * Обычный модуль без `'use client'`: функции нужны и клиентским
 * компонентам, и тестам.
 */

import type {
  CustomerRequestStatus,
  NotificationType,
  PricingType,
  ProjectStatus,
  RequestSource,
} from '@oinau/api-types';

import { ApiError, describeError } from '@/lib/api/client';
import { UnauthenticatedError } from '@/lib/cabinet/session';
import { currencySymbol, formatAmount } from '@/lib/format';

export type Tone = 'neutral' | 'info' | 'warning' | 'success' | 'danger';

export const REQUEST_STATUS: Record<CustomerRequestStatus, { label: string; tone: Tone }> = {
  NEW: { label: 'Новая', tone: 'info' },
  IN_PROGRESS: { label: 'В работе', tone: 'info' },
  WAITING_CLIENT: { label: 'Ждёт вашего ответа', tone: 'warning' },
  QUOTE_SENT: { label: 'КП отправлено', tone: 'warning' },
  APPROVED: { label: 'Согласована', tone: 'success' },
  COMPLETED: { label: 'Выполнена', tone: 'success' },
  CANCELLED: { label: 'Отменена', tone: 'neutral' },
};

export function describeRequestStatus(status: CustomerRequestStatus) {
  return REQUEST_STATUS[status] ?? { label: status, tone: 'neutral' as Tone };
}

/**
 * Как отправлена заявка — словами клиента. Быстрый заказ бывает без
 * позиций (звонок, запрос КП): подпись объясняет, почему в ней «0».
 * Обычная заявка из корзины подписи не требует.
 */
export const REQUEST_SOURCE: Partial<Record<RequestSource, string>> = {
  QUICK_CALLBACK: 'Обратный звонок',
  ONE_CLICK: 'Заказ в 1 клик',
  SKU_LIST: 'Заказ по артикулам',
  QUOTE_REQUEST: 'Запрос КП',
};

export function describeRequestSource(source: RequestSource | null | undefined): string | null {
  return source ? (REQUEST_SOURCE[source] ?? null) : null;
}

export const PROJECT_STATUS: Record<ProjectStatus, { label: string; tone: Tone }> = {
  PLANNING: { label: 'Планирование', tone: 'info' },
  ACTIVE: { label: 'В работе', tone: 'success' },
  ON_HOLD: { label: 'На паузе', tone: 'warning' },
  COMPLETED: { label: 'Завершён', tone: 'neutral' },
  ARCHIVED: { label: 'В архиве', tone: 'neutral' },
};

export const PROJECT_STATUSES = Object.keys(PROJECT_STATUS) as ProjectStatus[];

export function describeProjectStatus(status: ProjectStatus) {
  return PROJECT_STATUS[status] ?? { label: status, tone: 'neutral' as Tone };
}

export const NOTIFICATION_TYPE: Record<NotificationType, string> = {
  REQUEST_STATUS_CHANGED: 'Статус заявки',
  REQUEST_COMMENT_ADDED: 'Ответ менеджера',
  ACCOUNT: 'Аккаунт',
  SYSTEM: 'Системное',
};

const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

const shortDateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
});

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  return date ? dateFormat.format(date) : '—';
}

export function formatShortDate(value: string | null | undefined): string {
  const date = parse(value);
  return date ? shortDateFormat.format(date) : '—';
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? dateTimeFormat.format(date) : '—';
}

/** Сумма с валютой; `null` — цена по запросу, а не ноль. */
export function formatMoney(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined) return 'По запросу';
  return `${formatAmount(value)} ${currencySymbol(currency)}`;
}

export function formatUnitPrice(
  value: string | null | undefined,
  currency: string,
  pricingType: PricingType,
): string {
  if (value === null || value === undefined || pricingType === 'ON_REQUEST') return 'По запросу';
  return formatMoney(value, currency);
}

// ---------------------------------------------------------------- ошибки

export function isUnauthenticated(error: unknown): boolean {
  return (
    error instanceof UnauthenticatedError || (error instanceof ApiError && error.status === 401)
  );
}

/**
 * Текст ошибки кабинета.
 *
 * Сообщения backend написаны для человека и показываются как есть.
 * Отдельно — то, что без пояснения непонятно: лимит частоты и общая
 * ошибка валидации (её поля разбирает `fieldErrorsFrom`).
 */
export function describeCabinetError(error: unknown): string {
  // Неверный пароль при входе — тоже 401, но это не «истёкшая сессия».
  if (error instanceof ApiError && error.code === 'invalid_credentials') return error.message;
  if (isUnauthenticated(error)) return 'Сессия истекла. Войдите в кабинет заново.';
  if (error instanceof ApiError) {
    if (error.code === 'rate_limited') {
      return 'Слишком много попыток. Подождите немного и попробуйте снова.';
    }
    if (error.code === 'validation_error') return 'Проверьте правильность заполнения полей.';
    // У «аккаунт заблокирован» свой понятный текст — общий только для прочих 403.
    if (error.status === 403 && error.code !== 'account_locked') {
      return 'Недостаточно прав для этого действия.';
    }
    if (error.status >= 500) return 'Сервер временно недоступен. Попробуйте позже.';
  }
  return describeError(error);
}

type PydanticIssue = { loc?: unknown[]; msg?: string };

/**
 * Ошибки полей из ответа `validation_error`: `{loc: ['body', 'phone'], msg}`.
 * Префикс Pydantic «Value error, » отрезается — посетителю он ни о чём.
 */
export function fieldErrorsFrom(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== 'validation_error') return {};
  const fields = error.details?.fields;
  if (!Array.isArray(fields)) return {};
  const result: Record<string, string> = {};
  for (const issue of fields as PydanticIssue[]) {
    const name = issue.loc?.[issue.loc.length - 1];
    if (typeof name !== 'string' || !issue.msg || result[name]) continue;
    result[name] = issue.msg.replace(/^Value error, /, '');
  }
  return result;
}

export const PASSWORD_MIN_LENGTH = 12;

export function validatePassword(value: string): string | undefined {
  if (!value) return 'Введите пароль';
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `Пароль должен быть не короче ${PASSWORD_MIN_LENGTH} символов`;
  }
  if (value.trim() !== value) return 'Пароль не должен начинаться или заканчиваться пробелом';
  return undefined;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(value: string): string | undefined {
  if (!value.trim()) return 'Введите email';
  if (!EMAIL_PATTERN.test(value.trim())) return 'Проверьте адрес электронной почты';
  return undefined;
}

export function validatePhone(value: string): string | undefined {
  if (!value.trim()) return 'Укажите телефон';
  const digits = value.match(/\d/g)?.length ?? 0;
  if (digits < 5 || digits > 15) return 'В номере должно быть от 5 до 15 цифр';
  if (!/^[\d\s+\-()]+$/.test(value.trim())) {
    return 'Телефон может содержать только цифры, пробелы, «+», «-» и скобки';
  }
  return undefined;
}
