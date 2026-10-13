/**
 * Единая точка обращения к публичному API.
 *
 * Компоненты не вызывают `fetch` сами: иначе обработка ошибок, таймауты
 * и базовый URL разъезжаются по файлам, и первый же сбой сети выглядит
 * на разных экранах по-разному.
 *
 * Клиент один, а адрес разный: серверные компоненты ходят по внутреннему
 * адресу (в Docker это `backend:8000`), браузер — по публичному.
 */

import { ApiError, createApiClient, type RequestOptions } from '@oinau/api-client';

import { PUBLIC_API_URL, SERVER_API_URL } from '@/lib/config';

export { ApiError };

const isServer = typeof window === 'undefined';

const client = createApiClient({
  baseUrl: isServer ? SERVER_API_URL : PUBLIC_API_URL,
});

export type QueryValue = string | number | boolean | readonly string[] | undefined;

export type PublicRequestOptions = RequestOptions & {
  /**
   * Сколько секунд ответ считается свежим.
   *
   * Каталог и контент меняются редко, но не «никогда»: бессрочный кеш
   * оставил бы на витрине вчерашние цены до следующей сборки.
   */
  revalidate?: number | false;
};

/** Ошибка сети или таймаута — API не ответил вовсе. */
export class NetworkError extends Error {
  constructor(readonly cause?: unknown) {
    super('Не удалось связаться с сервером');
    this.name = 'NetworkError';
  }
}

export async function apiRequest<T>(path: string, options: PublicRequestOptions = {}): Promise<T> {
  const { revalidate, fetchOptions, ...rest } = options;
  try {
    return await client.request<T>(path, {
      ...rest,
      fetchOptions: {
        ...fetchOptions,
        // `next` понимает только серверный fetch; в браузере поле игнорируется.
        ...(revalidate === undefined ? {} : { next: { revalidate } }),
      } as RequestInit,
    });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new NetworkError(error);
  }
}

/** Запрос, который допускает отсутствие данных: 404 превращается в null. */
export async function apiRequestOrNull<T>(
  path: string,
  options: PublicRequestOptions = {},
): Promise<T | null> {
  try {
    return await apiRequest<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * Человеческий текст ошибки для экрана.
 *
 * Сообщение backend показывается как есть: оно написано по-русски
 * и предназначено посетителю. Всё остальное сводится к одной фразе —
 * стектрейсы и коды на витрине бесполезны.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof NetworkError) return 'Нет связи с сервером. Проверьте подключение.';
  return 'Произошла ошибка. Попробуйте ещё раз.';
}
