/**
 * Разделы кабинета и безопасный адрес возврата после входа.
 */

export type CabinetSection =
  'overview' | 'requests' | 'projects' | 'favorites' | 'notifications' | 'profile';

export type CabinetNavLink = { key: CabinetSection; href: string; label: string };

export const CABINET_HOME = '/cabinet';
export const CABINET_LOGIN = '/cabinet/login';

export const CABINET_NAV: readonly CabinetNavLink[] = [
  { key: 'overview', href: '/cabinet', label: 'Обзор' },
  { key: 'requests', href: '/cabinet/requests', label: 'Заявки' },
  { key: 'projects', href: '/cabinet/projects', label: 'Проекты' },
  { key: 'favorites', href: '/cabinet/favorites', label: 'Избранное' },
  { key: 'notifications', href: '/cabinet/notifications', label: 'Уведомления' },
  { key: 'profile', href: '/cabinet/profile', label: 'Профиль' },
];

/** «Обзор» активен только на `/cabinet`, остальные — и на вложенных страницах. */
export function isCabinetNavActive(pathname: string | null | undefined, href: string): boolean {
  if (!pathname) return false;
  if (href === CABINET_HOME) return pathname === CABINET_HOME;
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Страницы входа: на них кабинет не требует сессии. */
const PUBLIC_CABINET_PATHS = [
  '/cabinet/login',
  '/cabinet/register',
  '/cabinet/verify-email',
  '/cabinet/reset-password',
];

/**
 * Куда вернуть клиента после входа.
 *
 * Принимается только путь внутри кабинета: `?next=https://evil.example`
 * или `?next=//evil.example` превратили бы форму входа в открытый
 * редирект — классический приём фишинга.
 */
export function safeNextPath(value: string | string[] | null | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !raw.startsWith('/cabinet') || raw.startsWith('//') || raw.includes('\\')) {
    return CABINET_HOME;
  }
  const path = raw.split(/[?#]/)[0] ?? '';
  if (path !== CABINET_HOME && !path.startsWith(`${CABINET_HOME}/`)) return CABINET_HOME;
  if (PUBLIC_CABINET_PATHS.some((item) => path === item || path.startsWith(`${item}/`))) {
    return CABINET_HOME;
  }
  return raw;
}

export function loginHref(next?: string | null): string {
  const target = safeNextPath(next);
  return target === CABINET_HOME
    ? CABINET_LOGIN
    : `${CABINET_LOGIN}?next=${encodeURIComponent(target)}`;
}

/** Номер страницы из query: мусор и отрицательные значения — первая. */
export function pageFromQuery(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const page = Number(raw);
  return Number.isInteger(page) && page >= 1 && page <= 10_000 ? page : 1;
}
