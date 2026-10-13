/**
 * Сессия клиента: где живёт токен, обновление через refresh-cookie
 * и защита ротации от параллельных запросов.
 *
 * Сеть подменяется на уровне `fetch`: проверяется, какие запросы
 * реально уходят на backend и с какими заголовками.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loginCustomer, logoutCustomer } from '@/lib/api/customer-auth';
import { fetchProfile } from '@/lib/api/customer';
import {
  SESSION_HINT_KEY,
  UnauthenticatedError,
  clearSession,
  customerRequest,
  getAccessToken,
  hasSessionHint,
  resetSessionForTests,
  storeTokens,
  subscribeSession,
} from '@/lib/cabinet/session';

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'status',
    json: async () => body,
  } as Response;
}

const tokens = (token: string, expiresIn = 900) => ({
  access_token: token,
  token_type: 'bearer',
  expires_in: expiresIn,
});

const unauthorized = () =>
  jsonResponse(
    { error: { code: 'invalid_refresh_token', message: 'Сессия недействительна' } },
    401,
  );

function calls(path: string) {
  return fetchMock.mock.calls.filter(([url]) => new URL(String(url)).pathname === path);
}

function authHeader(call: unknown[]): string | undefined {
  return ((call[1] as RequestInit).headers as Record<string, string>).Authorization;
}

beforeEach(() => {
  resetSessionForTests();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('хранение токена', () => {
  it('access-токен не попадает ни в localStorage, ни в sessionStorage', async () => {
    fetchMock.mockResolvedValue(jsonResponse(tokens('secret-access-token')));

    await loginCustomer({ email: 'client@example.kz', password: 'customer-strong-password' });

    const stored = [
      ...Object.values({ ...window.localStorage }),
      ...Object.values({ ...window.sessionStorage }),
    ].join('|');
    expect(stored).not.toContain('secret-access-token');
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBe('1');
    await expect(getAccessToken()).resolves.toBe('secret-access-token');
  });

  it('вход отправляет запрос с cookie (credentials: include)', async () => {
    fetchMock.mockResolvedValue(jsonResponse(tokens('token')));

    await loginCustomer({ email: 'client@example.kz', password: 'customer-strong-password' });

    const [call] = calls('/api/v1/public/auth/login');
    expect((call?.[1] as RequestInit).credentials).toBe('include');
  });
});

describe('обновление сессии', () => {
  it('без токена в памяти берёт новый через /refresh', async () => {
    fetchMock.mockResolvedValue(jsonResponse(tokens('fresh')));

    await expect(getAccessToken()).resolves.toBe('fresh');
    expect(calls('/api/v1/public/auth/refresh')).toHaveLength(1);
  });

  it('одновременные запросы делят ОДНО обновление — иначе backend увидит переиспользование', async () => {
    let release: (value: Response) => void = () => undefined;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

    const pending = [getAccessToken(), getAccessToken(), getAccessToken()];
    release(jsonResponse(tokens('shared')));

    await expect(Promise.all(pending)).resolves.toEqual(['shared', 'shared', 'shared']);
    expect(calls('/api/v1/public/auth/refresh')).toHaveLength(1);
  });

  it('истекающий токен обновляется заранее', async () => {
    storeTokens(tokens('almost-expired', 10));
    fetchMock.mockResolvedValue(jsonResponse(tokens('renewed')));

    await expect(getAccessToken()).resolves.toBe('renewed');
  });

  it('отказ refresh (401) завершает сессию и снимает признак входа', async () => {
    storeTokens(tokens('old', 1));
    const listener = vi.fn();
    subscribeSession(listener);
    fetchMock.mockResolvedValue(unauthorized());

    await expect(getAccessToken()).resolves.toBeNull();
    expect(hasSessionHint()).toBe(false);
    expect(listener).toHaveBeenLastCalledWith(false);
  });

  it('сбой сети при обновлении не выкидывает из кабинета', async () => {
    storeTokens(tokens('old', 1));
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(getAccessToken()).rejects.toBeTruthy();
    expect(hasSessionHint()).toBe(true);
  });
});

describe('customerRequest', () => {
  it('подставляет Bearer-токен', async () => {
    storeTokens(tokens('access-1'));
    fetchMock.mockResolvedValue(jsonResponse({ email: 'client@example.kz' }));

    await fetchProfile();

    const [call] = calls('/api/v1/customer/profile');
    expect(authHeader(call!)).toBe('Bearer access-1');
  });

  it('на 401 обновляет сессию один раз и повторяет запрос', async () => {
    storeTokens(tokens('revoked'));
    fetchMock
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(jsonResponse(tokens('access-2')))
      .mockResolvedValueOnce(jsonResponse({ email: 'client@example.kz' }));

    await expect(fetchProfile()).resolves.toEqual({ email: 'client@example.kz' });

    const profileCalls = calls('/api/v1/customer/profile');
    expect(profileCalls).toHaveLength(2);
    expect(authHeader(profileCalls[1]!)).toBe('Bearer access-2');
    expect(calls('/api/v1/public/auth/refresh')).toHaveLength(1);
  });

  it('без сессии бросает UnauthenticatedError и не ходит в кабинет', async () => {
    fetchMock.mockResolvedValue(unauthorized());

    await expect(customerRequest('/api/v1/customer/profile')).rejects.toBeInstanceOf(
      UnauthenticatedError,
    );
    expect(calls('/api/v1/customer/profile')).toHaveLength(0);
  });
});

describe('выход', () => {
  it('вызывает /logout и очищает сессию', async () => {
    storeTokens(tokens('access'));
    fetchMock.mockResolvedValue({ ok: true, status: 204, json: async () => null } as Response);

    await logoutCustomer();

    expect(calls('/api/v1/public/auth/logout')).toHaveLength(1);
    expect(hasSessionHint()).toBe(false);
  });

  it('очищает локальную сессию, даже если backend недоступен', async () => {
    storeTokens(tokens('access'));
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(logoutCustomer()).rejects.toBeTruthy();
    expect(hasSessionHint()).toBe(false);
    fetchMock.mockResolvedValue(unauthorized());
    await expect(getAccessToken()).resolves.toBeNull();
  });

  it('clearSession без активной сессии не рассылает событий', () => {
    const listener = vi.fn();
    subscribeSession(listener);
    clearSession();
    expect(listener).not.toHaveBeenCalled();
  });
});
