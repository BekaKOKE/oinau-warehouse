/**
 * Клиент API: параметры запроса, разбор ошибок backend и поведение
 * при обрыве сети.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  NetworkError,
  apiRequest,
  apiRequestOrNull,
  describeError,
} from '@/lib/api/client';
import { fetchProducts } from '@/lib/api/catalog';
import { fetchHomeContent } from '@/lib/api/content';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'ok',
    json: async () => body,
  } as Response;
}

describe('apiRequest', () => {
  it('собирает строку запроса и пропускает пустые параметры', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));

    await apiRequest('/api/v1/public/products', {
      query: { search: 'канат', page: 1, category: undefined },
    });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.pathname).toBe('/api/v1/public/products');
    expect(url.searchParams.get('search')).toBe('канат');
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.has('category')).toBe(false);
  });

  it('превращает ошибку backend в ApiError с кодом и деталями', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'product_unavailable',
            message: 'Товар недоступен для заявки',
            details: { skus: ['RP-016'] },
          },
        },
        422,
      ),
    );

    const error = await apiRequest('/api/v1/public/requests', { method: 'POST', body: {} }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).code).toBe('product_unavailable');
    expect((error as ApiError).details).toEqual({ skus: ['RP-016'] });
  });

  it('обрыв сети превращается в NetworkError, а не в падение', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const error = await apiRequest('/api/v1/public/categories').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(NetworkError);
    expect(describeError(error)).toBe('Нет связи с сервером. Проверьте подключение.');
  });

  it('передаёт ключ идемпотентности заголовком', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ number: 'R-2026-000001' }));

    await apiRequest('/api/v1/public/requests', {
      method: 'POST',
      body: { items: [] },
      idempotencyKey: 'key-123',
    });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('key-123');
    expect(headers['Content-Type']).toBe('application/json');
  });
});

describe('apiRequestOrNull', () => {
  it('404 означает отсутствие данных, а не ошибку', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'not_found', message: 'Товар не найден' } }, 404),
    );

    await expect(apiRequestOrNull('/api/v1/public/products/none')).resolves.toBeNull();
  });

  it('остальные ошибки пробрасываются', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'internal_error', message: 'Ошибка' } }, 500),
    );

    await expect(apiRequestOrNull('/api/v1/public/products/none')).rejects.toBeInstanceOf(ApiError);
  });
});

describe('модули каталога и контента', () => {
  it('fetchProducts переводит фильтры в параметры backend', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, page: 1, page_size: 24, pages: 0 }),
    );

    await fetchProducts({ category: 'kanaty-i-seti', minPrice: '1000', sort: 'price_asc' });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.searchParams.get('category')).toBe('kanaty-i-seti');
    expect(url.searchParams.get('min_price')).toBe('1000');
    expect(url.searchParams.get('sort')).toBe('price_asc');
    expect(url.searchParams.get('page_size')).toBe('24');
  });

  it('недоступная CMS не роняет страницу — раздел просто пуст', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(fetchHomeContent()).resolves.toBeNull();
  });
});
