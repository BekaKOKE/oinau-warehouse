'use client';

/**
 * Текущий сотрудник и его права для всего интерфейса.
 *
 * Профиль и список прав берутся из GET /admin/auth/me и перечитываются
 * при каждом входе в приложение: роль могли сменить, пока вкладка была
 * закрыта. Решения «можно ли» принимает backend — провайдер лишь
 * помогает не показывать заведомо недоступное.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { authApi } from '@/lib/api/endpoints';
import type { CurrentUser } from '@/lib/api/types';
import { hasAll, type PermissionCode } from '@/lib/auth/permissions';
import {
  hasSessionHint,
  login as loginRequest,
  logout as logoutRequest,
  subscribeSession,
  UnauthenticatedError,
  watchOtherTabs,
} from '@/lib/auth/session';

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous' | 'error';

type SessionContextValue = {
  status: SessionStatus;
  user: CurrentUser | null;
  permissions: ReadonlySet<string>;
  error: unknown;
  can: (...required: PermissionCode[]) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

const EMPTY: ReadonlySet<string> = new Set();

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!hasSessionHint()) {
      setStatus('anonymous');
      return;
    }
    setStatus('loading');
    authApi
      .me()
      .then((profile) => {
        if (cancelled) return;
        setUser(profile);
        setStatus('authenticated');
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        if (reason instanceof UnauthenticatedError) {
          setUser(null);
          setStatus('anonymous');
        } else {
          setError(reason);
          setStatus('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  useEffect(() => {
    const unsubscribe = subscribeSession((authenticated) => {
      if (!authenticated) {
        setUser(null);
        setStatus('anonymous');
      }
    });
    const unwatch = watchOtherTabs();
    return () => {
      unsubscribe();
      unwatch();
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await loginRequest(email, password);
    const profile = await authApi.me();
    setUser(profile);
    setError(null);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  const permissions = useMemo<ReadonlySet<string>>(
    () => (user ? new Set(user.permissions) : EMPTY),
    [user],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      user,
      permissions,
      error,
      can: (...required) => hasAll(permissions, required),
      login,
      logout,
      reload,
    }),
    [status, user, permissions, error, login, logout, reload],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession вызван вне SessionProvider');
  return context;
}
