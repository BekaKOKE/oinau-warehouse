'use client';

/**
 * Модальные окна и подтверждение опасных действий.
 *
 * `useConfirm()` возвращает промис: код удаления читается сверху вниз
 * (`if (!(await confirm(...))) return;`) без вложенных колбэков.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

import { Button } from './Button';
import { Icon } from './Icon';
import styles from './Dialog.module.css';

type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  /** Боковая панель вместо окна по центру. */
  variant?: 'modal' | 'drawer';
  /** Запрет закрытия по Esc и клику мимо, пока идёт сохранение. */
  busy?: boolean;
};

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
// Без :is() со списком: его понимают не все движки селекторов.
const BODY_FOCUSABLE = FOCUSABLE.split(', ')
  .map((selector) => `[data-dialog-body] ${selector}`)
  .join(', ');

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  variant = 'modal',
  busy = false,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  // Колбэк и флаг читаются через ref: иначе эффект перезапускался бы на
  // каждый рендер родителя и уводил фокус из поля, в котором печатают.
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  onCloseRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const first =
      panel?.querySelector<HTMLElement>('[data-autofocus]') ??
      panel?.querySelector<HTMLElement>(BODY_FOCUSABLE);
    (first ?? panel)?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyRef.current) {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;
      // Фокус не уходит из окна на страницу под ним.
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl?.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className={`${styles.overlay} ${variant === 'drawer' ? styles.overlayDrawer : ''}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`${styles.panel} ${styles[size]} ${variant === 'drawer' ? styles.drawer : ''}`}
      >
        <div className={styles.header}>
          <div>
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className={styles.description}>
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            disabled={busy}
            aria-label="Закрыть"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        {children ? (
          <div className={styles.body} data-dialog-body>
            {children}
          </div>
        ) : null}
        {footer ? <div className={styles.footer}>{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------- подтверждение

export type ConfirmOptions = {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'primary';
};

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<
    (ConfirmOptions & { resolve: (value: boolean) => void }) | null
  >(null);

  const confirm = useCallback<ConfirmFn>(
    (options) => new Promise<boolean>((resolve) => setState({ ...options, resolve })),
    [],
  );

  const close = useCallback(
    (result: boolean) => {
      state?.resolve(result);
      setState(null);
    },
    [state],
  );

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Dialog
        open={state !== null}
        onClose={() => close(false)}
        title={state?.title ?? ''}
        description={state?.description}
        size="sm"
        footer={
          <>
            {/* Фокус — на «Отмена»: Enter по привычке не должен удалять. */}
            <Button variant="secondary" onClick={() => close(false)} data-autofocus>
              {state?.cancelLabel ?? 'Отмена'}
            </Button>
            <Button
              variant={state?.tone === 'primary' ? 'primary' : 'danger'}
              onClick={() => close(true)}
            >
              {state?.confirmLabel ?? 'Подтвердить'}
            </Button>
          </>
        }
      />
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('useConfirm вызван вне ConfirmProvider');
  return context;
}
