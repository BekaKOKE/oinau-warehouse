/**
 * Шапка сайта.
 *
 * Клиентский компонент: он знает текущий маршрут, состав заявки и
 * открывает панель. Данные (категории, настройки) приходят пропсами
 * из серверного макета — шапка их не запрашивает.
 *
 * Личный кабинет на этом этапе не реализован: кнопка «Войти» ведёт
 * на страницу-заглушку `/cabinet/login`, а не в несуществующую форму.
 */

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

import type { CategoryNode } from '@oinau/api-types';

import { useFavorites } from '@/components/favorites/FavoritesProvider';
import { useRequestDrawer } from '@/components/request/RequestDrawerContext';
import { useRequest } from '@/components/request/RequestProvider';
import { ButtonLink } from '@/components/ui/Button';
import { productCountLabel } from '@/lib/format';
import { NAV_LINKS } from '@/lib/navigation';
import { SearchBar } from './SearchBar';
import styles from './SiteHeader.module.css';

function Logo() {
  return (
    <Link href="/" className={styles.logo} aria-label="OINAU PRO — на главную">
      <span className={styles.logoMark} aria-hidden="true">
        <svg width="16" height="14" viewBox="0 0 16 14" fill="none">
          <path d="M8 0.5 15.4 13.5H0.6L8 0.5Z" fill="#fff" />
        </svg>
      </span>
      <span className={styles.logoText}>
        <span className={styles.logoName}>
          OINAU<span> PRO</span>
        </span>
        <span className={styles.logoTagline}>Комплектующие для площадок</span>
      </span>
    </Link>
  );
}

export function SiteHeader({ categories }: { categories: CategoryNode[] }) {
  const pathname = usePathname();
  const { count, ready } = useRequest();
  const { count: favoritesCount, ready: favoritesReady } = useFavorites();
  const { open } = useRequestDrawer();
  const [menuOpen, setMenuOpen] = useState(false);

  // Переход по ссылке закрывает меню: иначе оно остаётся поверх новой страницы.
  useEffect(() => setMenuOpen(false), [pathname]);

  const topCategories = categories.flatMap((node) => node.children ?? []).slice(0, 8);

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Logo />

        <nav className={styles.nav} aria-label="Основная навигация">
          {NAV_LINKS.map((link, index) => (
            <Link
              key={link.href}
              href={link.href}
              className={[
                styles.navLink,
                index === 0 ? styles.navPrimary : '',
                pathname === link.href || pathname.startsWith(`${link.href}/`)
                  ? styles.navLinkActive
                  : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <SearchBar className={styles.search} />

        <div className={styles.actions}>
          <Link href="/favorites" className={styles.iconButton} aria-label="Избранное">
            <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M8 14S1.5 10.1 1.5 5.9A3.4 3.4 0 0 1 8 4.3a3.4 3.4 0 0 1 6.5 1.6C14.5 10.1 8 14 8 14Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
            </svg>
            {favoritesReady && favoritesCount > 0 ? (
              <span className={styles.counter}>{favoritesCount}</span>
            ) : null}
          </Link>

          <button
            type="button"
            className={styles.iconButton}
            onClick={open}
            aria-label={ready && count > 0 ? `Заявка: ${count}` : 'Заявка'}
          >
            <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M2.5 3.5h11v9h-11z M2.5 6.5h11 M6 3.5v9"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
            </svg>
            {ready && count > 0 ? <span className={styles.counter}>{count}</span> : null}
          </button>

          <ButtonLink
            href="/cabinet/login"
            variant="light"
            size="md"
            className={styles.loginButton}
          >
            Войти
          </ButtonLink>

          <button
            type="button"
            className={`${styles.iconButton} ${styles.burger}`}
            onClick={() => setMenuOpen(true)}
            aria-label="Открыть меню"
            aria-expanded={menuOpen}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path
                d="M2 5h14M2 9h14M2 13h14"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {menuOpen ? (
        <div
          className={styles.mobileMenu}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setMenuOpen(false);
          }}
        >
          <nav className={styles.mobilePanel} aria-label="Меню">
            <div className={styles.mobileHeader}>
              <span className={styles.mobileTitle}>Меню</span>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => setMenuOpen(false)}
                aria-label="Закрыть меню"
              >
                ✕
              </button>
            </div>

            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href} className={styles.mobileLink}>
                {link.label}
              </Link>
            ))}

            {topCategories.length > 0 ? (
              <div className={styles.mobileSection}>
                <span className={styles.mobileTitle}>Категории</span>
                {topCategories.map((category) => (
                  <Link
                    key={category.slug}
                    href={`/catalog/${category.slug}`}
                    className={styles.mobileLink}
                  >
                    {category.name}
                    <span className={styles.mobileCount}>
                      {productCountLabel(category.product_count ?? 0)}
                    </span>
                  </Link>
                ))}
              </div>
            ) : null}

            <div className={styles.mobileSection}>
              <ButtonLink href="/cabinet/login" variant="light" block>
                Войти в кабинет
              </ButtonLink>
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}
