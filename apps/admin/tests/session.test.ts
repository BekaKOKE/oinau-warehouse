/**
 * Сессия сотрудника: хранение токена, обновление через refresh-cookie,
 * обработка 401/403 и отделение от сессии кабинета клиента.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';
import {
  adminRequest,
  getAccessToken,
  login,
  logout,
  resetSessionForTests,
  SESSION_HINT_KEY,
  storeTokens,
  subscribeSession,
  UnauthenticatedError,
  watchOtherTabs,
} from '@/lib/auth/session';

import { authHeader, createFetchMock, errorResponse, jsonResponse, tokens } from './helpers';

const REFRESH = '/api/v1/admin/auth/refresh';
const LOGIN = '/api/v1/admin/auth/login';
const LOGOUT = '/api/v1/admin/auth/logout';
const ME = '/api/v1/admin/auth/me';

let net: ReturnType<typeof createFetchMock>;

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('хранение токена', () => {
  it('access-токен живёт только в памяти; в localStorage — лишь признак сессии', async () => {
    net.on('POST', LOGIN, tokens('secret-admin-token'));

    await login('admin@oinau-pro.kz', 'correct horse battery');

    const stored = [
      ...Object.values({ ...window.localStorage }),
      ...Object.values({ ...window.sessionStorage }),
    ].join('|');
    expect(stored).not.toContain('secret-admin-token');
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBe('1');
    await expect(getAccessToken()).resolves.toBe('secret-admin-token');
  });

  it('refresh уходит на путь админки с cookie, а не на путь кабинета клиента', async () => {
    net.on('POST', REFRESH, tokens('renewed'));

    await getAccessToken();

    const [call] = net.calls('POST', REFRESH);
    expect(call).toBeDefined();
    expect((call?.[1] as RequestInit).credentials).toBe('include');
    expect(net.mock.mock.calls.some(([url]) => String(url).includes('/public/auth'))).toBe(false);
  });
});

describe('обновление токена', () => {
  it('параллельные запросы делят одно обновление', async () => {
    net.on('POST', REFRESH, tokens('shared'));
    net.on('GET', ME, { ok: true });

    await Promise.all([adminRequest(ME), adminRequest(ME), adminRequest(ME)]);

    expect(net.calls('POST', REFRESH)).toHaveLength(1);
    expect(net.calls('GET', ME).every((call) => authHeader(call) === 'Bearer shared')).toBe(true);
  });

  it('на 401 обновляет сессию один раз и повторяет запрос', async () => {
    storeTokens(tokens('revoked'));
    let meCalls = 0;
    net.on('GET', ME, () => {
      meCalls += 1;
      return meCalls === 1
        ? errorResponse(401, 'unauthenticated', 'Требуется аутентификация')
        : jsonResponse({ ok: 1 });
    });
    net.on('POST', REFRESH, tokens('fresh'));

    await expect(adminRequest(ME)).resolves.toEqual({ ok: 1 });
    expect(authHeader(net.calls('GET', ME)[1] ?? [])).toBe('Bearer fresh');
  });

  it('отказ refresh (401) завершает сессию и сообщает подписчикам', async () => {
    storeTokens(tokens('old'));
    const listener = vi.fn();
    subscribeSession(listener);
    net.on('GET', ME, errorResponse(401, 'unauthenticated', 'Требуется аутентификация'));
    net.on('POST', REFRESH, errorResponse(401, 'invalid_refresh_token', 'Сессия недействительна'));

    await expect(adminRequest(ME)).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
    expect(listener).toHaveBeenLastCalledWith(false);
  });

  it('403 — это «нет права», сессия остаётся', async () => {
    storeTokens(tokens('valid'));
    net.on(
      'GET',
      '/api/v1/admin/users',
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );

    const error = await adminRequest('/api/v1/admin/users').catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
    expect(net.calls('POST', REFRESH)).toHaveLength(0);
    await expect(getAccessToken()).resolves.toBe('valid');
  });

  it('сбой сети при refresh не выбрасывает из админки', async () => {
    window.localStorage.setItem(SESSION_HINT_KEY, '1');
    net.mock.mockRejectedValueOnce(new TypeError('Failed to fetch'));

    await expect(getAccessToken()).rejects.toThrow();
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBe('1');
  });
});

describe('выход', () => {
  it('отзывает refresh на сервере и забывает токен локально', async () => {
    storeTokens(tokens('to-forget'));
    net.on('POST', LOGOUT, {
      status: 204,
      ok: true,
      json: async () => null,
    } as unknown as Response);
    net.on('POST', REFRESH, errorResponse(401, 'invalid_refresh_token', 'Сессия недействительна'));

    await logout();

    expect(net.calls('POST', LOGOUT)).toHaveLength(1);
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
    await expect(getAccessToken()).resolves.toBeNull();
  });

  it('выход в другой вкладке сразу гасит сессию в этой', async () => {
    storeTokens(tokens('tab-token'));
    const listener = vi.fn();
    subscribeSession(listener);
    const unwatch = watchOtherTabs();

    window.dispatchEvent(new StorageEvent('storage', { key: SESSION_HINT_KEY, newValue: null }));

    expect(listener).toHaveBeenLastCalledWith(false);
    unwatch();
  });
});
