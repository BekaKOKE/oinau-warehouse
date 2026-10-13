/**
 * Транспорт Admin API.
 *
 * Поверх общего `@oinau/api-client` добавляет только то, что нужно
 * админке: различение «сервер ответил ошибкой» и «сервер не ответил»
 * и приведение query-параметров из OpenAPI (там встречается `null`).
 * Токен сюда не попадает — его подставляет `lib/auth/session.ts`.
 *
 * Отдельно живут два запроса, которые не укладываются в JSON-клиент:
 * скачивание XLSX (ответ — файл) и отправка файла через multipart.
 * Формат ошибок у них общий с остальным API — `ApiError`.
 */

import { ApiError, createApiClient, type RequestOptions } from '@oinau/api-client';

import { API_URL } from '@/lib/config';

export { ApiError };

const client = createApiClient({ baseUrl: API_URL });

/** Ошибка сети или таймаута — API не ответил вовсе. */
export class NetworkError extends Error {
  constructor(readonly cause?: unknown) {
    super('Не удалось связаться с сервером');
    this.name = 'NetworkError';
  }
}

type QueryInput = Record<string, string | number | boolean | null | undefined>;

export type AdminRequestOptions = Omit<RequestOptions, 'query'> & {
  query?: QueryInput;
};

function cleanQuery(query: QueryInput | undefined): RequestOptions['query'] {
  if (!query) return undefined;
  const result: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(query)) {
    // Пустая строка из поля поиска — это «фильтра нет», а не поиск по "".
    if (value === null || value === undefined || value === '') continue;
    result[key] = value;
  }
  return result;
}

export async function rawRequest<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  try {
    return await client.request<T>(path, { ...options, query: cleanQuery(options.query) });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError' && options.signal?.aborted) {
      throw error;
    }
    throw new NetworkError(error);
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

// ---------------------------------------------------------------- файлы

/**
 * Файлы больше JSON-ответов, а экспорт каталога считается на сервере,
 * поэтому ждём дольше обычного запроса (15 с в общем клиенте).
 */
const FILE_TIMEOUT_MS = 120_000;

export type DownloadedFile = { blob: Blob; filename: string | null };

type ErrorBody = {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
};

function fileUrl(path: string): string {
  const base = API_URL.endsWith('/') ? API_URL : `${API_URL}/`;
  return new URL(path.replace(/^\//, ''), base).toString();
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as ErrorBody | null;
  return new ApiError(
    response.status,
    body?.error?.code ?? 'unknown_error',
    body?.error?.message ?? response.statusText,
    body?.error?.details,
    body?.error?.request_id,
  );
}

async function sendFile(
  path: string,
  { method, body, headers, signal }: FileRequestOptions,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FILE_TIMEOUT_MS);
  signal?.addEventListener('abort', () => controller.abort());

  let response: Response;
  try {
    response = await fetch(fileUrl(path), {
      method,
      // Content-Type для FormData ставит сам браузер: в нём граница multipart.
      headers,
      body,
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new NetworkError(error);
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) throw await toApiError(response);
  return response;
}

type FileRequestOptions = {
  method: 'GET' | 'POST';
  body?: FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

/** Имя файла из Content-Disposition; без него вызывающий подставит своё. */
export function filenameFromResponse(response: Response): string | null {
  const disposition = response.headers?.get?.('content-disposition') ?? null;
  if (!disposition) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded?.[1]) return decodeURIComponent(encoded[1].trim());
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1]?.trim() ?? null;
}

/** Скачивание файла: XLSX экспорта и шаблона импорта. */
export async function rawDownload(
  path: string,
  options: { headers?: Record<string, string>; signal?: AbortSignal } = {},
): Promise<DownloadedFile> {
  const response = await sendFile(path, { method: 'GET', ...options });
  return { blob: await response.blob(), filename: filenameFromResponse(response) };
}

/** Отправка файла в поле `file` — предпросмотр и подтверждение импорта. */
export async function rawUpload<T>(
  path: string,
  file: File,
  options: { headers?: Record<string, string>; signal?: AbortSignal } = {},
): Promise<T> {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await sendFile(path, { method: 'POST', body: form, ...options });
  return (await response.json()) as T;
}
