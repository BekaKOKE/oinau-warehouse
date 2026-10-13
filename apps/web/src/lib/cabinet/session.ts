/**
 * Сессия клиента в браузере.
 *
 * Access-токен живёт только в памяти этого модуля: ни localStorage,
 * ни sessionStorage, ни обычная cookie. Refresh-токен браузер хранит
 * сам в httpOnly cookie, которую выставляет backend, — JavaScript его
 * не видит и не может украсть.
 *
 * Две ловушки ротации refresh-токенов, которые здесь закрыты:
 *
 * 1. Параллельные обновления. Backend меняет refresh-токен при каждом
 *    обновлении и считает повторное предъявление старого кражей —
 *    отзывает всю цепочку, и клиента выбрасывает из кабинета. Два
 *    одновременных запроса с истёкшим access-токеном (или двойной
 *    эффект StrictMode) обязаны разделить ОДНО обновление.
 * 2. Несколько вкладок. Общий промис внутри вкладки не спасает, если
 *    две вкладки открылись одновременно, поэтому обновление идёт под
 *    Web Lock: вторая вкладка дождётся первой и отправит уже новую cookie.
 *
 * В localStorage лежит лишь признак «в этом браузере входили» — без
 * него каждый анонимный посетитель при загрузке страницы стучался бы
 * в /refresh и тратил лимит запросов.
 */

import type { CustomerTokenResponse } from '@oinau/api-types';

import { ApiError, apiRequest, type PublicRequestOptions } from '@/lib/api/client';

export const SESSION_HINT_KEY = 'oinau.cabinet.session';

const AUTH_BASE = '/api/v1/public/auth';

/** Запас до истечения access-токена: обновляем заранее, а не по 401. */
const EXPIRY_MARGIN_MS = 30_000;

type TokenState = { token: string; expiresAt: number };

let current: TokenState | null = null;
let pendingRefresh: Promise<string | null> | null = null;

type Listener = (authenticated: boolean) => void;
const listeners = new Set<Listener>();

function notify(authenticated: boolean) {
  for (const listener of listeners) listener(authenticated);
}

/** Подписка на вход и выход — провайдер сессии узнаёт, что токен пропал. */
export function subscribeSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function readHint(): boolean {
  try {
    return window.localStorage.getItem(SESSION_HINT_KEY) === '1';
  } catch {
    return false;
  }
}

function writeHint(value: boolean) {
  try {
    if (value) window.localStorage.setItem(SESSION_HINT_KEY, '1');
    else window.localStorage.removeItem(SESSION_HINT_KEY);
  } catch {
    // Приватный режим: сессия всё равно работает до перезагрузки.
  }
}

/** Принять токен из ответа /login или /refresh. */
export function storeTokens(response: CustomerTokenResponse) {
  current = {
    token: response.access_token,
    expiresAt: Date.now() + response.expires_in * 1000,
  };
  writeHint(true);
  notify(true);
}

/** Забыть сессию локально (после logout или отказа refresh). */
export function clearSession() {
  const wasAuthenticated = current !== null;
  current = null;
  writeHint(false);
  if (wasAuthenticated) notify(false);
}

export function hasSessionHint(): boolean {
  return readHint();
}

function freshToken(): string | null {
  if (!current) return null;
  return current.expiresAt - EXPIRY_MARGIN_MS > Date.now() ? current.token : null;
}

async function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (!locks) return task();
  return locks.request('oinau-customer-refresh', task) as Promise<T>;
}

async function performRefresh(): Promise<string | null> {
  try {
    const response = await withRefreshLock(() =>
      apiRequest<CustomerTokenResponse>(`${AUTH_BASE}/refresh`, { method: 'POST' }),
    );
    storeTokens(response);
    return response.access_token;
  } catch (error) {
    // 401 — сессии нет или она отозвана. Сетевой сбой сессию не удаляет:
    // иначе кратковременная потеря связи выкидывала бы из кабинета.
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      clearSession();
      return null;
    }
    throw error;
  }
}

/** Одно обновление на всех, кто попросил его одновременно. */
export function refreshSession(): Promise<string | null> {
  if (!pendingRefresh) {
    pendingRefresh = performRefresh().finally(() => {
      pendingRefresh = null;
    });
  }
  return pendingRefresh;
}

/** Действующий access-токен: из памяти или после обновления. */
export async function getAccessToken(): Promise<string | null> {
  return freshToken() ?? refreshSession();
}

export class UnauthenticatedError extends Error {
  constructor() {
    super('Требуется вход в кабинет');
    this.name = 'UnauthenticatedError';
  }
}

/**
 * Запрос к /api/v1/customer от имени клиента.
 *
 * Токен подставляется заголовком через общий API-клиент. На 401
 * (токен отозван раньше срока, например после смены пароля в другой
 * вкладке) делается одна попытка обновить сессию и повторить запрос.
 */
export async function customerRequest<T>(
  path: string,
  options: PublicRequestOptions = {},
): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new UnauthenticatedError();

  const send = (accessToken: string) =>
    apiRequest<T>(path, {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${accessToken}` },
    });

  try {
    return await send(token);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    current = null;
    const renewed = await refreshSession();
    if (!renewed) throw new UnauthenticatedError();
    return send(renewed);
  }
}

/** Только для тестов: сбросить состояние модуля между сценариями. */
export function resetSessionForTests() {
  current = null;
  pendingRefresh = null;
  listeners.clear();
}
