/**
 * Шапка сайта.
 *
 * Две строки, как в макете: сверху логотип, поиск, телефон отдела
 * продаж, «Быстрый заказ» и корзина; снизу — разделы сайта, избранное
 * и вход в кабинет. На телефоне остаётся компактная строка (меню,
 * логотип, поиск, корзина), а разделы уходят в меню и в нижнюю панель.
 *
 * Клиентский компонент: он знает текущий маршрут, состав корзины и
 * открывает окна. Данные (категории, контакты) приходят пропсами из
 * серверного макета — шапка их не запрашивает. Телефон и часы работы —
 * из CMS: без них блок просто не выводится.
 *
 * Активный пункт определяется только маршрутом (`isNavActive`) и
 * помечается `aria-current="page"`.
 */

'use client';

import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import type { CategoryNode, ContactsContent } from '@oinau/api-types';

import { useCustomerSession } from '@/components/cabinet/CustomerSessionProvider';
import { useFavorites } from '@/components/favorites/FavoritesProvider';
import { useQuickOrder } from '@/components/quick-order/QuickOrderContext';
import { useRequestDrawer } from '@/components/request/RequestDrawerContext';
import { useRequest } from '@/components/request/RequestProvider';
import { formatCount } from '@/lib/format';
import { NAV_LINKS, NAV_PRIMARY, NAV_SECONDARY, isNavActive } from '@/lib/navigation';
import { SearchBar } from './SearchBar';
import styles from './SiteHeader.module.css';

export function Logo({
  className,
  tone = 'color',
}: {
  className?: string;
  tone?: 'color' | 'white';
}) {
  return (
    <Link
      href="/"
      className={[styles.logo, className ?? ''].filter(Boolean).join(' ')}
      aria-label="OINAU PRO — на главную"
    >
      <Image
        src={tone === 'white' ? '/brand/logo-white.png' : '/brand/logo.png'}
        alt=""
        width={1000}
        height={255}
        priority={tone === 'color'}
        className={styles.logoImage}
      />
    </Link>
  );
}

function CartIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path
        d="M1.5 2.5h2.2l1.9 9h8.6l1.6-6.5H4.6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M6.5 15.5h1.6M12.4 15.5H14" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function HeartIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 14S1.5 10.1 1.5 5.9A3.4 3.4 0 0 1 8 4.3a3.4 3.4 0 0 1 6.5 1.6C14.5 10.1 8 14 8 14Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function SiteHeader({
  categories,
  contacts = null,
}: {
  categories: CategoryNode[];
  contacts?: ContactsContent | null;
}) {
  const pathname = usePathname();
  const { count, ready } = useRequest();
  const { count: favoritesCount, ready: favoritesReady, synced } = useFavorites();
  const { status: sessionStatus, unreadCount } = useCustomerSession();
  const signedIn = sessionStatus === 'authenticated';
  const favoritesHref = synced ? '/cabinet/favorites' : '/favorites';
  const cabinetHref = signedIn ? '/cabinet' : '/cabinet/login';
  const { open } = useRequestDrawer();
  const quickOrder = useQuickOrder();
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInput = useRef<HTMLInputElement>(null);

  const phone = contacts?.phones?.[0] ?? null;
  const whatsapp = contacts?.whatsapp ?? null;
  const hours = contacts?.working_hours ?? null;
  const cartCount = ready && count > 0 ? count : 0;

  // Переход по ссылке закрывает меню и поиск: иначе они остаются
  // поверх новой страницы.
  useEffect(() => {
    setMenuOpen(false);
    setSearchOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (searchOpen) searchInput.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false);
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [menuOpen]);

  const topCategories = categories.flatMap((node) => node.children ?? []).slice(0, 10);

  return (
    <header className={styles.header}>
      <div className={styles.top}>
        <div className={`container ${styles.topInner}`}>
          <button
            type="button"
            className={`${styles.iconButton} ${styles.burger}`}
            onClick={() => setMenuOpen(true)}
            aria-label="Открыть меню"
            aria-expanded={menuOpen}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
              <path d="M2 5h16M2 10h16M2 15h16" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>

          <Logo />
          <span className={styles.divider} aria-hidden="true" />
          <p className={styles.tagline}>
            Комплектующие
            <br />
            для детских площадок
          </p>

          <SearchBar
            className={`${styles.search} ${searchOpen ? styles.searchOpen : ''}`}
            inputRef={searchInput}
          />

          {phone ? (
            <div className={styles.phone}>
              <a href={`tel:${phone.tel}`} className={styles.phoneNumber}>
                {phone.display}
              </a>
              {hours || phone.label ? (
                <span className={styles.phoneHint}>
                  {[hours, phone.label].filter(Boolean).join(' · ')}
                </span>
              ) : null}
              {whatsapp ? (
                <a
                  href={whatsapp.url}
                  className={styles.whatsapp}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Написать в WhatsApp
                </a>
              ) : null}
            </div>
          ) : null}

          <button type="button" className={styles.quick} onClick={() => quickOrder.open()}>
            <span className={styles.quickMark} aria-hidden="true" />
            Быстрый заказ
          </button>

          <button
            type="button"
            className={`${styles.iconButton} ${styles.searchToggle}`}
            onClick={() => setSearchOpen((value) => !value)}
            aria-label={searchOpen ? 'Скрыть поиск' : 'Показать поиск'}
            aria-expanded={searchOpen}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </button>

          <button
            type="button"
            className={styles.cart}
            onClick={open}
            aria-label={cartCount > 0 ? `Корзина: ${cartCount}` : 'Корзина'}
          >
            <CartIcon />
            <span className={styles.cartLabel}>Корзина</span>
            {cartCount > 0 ? (
              <span className={styles.counter} aria-hidden="true">
                {formatCount(cartCount)}
              </span>
            ) : null}
          </button>
        </div>
      </div>

      <div className={styles.bar}>
        <div className={`container ${styles.barInner}`}>
          <nav className={styles.nav} aria-label="Основная навигация">
            {[NAV_PRIMARY, NAV_SECONDARY].map((group, index) => (
              <div
                key={index}
                className={index === 0 ? styles.navGroup : `${styles.navGroup} ${styles.navEnd}`}
              >
                {group.map((link) => {
                  const active = isNavActive(pathname, link.href);
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={
                        active ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink
                      }
                      aria-current={active ? 'page' : undefined}
                    >
                      {link.label}
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className={styles.barActions}>
            <Link
              href={favoritesHref}
              className={styles.barLink}
              aria-label={
                favoritesReady && favoritesCount > 0 ? `Избранное: ${favoritesCount}` : 'Избранное'
              }
              aria-current={isNavActive(pathname, favoritesHref) ? 'page' : undefined}
            >
              <HeartIcon />
              <span aria-hidden="true">Избранное</span>
              {favoritesReady && favoritesCount > 0 ? (
                <span className={styles.barCount} aria-hidden="true">
                  {formatCount(favoritesCount)}
                </span>
              ) : null}
            </Link>

            <Link
              href={cabinetHref}
              className={styles.login}
              aria-label={
                signedIn && unreadCount > 0
                  ? `Кабинет: непрочитанных уведомлений ${unreadCount}`
                  : undefined
              }
            >
              {signedIn ? 'Кабинет' : 'Войти'}
              {signedIn && unreadCount > 0 ? (
                <span className={styles.loginDot} aria-hidden="true" />
              ) : null}
            </Link>
          </div>
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
              <Logo className={styles.mobileLogo} />
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => setMenuOpen(false)}
                aria-label="Закрыть меню"
              >
                <svg width="16" height="16" viewBox="0 0 14 14" aria-hidden="true">
                  <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              </button>
            </div>

            <button
              type="button"
              className={styles.mobileQuick}
              onClick={() => {
                setMenuOpen(false);
                quickOrder.open();
              }}
            >
              <span className={styles.quickMark} aria-hidden="true" />
              Быстрый заказ
            </button>

            {[...NAV_LINKS, { href: favoritesHref, label: 'Избранное' }].map((link) => {
              const active = isNavActive(pathname, link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${styles.mobileLink} ${active ? styles.mobileLinkActive : ''}`}
                  aria-current={active ? 'page' : undefined}
                >
                  {link.label}
                </Link>
              );
            })}

            {topCategories.length > 0 ? (
              <div className={styles.mobileSection}>
                <span className={styles.mobileTitle}>Разделы каталога</span>
                {topCategories.map((category) => (
                  <Link
                    key={category.slug}
                    href={`/catalog/${category.slug}`}
                    className={styles.mobileLink}
                  >
                    {category.name}
                    <span className={styles.mobileCount}>
                      {formatCount(category.product_count ?? 0)}
                    </span>
                  </Link>
                ))}
              </div>
            ) : null}

            <div className={styles.mobileSection}>
              {phone ? (
                <a href={`tel:${phone.tel}`} className={styles.mobilePhone}>
                  {phone.display}
                  {hours ? <span className={styles.phoneHint}>{hours}</span> : null}
                </a>
              ) : null}
              <Link href={cabinetHref} className={styles.mobileLogin}>
                {signedIn ? 'Личный кабинет' : 'Войти в кабинет'}
              </Link>
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}
