/**
 * Разделы основной навигации.
 *
 * Лежат в обычном модуле, а не в компоненте шапки: шапка клиентская,
 * а подвал серверный, и данные, экспортированные из `'use client'`,
 * через эту границу приходят не массивом, а ссылкой на клиентский
 * модуль. Общий список должен жить вне обоих компонентов.
 */

export type NavLink = { href: string; label: string };

/** Левая часть меню: что продаём и что умеем. */
export const NAV_PRIMARY: readonly NavLink[] = [
  { href: '/catalog', label: 'Каталог' },
  { href: '/services', label: 'Услуги' },
  { href: '/faq', label: 'Вопросы' },
];

/**
 * Правая часть меню — рядом с телефоном и корзиной: как получить
 * заказ и как связаться.
 */
export const NAV_SECONDARY: readonly NavLink[] = [
  { href: '/delivery', label: 'Доставка' },
  { href: '/contacts', label: 'Контакты' },
];

/** Полный список — подвал и мобильное меню. */
export const NAV_LINKS: readonly NavLink[] = [...NAV_PRIMARY, ...NAV_SECONDARY];

/**
 * Пункт активен только на своём маршруте и вложенных в него:
 * «Каталог» — на `/catalog` и `/catalog/<раздел>`, но не на главной.
 *
 * Сравнение по границе сегмента: `/catalogue` не должен подсвечивать
 * `/catalog`. Карточка товара (`/product/…`) каталогом не считается —
 * у неё свои хлебные крошки.
 */
export function isNavActive(pathname: string | null | undefined, href: string): boolean {
  if (!pathname || href === '/') return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}
