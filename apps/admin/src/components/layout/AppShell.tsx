'use client';

/**
 * Каркас рабочей области: боковая навигация, верхняя панель, контент.
 *
 * Пункты навигации фильтруются правами текущего сотрудника
 * (`lib/navigation.ts`). На узком экране навигация выезжает поверх
 * контента и закрывается при переходе.
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { BrandLogo } from '@/components/ui/BrandLogo';
import { Icon } from '@/components/ui/Icon';
import { useToast } from '@/components/ui/Toast';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { SITE_URL } from '@/lib/config';
import { isNavActive, visibleNav } from '@/lib/navigation';

import styles from './AppShell.module.css';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, permissions, logout } = useSession();
  const pathname = usePathname();
  const toast = useToast();
  const [navOpen, setNavOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    setNavOpen(false);
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape') return;
      if (event instanceof MouseEvent && (event.target as HTMLElement).closest('[data-user-menu]'))
        return;
      setMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [menuOpen]);

  const groups = visibleNav(permissions);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logout();
    } catch (error) {
      // Локальная сессия всё равно забыта; сервер отзовёт токен по сроку.
      toast.error('Выход выполнен без связи с сервером', error);
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className={styles.shell}>
      <aside
        className={`${styles.sidebar} ${navOpen ? styles.sidebarOpen : ''}`}
        aria-label="Разделы"
      >
        <div className={styles.brand}>
          <Link href="/" className={styles.brandLink} aria-label="OINAU PRO — панель управления">
            <BrandLogo tone="white" height={24} />
            <span className={styles.brandSub}>Панель управления</span>
          </Link>
          <button
            type="button"
            className={styles.navClose}
            onClick={() => setNavOpen(false)}
            aria-label="Закрыть меню"
          >
            <Icon name="close" />
          </button>
        </div>

        <nav className={styles.nav}>
          {groups.map((group, index) => (
            <div key={group.title ?? `group-${index}`} className={styles.group}>
              {group.title ? <p className={styles.groupTitle}>{group.title}</p> : null}
              <ul>
                {group.items.map((item) => {
                  const active = isNavActive(item, pathname);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={`${styles.navLink} ${active ? styles.navLinkActive : ''}`}
                        aria-current={active ? 'page' : undefined}
                      >
                        <Icon name={item.icon} />
                        <span>{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <a className={styles.siteLink} href={SITE_URL} target="_blank" rel="noreferrer">
          <Icon name="external" size={16} />
          Открыть сайт
        </a>
      </aside>

      {navOpen ? (
        <div className={styles.backdrop} onClick={() => setNavOpen(false)} aria-hidden="true" />
      ) : null}

      <div className={styles.main}>
        <header className={styles.topbar}>
          <button
            type="button"
            className={styles.menuButton}
            onClick={() => setNavOpen(true)}
            aria-label="Открыть меню"
          >
            <Icon name="menu" />
          </button>
          <Link href="/" className={styles.mobileBrand} aria-label="OINAU PRO — на главную панели">
            <BrandLogo height={22} />
          </Link>
          <div className={styles.topbarSpacer} />
          {user ? (
            <div className={styles.userMenu} data-user-menu>
              <button
                type="button"
                className={styles.userButton}
                onClick={() => setMenuOpen((open) => !open)}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
              >
                <span className={styles.avatar} aria-hidden="true">
                  {initials(user.full_name)}
                </span>
                <span className={styles.userText}>
                  <span className={styles.userName}>{user.full_name}</span>
                  <span className={styles.userRole}>{ROLE_LABELS[user.role]}</span>
                </span>
                <Icon name="chevronDown" size={16} />
              </button>
              {menuOpen ? (
                <div className={styles.dropdown} role="menu">
                  <div className={styles.dropdownHeader}>
                    <span className={styles.userName}>{user.full_name}</span>
                    <span className={styles.userEmail}>{user.email}</span>
                  </div>
                  <button
                    type="button"
                    role="menuitem"
                    className={styles.dropdownItem}
                    onClick={() => void handleLogout()}
                    disabled={loggingOut}
                  >
                    <Icon name="logout" size={16} />
                    {loggingOut ? 'Выходим…' : 'Выйти'}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </header>
        <main className={styles.content} id="main">
          {children}
        </main>
      </div>
    </div>
  );
}
