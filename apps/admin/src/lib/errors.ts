/**
 * Ошибки API в виде, пригодном для экрана.
 *
 * Сообщения backend написаны по-русски для людей и показываются как есть.
 * Ошибки валидации (422) раскладываются по полям формы: FastAPI отдаёт
 * их списком `details.fields` с путём `loc`.
 */

import { ApiError, NetworkError } from '@/lib/api/client';
import { UnauthenticatedError } from '@/lib/auth/session';

export type FieldErrors = Record<string, string>;

type RawFieldError = { loc?: unknown; msg?: unknown };

function isRawFieldError(value: unknown): value is RawFieldError {
  return typeof value === 'object' && value !== null && 'msg' in value;
}

/** Pydantic пишет «Value error, <текст>» — служебную приставку убираем. */
function cleanMessage(message: string): string {
  return message.replace(/^(Value error|Assertion failed), /, '');
}

function rawFields(error: ApiError): RawFieldError[] {
  const fields = error.details?.fields;
  return Array.isArray(fields) ? fields.filter(isRawFieldError) : [];
}

/**
 * Ошибки по полям: ключ — путь без `body` («translations.ru.name»).
 * Ошибка уровня модели (loc = ["body"]) попадает под ключ «_form».
 */
export function extractFieldErrors(error: unknown): FieldErrors {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const result: FieldErrors = {};
  for (const field of rawFields(error)) {
    const loc = Array.isArray(field.loc) ? field.loc.map(String) : [];
    const path = (loc[0] === 'body' || loc[0] === 'query' ? loc.slice(1) : loc).join('.');
    const key = path || '_form';
    if (!(key in result)) result[key] = cleanMessage(String(field.msg));
  }
  return result;
}

export function describeError(error: unknown): string {
  if (error instanceof UnauthenticatedError) return error.message;
  if (error instanceof NetworkError) return 'Нет связи с сервером. Проверьте подключение.';
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Недостаточно прав для этого действия.';
    if (error.status === 429) return 'Слишком много запросов. Подождите немного и повторите.';
    if (error.status >= 500) {
      return error.requestId
        ? `Ошибка сервера. Код запроса: ${error.requestId}`
        : 'Ошибка сервера. Попробуйте позже.';
    }
    if (error.status === 422) {
      const first = rawFields(error)[0];
      if (first) return cleanMessage(String(first.msg));
    }
    return error.message;
  }
  return 'Произошла ошибка. Попробуйте ещё раз.';
}

export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}
