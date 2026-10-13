/**
 * Разделы админки и права, без которых раздел не показывается.
 *
 * Правило видимости — «есть ли смысл открывать раздел», а не «пустит ли
 * backend». Каталог читать может и MANAGER (право catalog.read), но
 * категории и характеристики ему не нужны: работать с ними без
 * catalog.write нельзя. Товары и склад менеджеру показываются только
 * для чтения — он сверяет позиции заявки с каталогом и наличием.
 * Импорт/экспорт открыт с catalog.read: выгрузить каталог и проверить
 * файл backend разрешает и без права записи.
 *
 * Скрытие пункта — не защита: backend проверяет каждый запрос.
 */

import { Permission, type PermissionCode } from '@/lib/auth/permissions';

export type NavIcon =
  | 'dashboard'
  | 'products'
  | 'categories'
  | 'attributes'
  | 'requests'
  | 'stock'
  | 'content'
  | 'import'
  | 'users'
  | 'audit'
  | 'integration'
  | 'tag';

export type NavItem = {
  href: string;
  label: string;
  icon: NavIcon;
  /** Все перечисленные права обязательны. */
  requires: readonly PermissionCode[];
  /** Совпадение только по точному пути (для корня). */
  exact?: boolean;
};

export type NavGroup = { title: string | null; items: readonly NavItem[] };

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    title: null,
    items: [{ href: '/', label: 'Dashboard', icon: 'dashboard', requires: [], exact: true }],
  },
  {
    title: 'Продажи',
    items: [
      { href: '/requests', label: 'Заявки', icon: 'requests', requires: [Permission.REQUEST_READ] },
    ],
  },
  {
    title: 'Каталог',
    items: [
      { href: '/products', label: 'Товары', icon: 'products', requires: [Permission.CATALOG_READ] },
      {
        href: '/categories',
        label: 'Категории',
        icon: 'categories',
        requires: [Permission.CATALOG_WRITE],
      },
      {
        href: '/attributes',
        label: 'Характеристики',
        icon: 'attributes',
        requires: [Permission.CATALOG_WRITE],
      },
      {
        href: '/colors',
        label: 'Цвета',
        icon: 'tag',
        requires: [Permission.CATALOG_WRITE],
      },
      { href: '/stock', label: 'Склад', icon: 'stock', requires: [Permission.CATALOG_READ] },
      {
        href: '/import-export',
        label: 'Импорт / экспорт',
        icon: 'import',
        // Экспорт, шаблон, предпросмотр и история доступны с catalog.read —
        // ровно как в backend. Применять импорт можно только с catalog.write,
        // и эта кнопка внутри раздела показывается отдельно.
        requires: [Permission.CATALOG_READ],
      },
    ],
  },
  {
    title: 'Сайт',
    items: [
      { href: '/content', label: 'Контент', icon: 'content', requires: [Permission.CONTENT_WRITE] },
    ],
  },
  {
    title: 'Администрирование',
    items: [
      { href: '/users', label: 'Пользователи', icon: 'users', requires: [Permission.USER_MANAGE] },
      { href: '/audit', label: 'Аудит', icon: 'audit', requires: [Permission.AUDIT_READ] },
      {
        href: '/integration',
        label: 'Интеграции',
        icon: 'integration',
        // Состояние обмена и каналов — эксплуатационная настройка системы,
        // как и в backend (право settings.write).
        requires: [Permission.SETTINGS_WRITE],
      },
    ],
  },
];

export function visibleNav(granted: ReadonlySet<string>): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.requires.every((code) => granted.has(code))),
  })).filter((group) => group.items.length > 0);
}

export function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/** Разрешён ли переход после входа: только внутренний путь приложения. */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    return '/';
  }
  return value.startsWith('/login') ? '/' : value;
}
