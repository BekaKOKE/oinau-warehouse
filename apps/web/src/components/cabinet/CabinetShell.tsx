/**
 * Каркас кабинета: проверка входа, боковое меню и область содержимого.
 *
 * Страницы кабинета рисуются в браузере: их данные принадлежат
 * конкретному клиенту и требуют access-токена, которого у сервера
 * Next.js нет (и не должно быть). Гостя отправляет на вход с адресом
 * возврата.
 *
 * На телефоне боковое меню превращается в компактную кнопку с текущим
 * разделом, раскрывающую тот же список.
 */

'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState, type ReactNode } from 'react';

import { useFavorites } from '@/components/favorites/FavoritesProvider';
import { Button } from '@/components/ui/Button';
import { ErrorState, Skeleton } from '@/components/ui/States';
import {
  CABINET_LOGIN,
  CABINET_NAV,
  isCabinetNavActive,
  loginHref,
  type CabinetSection,
} from '@/lib/cabinet/navigation';
import { formatCount } from '@/lib/format';
import { useCustomerSession } from './CustomerSessionProvider';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

const ICONS: Record<CabinetSection, ReactNode> = {
  overview: <path d="M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z" />,
  requests: <path d="M3.5 2h9v12h-9zM6 5h4M6 8h4M6 11h2.5" />,
  projects: <path d="M2 4.5h4.5L8 6h6v7.5H2z" />,
  favorites: (
    <path d="M8 13.5S2 10 2 6.1A3.1 3.1 0 0 1 8 4.6a3.1 3.1 0 0 1 6 1.5C14 10 8 13.5 8 13.5Z" />
  ),
  notifications: <path d="M4 11V7a4 4 0 1 1 8 0v4l1.2 1.5H2.8zM6.5 14a1.6 1.6 0 0 0 3 0" />,
  profile: <path d="M8 8a2.8 2.8 0 1 0 0-5.6A2.8 2.8 0 0 0 8 8Zm-5 6a5 5 0 0 1 10 0" />,
};

function NavIcon({ section }: { section: CabinetSection }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinejoin="round"
      strokeLinecap="round"
      aria-hidden="true"
    >
      {ICONS[section]}
    </svg>
  );
}

export function CabinetShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { status, profile, unreadCount, logout, retry } = useCustomerSession();
  const { count: favoritesCount, ready: favoritesReady } = useFavorites();
  const [menuOpen, setMenuOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const leavingRef = useRef(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (status === 'anonymous' && !leavingRef.current) {
      router.replace(loginHref(pathname));
    }
  }, [status, pathname, router]);

  async function handleLogout() {
    leavingRef.current = true;
    setLeaving(true);
    await logout();
    toast.success('Вы вышли из кабинета');
    router.replace(CABINET_LOGIN);
  }

  if (status === 'error') {
    return (
      <div className={styles.shellSingle}>
        <ErrorState
          title="Кабинет временно недоступен"
          text="Не удалось связаться с сервером. Проверьте подключение и попробуйте ещё раз."
          action={<Button onClick={retry}>Повторить</Button>}
        />
      </div>
    );
  }

  if (status !== 'authenticated' || !profile) {
    return (
      <div className={styles.shell} aria-busy="true">
        <div className={`${styles.sidebar} ${styles.sidebarSkeleton}`}>
          <Skeleton height="44px" />
          <Skeleton height="220px" />
        </div>
        <div className={styles.content}>
          <Skeleton height="34px" width="40%" />
          <Skeleton height="120px" />
          <Skeleton height="240px" />
        </div>
      </div>
    );
  }

  const counters: Partial<Record<CabinetSection, number>> = {
    favorites: favoritesReady ? favoritesCount : 0,
    notifications: unreadCount,
  };
  const current = CABINET_NAV.find((link) => isCabinetNavActive(pathname, link.href));

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarUser}>
          <span className={styles.avatar} aria-hidden="true">
            {(profile.contact_name.trim()[0] ?? '?').toUpperCase()}
          </span>
          <div className={styles.sidebarUserText}>
            <p className={styles.sidebarName}>{profile.company_name || profile.contact_name}</p>
            <p className={styles.sidebarEmail}>{profile.email}</p>
          </div>
        </div>

        <button
          type="button"
          className={styles.menuToggle}
          onClick={() => setMenuOpen((value) => !value)}
          aria-expanded={menuOpen}
          aria-controls="cabinet-nav"
        >
          <span className={styles.menuToggleLabel}>
            {current ? <NavIcon section={current.key} /> : null}
            {current?.label ?? 'Разделы кабинета'}
          </span>
          <span className={styles.menuToggleHint}>
            {/* Точка, а не число: цифра рядом с названием раздела читалась
                бы как счётчик этого раздела. */}
            {unreadCount > 0 ? (
              <span
                className={styles.menuToggleDot}
                role="img"
                aria-label={`непрочитанных уведомлений: ${unreadCount}`}
              />
            ) : null}
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              aria-hidden="true"
              className={menuOpen ? styles.chevronOpen : styles.chevron}
            >
              <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </span>
        </button>

        <nav
          id="cabinet-nav"
          className={`${styles.nav} ${menuOpen ? styles.navOpen : ''}`}
          aria-label="Разделы кабинета"
        >
          {CABINET_NAV.map((link) => {
            const active = isCabinetNavActive(pathname, link.href);
            const counter = counters[link.key] ?? 0;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`${styles.navLink} ${active ? styles.navLinkActive : ''}`}
                aria-current={active ? 'page' : undefined}
              >
                <NavIcon section={link.key} />
                <span className={styles.navLabel}>{link.label}</span>
                {counter > 0 ? (
                  <span
                    className={
                      link.key === 'notifications' ? styles.navCounterAccent : styles.navCounter
                    }
                    aria-label={
                      link.key === 'notifications' ? `непрочитанных: ${counter}` : `${counter}`
                    }
                  >
                    {formatCount(counter)}
                  </span>
                ) : null}
              </Link>
            );
          })}

          <div className={styles.navFooter}>
            <Link href="/catalog" className={styles.navSecondary}>
              Перейти в каталог
            </Link>
            <button
              type="button"
              className={styles.logout}
              onClick={handleLogout}
              disabled={leaving}
            >
              {leaving ? 'Выходим…' : 'Выйти'}
            </button>
          </div>
        </nav>
      </aside>

      <div className={styles.content}>{children}</div>
    </div>
  );
}
