/**
 * Короткие уведомления об успехе и ошибке действия.
 *
 * Живут в регионе `role="status"` / `role="alert"`: средство чтения
 * с экрана объявит «Профиль сохранён», не перемещая фокус.
 */

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import styles from './Cabinet.module.css';

type ToastTone = 'success' | 'error';
type Toast = { id: number; tone: ToastTone; text: string };

type ToastApi = {
  success: (text: string) => void;
  error: (text: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const TOAST_TTL_MS = 4500;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const push = useCallback(
    (tone: ToastTone, text: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-2), { id, tone, text }]);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), TOAST_TTL_MS),
      );
    },
    [dismiss],
  );

  useEffect(() => {
    const active = timers.current;
    return () => active.forEach((timer) => clearTimeout(timer));
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (text) => push('success', text),
      error: (text) => push('error', text),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.toasts}>
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`${styles.toast} ${toast.tone === 'error' ? styles.toastError : styles.toastSuccess}`}
            role={toast.tone === 'error' ? 'alert' : 'status'}
          >
            <span className={styles.toastDot} aria-hidden="true" />
            <span className={styles.toastText}>{toast.text}</span>
            <button
              type="button"
              className={styles.toastClose}
              onClick={() => dismiss(toast.id)}
              aria-label="Закрыть уведомление"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast используется вне ToastProvider');
  return context;
}
