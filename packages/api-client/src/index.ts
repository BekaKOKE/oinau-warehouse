/**
 * Общий HTTP-клиент для web и admin.
 *
 * Существует, чтобы разделение на два фронтенд-приложения не привело
 * к двум разным реализациям работы с API.
 */

import type { ApiErrorBody } from '@oinau/api-types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type ApiClientOptions = {
  baseUrl: string;
  /** Возвращает access-token. Хранится в памяти, не в localStorage. */
  getAccessToken?: () => string | null;
  defaultTimeoutMs?: number;
};

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Массив — повторяющийся параметр: `attr=a&attr=b`. */
  query?: Record<string, string | number | boolean | readonly string[] | undefined>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Для форм: защищает от дублей при двойном клике и ретраях сети. */
  idempotencyKey?: string;
  /**
   * Таймаут конкретного запроса. Нужен отправке файла: двадцать
   * мегабайт по мобильной сети не укладываются в общие 15 секунд.
   */
  timeoutMs?: number;
  /**
   * Дополнительные поля запроса, которые клиент передаёт в `fetch` как есть.
   *
   * Нужны серверным компонентам Next.js: политика кеширования задаётся
   * там расширенными полями `cache` и `next`, и без этого прохода
   * витрине пришлось бы обходить общий клиент собственным `fetch`.
   */
  fetchOptions?: RequestInit;
};

export function createApiClient(options: ApiClientOptions) {
  const { baseUrl, getAccessToken, defaultTimeoutMs = 15_000 } = options;

  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const url = new URL(path.replace(/^\//, ''), baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`);
    for (const [key, value] of Object.entries(opts.query ?? {})) {
      if (value === undefined) continue;
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, String(item));
      } else {
        url.searchParams.set(key, String(value));
      }
    }

    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...opts.headers,
    };
    // FormData уходит как есть: Content-Type с границей multipart
    // браузер выставляет сам, и заданный вручную заголовок её потерял бы.
    const isForm = typeof FormData !== 'undefined' && opts.body instanceof FormData;
    if (opts.body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
    const token = getAccessToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? defaultTimeoutMs);
    opts.signal?.addEventListener('abort', () => controller.abort());

    let body: BodyInit | undefined;
    if (isForm) body = opts.body as FormData;
    else if (opts.body !== undefined) body = JSON.stringify(opts.body);

    let response: Response;
    try {
      response = await fetch(url, {
        credentials: 'include', // refresh-токен в httpOnly cookie
        ...opts.fetchOptions,
        method: opts.method ?? 'GET',
        headers,
        body,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }

    if (response.status === 204) return undefined as T;

    const payload: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const body = payload as ApiErrorBody | null;
      throw new ApiError(
        response.status,
        body?.error?.code ?? 'unknown_error',
        body?.error?.message ?? response.statusText,
        body?.error?.details,
        body?.error?.request_id,
      );
    }

    return payload as T;
  }

  return { request };
}

export type ApiClient = ReturnType<typeof createApiClient>;
