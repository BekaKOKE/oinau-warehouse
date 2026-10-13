/**
 * Сессия сотрудника в браузере.
 *
 * Access-токен живёт только в памяти этого модуля: ни localStorage,
 * ни sessionStorage, ни обычная cookie. Refresh-токен браузер хранит
 * в httpOnly cookie, которую выставляет backend на путь
 * /api/v1/admin/auth, — JavaScript его не видит.
 *
 * С кабинетом клиента ничего не делится: другой путь API, другая cookie,
 * другой ключ признака сессии и другое имя Web Lock. Токен клиента
 * backend в админку не пропустит (другая аудитория JWT), но и фронтенд
 * не должен их путать.
 *
 * Ловушки ротации refresh-токенов (backend считает повторное
 * предъявление старого токена кражей и отзывает всю цепочку):
 * 1. Параллельные обновления внутри вкладки делят ОДИН запрос.
 * 2. Несколько вкладок обновляются под Web Lock: вторая дождётся первой
 *    и отправит уже новую cookie.
 *
 * В localStorage лежит лишь признак «в этом браузере входили» — без него
 * открытие страницы входа стучалось бы в /refresh впустую.
 */

import type { TokenResponse } from '@/lib/api/types';
import {
  ApiError,
  rawDownload,
  rawRequest,
  rawUpload,
  type AdminRequestOptions,
  type DownloadedFile,
} from '@/lib/api/client';

export const SESSION_HINT_KEY = 'oinau.admin.session';
export const AUTH_BASE = '/api/v1/admin/auth';

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

export function subscribeSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
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
    // Приватный режим: сессия работает до перезагрузки вкладки.
  }
}

export function hasSessionHint(): boolean {
  return readHint();
}

export function storeTokens(response: TokenResponse) {
  current = { token: response.access_token, expiresAt: Date.now() + response.expires_in * 1000 };
  writeHint(true);
  notify(true);
}

/** Забыть сессию локально (после выхода или отказа в обновлении). */
export function clearSession() {
  current = null;
  writeHint(false);
  // Уведомляем всегда: к моменту отказа refresh токен в памяти уже
  // стёрт (запрос с 401 обнуляет его), и проверка «был ли токен»
  // пропустила бы как раз главный случай — отзыв сессии на сервере.
  notify(false);
}

/**
 * Выход в другой вкладке снимает признак сессии — здесь это событие
 * `storage`. Токен в памяти этой вкладки ещё жил бы до 15 минут, поэтому
 * забываем его сразу.
 */
export function watchOtherTabs(): () => void {
  const handler = (event: StorageEvent) => {
    if (event.key === SESSION_HINT_KEY && event.newValue === null && current !== null) {
      current = null;
      notify(false);
    }
  };
  window.addEventListener('storage', handler);
  return () => window.removeEventListener('storage', handler);
}

function freshToken(): string | null {
  if (!current) return null;
  return current.expiresAt - EXPIRY_MARGIN_MS > Date.now() ? current.token : null;
}

async function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (!locks) return task();
  return locks.request('oinau-admin-refresh', task) as Promise<T>;
}

async function performRefresh(): Promise<string | null> {
  try {
    const response = await withRefreshLock(() =>
      rawRequest<TokenResponse>(`${AUTH_BASE}/refresh`, { method: 'POST' }),
    );
    storeTokens(response);
    return response.access_token;
  } catch (error) {
    // 401 — сессии нет или она отозвана. Сетевой сбой сессию не удаляет:
    // иначе кратковременная потеря связи выкидывала бы из админки.
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

export async function getAccessToken(): Promise<string | null> {
  return freshToken() ?? refreshSession();
}

export class UnauthenticatedError extends Error {
  constructor() {
    super('Сессия истекла. Войдите снова.');
    this.name = 'UnauthenticatedError';
  }
}

/**
 * Запрос к /api/v1/admin от имени сотрудника.
 *
 * На 401 (токен отозван раньше срока: смена пароля, отключение
 * сотрудника) — одна попытка обновить сессию и повторить запрос.
 * 403 сессию не трогает: это «нет права», а не «не вошёл».
 */
async function withAccessToken<T>(send: (accessToken: string) => Promise<T>): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new UnauthenticatedError();
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

function bearer(accessToken: string): Record<string, string> {
  return { Authorization: `Bearer ${accessToken}` };
}

export async function adminRequest<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  return withAccessToken((token) =>
    rawRequest<T>(path, { ...options, headers: { ...options.headers, ...bearer(token) } }),
  );
}

/** Скачивание файла API (XLSX) — тот же токен и та же обработка 401. */
export async function adminDownload(
  path: string,
  options: { signal?: AbortSignal } = {},
): Promise<DownloadedFile> {
  return withAccessToken((token) => rawDownload(path, { ...options, headers: bearer(token) }));
}

/** Отправка файла в API (multipart, поле `file`). */
export async function adminUpload<T>(
  path: string,
  file: File,
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  return withAccessToken((token) =>
    rawUpload<T>(path, file, { ...options, headers: bearer(token) }),
  );
}

export async function login(email: string, password: string): Promise<void> {
  const response = await rawRequest<TokenResponse>(`${AUTH_BASE}/login`, {
    method: 'POST',
    body: { email, password },
  });
  storeTokens(response);
}

export async function logout(): Promise<void> {
  try {
    // Без токена: backend отзывает refresh-токен по cookie.
    await rawRequest<void>(`${AUTH_BASE}/logout`, { method: 'POST' });
  } finally {
    clearSession();
  }
}

/** Только для тестов: сбросить состояние модуля между сценариями. */
export function resetSessionForTests() {
  current = null;
  pendingRefresh = null;
  listeners.clear();
}
