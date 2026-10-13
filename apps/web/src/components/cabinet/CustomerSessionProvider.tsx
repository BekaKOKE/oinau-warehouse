/**
 * Состояние входа клиента для всего сайта.
 *
 * Шапке нужно знать, показывать «Войти» или «Кабинет», избранному —
 * хранить сердечки в браузере или в аккаунте, кабинету — кого пускать.
 * Токены здесь не хранятся: они в `lib/cabinet/session`, провайдер
 * держит только профиль и статус.
 */

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import type { CustomerProfile } from '@oinau/api-types';

import { fetchProfile, fetchUnreadCount } from '@/lib/api/customer';
import { loginCustomer, logoutCustomer } from '@/lib/api/customer-auth';
import {
  clearSession,
  getAccessToken,
  hasSessionHint,
  subscribeSession,
} from '@/lib/cabinet/session';
import { isUnauthenticated } from '@/lib/cabinet/format';

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous' | 'error';

type SessionState = {
  status: SessionStatus;
  profile: CustomerProfile | null;
  unreadCount: number;
  login: (email: string, password: string) => Promise<CustomerProfile>;
  logout: () => Promise<void>;
  /** Повторить восстановление сессии после сетевой ошибки. */
  retry: () => void;
  setProfile: (profile: CustomerProfile) => void;
  refreshUnread: () => Promise<void>;
  setUnreadCount: (count: number) => void;
};

const SessionContext = createContext<SessionState | null>(null);

export function CustomerSessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [profile, setProfileState] = useState<CustomerProfile | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [attempt, setAttempt] = useState(0);

  const refreshUnread = useCallback(async () => {
    try {
      const result = await fetchUnreadCount();
      setUnreadCount(result.unread);
    } catch {
      // Счётчик вторичен: его сбой не должен ломать кабинет.
    }
  }, []);

  // Восстановление сессии при загрузке страницы. Анонимный посетитель
  // (нет признака входа) в API не обращается вовсе.
  useEffect(() => {
    let cancelled = false;
    if (!hasSessionHint()) {
      setStatus('anonymous');
      return;
    }
    setStatus('loading');
    (async () => {
      try {
        const token = await getAccessToken();
        if (!token) {
          if (!cancelled) setStatus('anonymous');
          return;
        }
        const loaded = await fetchProfile();
        if (cancelled) return;
        setProfileState(loaded);
        setStatus('authenticated');
        void refreshUnread();
      } catch (error) {
        if (cancelled) return;
        if (isUnauthenticated(error)) {
          clearSession();
          setStatus('anonymous');
        } else {
          setStatus('error');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt, refreshUnread]);

  // Сессию могли потерять без участия провайдера: refresh отклонён
  // посреди работы, пароль сменён по ссылке.
  useEffect(
    () =>
      subscribeSession((authenticated) => {
        if (!authenticated) {
          setProfileState(null);
          setUnreadCount(0);
          setStatus('anonymous');
        }
      }),
    [],
  );

  const login = useCallback<SessionState['login']>(
    async (email, password) => {
      await loginCustomer({ email, password });
      const loaded = await fetchProfile();
      setProfileState(loaded);
      setStatus('authenticated');
      void refreshUnread();
      return loaded;
    },
    [refreshUnread],
  );

  const logout = useCallback(async () => {
    try {
      await logoutCustomer();
    } catch {
      // Локальная сессия уже очищена в logoutCustomer.
    }
    setProfileState(null);
    setUnreadCount(0);
    setStatus('anonymous');
  }, []);

  const value = useMemo<SessionState>(
    () => ({
      status,
      profile,
      unreadCount,
      login,
      logout,
      retry: () => setAttempt((value) => value + 1),
      setProfile: setProfileState,
      refreshUnread,
      setUnreadCount,
    }),
    [status, profile, unreadCount, login, logout, refreshUnread],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useCustomerSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useCustomerSession используется вне CustomerSessionProvider');
  }
  return context;
}
