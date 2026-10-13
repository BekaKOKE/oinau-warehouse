'use client';

/**
 * Пропускает в админку только вошедшего сотрудника.
 *
 * Это не защита данных — данные защищает backend, и без токена ни один
 * запрос не пройдёт. Шлюз избавляет от мигания пустых экранов с ошибкой
 * 401 и возвращает сотрудника туда, откуда его выбросило.
 */

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { ErrorState, ForbiddenState } from '@/components/ui/States';
import { Spinner } from '@/components/ui/Spinner';
import type { PermissionCode } from '@/lib/auth/permissions';

import { useSession } from './SessionProvider';
import styles from './AuthGate.module.css';

function currentLocation(pathname: string): string {
  // pathname из next/navigation — уже без basePath; query берём из адреса.
  const search = typeof window === 'undefined' ? '' : window.location.search;
  return `${pathname}${search}`;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const { status, error, reload, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === 'anonymous') {
      const next = currentLocation(pathname);
      router.replace(next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`);
    }
  }, [status, pathname, router]);

  if (status === 'authenticated') return <>{children}</>;

  if (status === 'error') {
    return (
      <div className={styles.screen}>
        <div className={styles.box}>
          <ErrorState error={error} onRetry={reload} />
          <Button variant="ghost" size="sm" onClick={() => void logout()}>
            Войти под другим пользователем
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.screen} role="status" aria-live="polite">
      <Spinner size={22} />
      <span className="visually-hidden">Проверяем сессию…</span>
    </div>
  );
}

/** Раздел целиком недоступен без прав — вместо экрана показывается причина. */
export function RequirePermission({
  all,
  children,
}: {
  all: readonly PermissionCode[];
  children: ReactNode;
}) {
  const { can } = useSession();
  if (!can(...all)) {
    return (
      <div className={styles.forbidden}>
        <ForbiddenState />
      </div>
    );
  }
  return <>{children}</>;
}
