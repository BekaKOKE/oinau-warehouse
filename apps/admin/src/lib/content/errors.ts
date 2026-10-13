/**
 * Ошибки сохранения раздела CMS в виде ошибок полей формы.
 *
 * 422 backend уже приходит с путями полей. Ссылки на медиатеку backend
 * проверяет отдельно и отвечает 404 (`media_not_found`) или 409
 * (`media_failed`) со списком UUID — их нужно показать у того поля,
 * где выбран этот файл, а не одной строкой над формой.
 */

import { ApiError } from '@/lib/api/client';
import { extractFieldErrors, type FieldErrors } from '@/lib/errors';

import type { MediaRef } from './fields';

const MEDIA_MESSAGES: Record<string, string> = {
  media_not_found: 'Файл не найден в медиатеке — выберите другое изображение',
  media_failed: 'Файл отклонён при обработке — загрузите другое изображение',
};

export function saveFieldErrors(error: unknown, refs: readonly MediaRef[]): FieldErrors {
  const errors = extractFieldErrors(error);
  if (!(error instanceof ApiError)) return errors;
  const message = MEDIA_MESSAGES[error.code];
  if (!message) return errors;

  const raw = error.details?.media_uuids;
  const uuids = new Set(Array.isArray(raw) ? raw.map(String) : []);
  for (const ref of refs) {
    if (uuids.has(ref.uuid)) errors[ref.path] = message;
  }
  return errors;
}

/** Путь `a.b` лежит внутри одного из префиксов (или совпадает с ним). */
export function pathWithin(path: string, prefixes: readonly string[]): boolean {
  return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}.`));
}
