'use client';

/**
 * Уведомления о результате действия («Товар сохранён»).
 *
 * Ошибки живут дольше успехов: их нужно успеть прочитать, а код
 * запроса — переписать в сообщение разработчику.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { describeError } from '@/lib/errors';

import { Icon } from './Icon';
import styles from './Toast.module.css';

export type ToastTone = 'success' | 'error' | 'info';

type ToastItem = { id: number; tone: ToastTone; title: string; description?: string };

type ToastApi = {
  show: (toast: Omit<ToastItem, 'id'>) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, error?: unknown) => void;
  info: (title: string, description?: string) => void;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const DURATION: Record<ToastTone, number> = { success: 3500, info: 4500, error: 8000 };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const show = useCallback(
    (toast: Omit<ToastItem, 'id'>) => {
      const id = nextId.current++;
      // Не больше четырёх одновременно: старые уходят первыми.
      setItems((current) => [...current.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), DURATION[toast.tone]);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      dismiss,
      success: (title, description) => show({ tone: 'success', title, description }),
      info: (title, description) => show({ tone: 'info', title, description }),
      error: (title, error) =>
        show({
          tone: 'error',
          title,
          description: error === undefined ? undefined : describeError(error),
        }),
    }),
    [show, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.viewport} aria-live="polite" aria-relevant="additions">
        {items.map((item) => (
          <div
            key={item.id}
            className={`${styles.toast} ${styles[item.tone]}`}
            role={item.tone === 'error' ? 'alert' : 'status'}
          >
            <span className={styles.icon}>
              <Icon
                name={item.tone === 'success' ? 'check' : item.tone === 'error' ? 'alert' : 'info'}
                size={16}
              />
            </span>
            <div className={styles.body}>
              <p className={styles.title}>{item.title}</p>
              {item.description ? <p className={styles.description}>{item.description}</p> : null}
            </div>
            <button
              type="button"
              className={styles.close}
              onClick={() => dismiss(item.id)}
              aria-label="Закрыть уведомление"
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast вызван вне ToastProvider');
  return context;
}
