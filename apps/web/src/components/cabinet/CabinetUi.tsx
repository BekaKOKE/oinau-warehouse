/**
 * Мелкие общие элементы кабинета: заголовок страницы, статус,
 * постраничная навигация, диалоги, поле пароля, сообщение формы.
 */

'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { pageWindow } from '@/components/catalog/Pagination';
import { Button } from '@/components/ui/Button';
import { Field, fieldStyles } from '@/components/ui/Field';
import { Skeleton } from '@/components/ui/States';
import type { Tone } from '@/lib/cabinet/format';
import { formatCount } from '@/lib/format';
import styles from './Cabinet.module.css';

export function PageHead({
  title,
  lead,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  lead?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className={styles.pageHead}>
      <div className={styles.pageHeadText}>
        {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
        <h1 className={styles.pageTitle}>{title}</h1>
        {lead ? <p className={styles.pageLead}>{lead}</p> : null}
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </header>
  );
}

export function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  return <span className={`${styles.badge} ${styles[`tone_${tone}`]}`}>{label}</span>;
}

export function FormAlert({
  tone = 'error',
  children,
}: {
  tone?: 'error' | 'success' | 'info';
  children: ReactNode;
}) {
  return (
    <div
      className={`${styles.alert} ${styles[`alert_${tone}`]}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      {children}
    </div>
  );
}

/** Постраничная навигация ссылками `?page=N`: работает «назад» и новая вкладка. */
export function CabinetPagination({
  basePath,
  page,
  pages,
  total,
  shown,
  extraQuery,
}: {
  basePath: string;
  page: number;
  pages: number;
  total: number;
  shown: number;
  extraQuery?: Record<string, string | undefined>;
}) {
  if (pages <= 1) return null;

  const href = (target: number) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(extraQuery ?? {})) {
      if (value) params.set(key, value);
    }
    if (target > 1) params.set('page', String(target));
    const query = params.toString();
    return query ? `${basePath}?${query}` : basePath;
  };

  return (
    <nav className={styles.pagination} aria-label="Страницы списка">
      <div className={styles.pages}>
        {page > 1 ? (
          <Link href={href(page - 1)} className={styles.pageLink} aria-label="Предыдущая страница">
            ‹
          </Link>
        ) : (
          <span className={`${styles.pageLink} ${styles.pageDisabled}`} aria-hidden="true">
            ‹
          </span>
        )}
        {pageWindow(page, pages).map((item, index) =>
          item === 'gap' ? (
            <span key={`gap-${index}`} className={styles.pageGap} aria-hidden="true">
              …
            </span>
          ) : (
            <Link
              key={item}
              href={href(item)}
              className={`${styles.pageLink} ${item === page ? styles.pageActive : ''}`}
              aria-current={item === page ? 'page' : undefined}
              aria-label={`Страница ${item}`}
            >
              {item}
            </Link>
          ),
        )}
        {page < pages ? (
          <Link href={href(page + 1)} className={styles.pageLink} aria-label="Следующая страница">
            ›
          </Link>
        ) : (
          <span className={`${styles.pageLink} ${styles.pageDisabled}`} aria-hidden="true">
            ›
          </span>
        )}
      </div>
      <p className={styles.pageInfo}>
        Показано {formatCount(shown)} из {formatCount(total)}
      </p>
    </nav>
  );
}

/** Скелетон списка строк на время загрузки. */
export function RowsSkeleton({ rows = 4, height = '64px' }: { rows?: number; height?: string }) {
  return (
    <div className={styles.rowsSkeleton} aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} height={height} />
      ))}
    </div>
  );
}

/**
 * Модальное окно.
 *
 * Escape и клик по подложке закрывают окно, фокус переходит внутрь
 * и возвращается на прежний элемент после закрытия — без этого
 * клавиатурный пользователь теряется на странице.
 */
export function Modal({
  title,
  onClose,
  children,
  footer,
  busy = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  busy?: boolean;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const focusable = panel.current?.querySelector<HTMLElement>(
      'input, select, textarea, button:not([data-modal-close])',
    );
    (focusable ?? panel.current)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busyRef.current) closeRef.current();
    }
    document.addEventListener('keydown', onKeyDown);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, []);

  return (
    <div
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={panel}
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={styles.modalHead}>
          <h2 id={titleId} className={styles.modalTitle}>
            {title}
          </h2>
          <button
            type="button"
            className={styles.modalClose}
            onClick={onClose}
            disabled={busy}
            aria-label="Закрыть"
            data-modal-close
          >
            ×
          </button>
        </div>
        <div className={styles.modalBody}>{children}</div>
        {footer ? <div className={styles.modalFooter}>{footer}</div> : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  text,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
}: {
  title: string;
  text: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      busy={busy}
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Отмена
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy} aria-busy={busy}>
            {busy ? 'Удаляем…' : confirmLabel}
          </Button>
        </>
      }
    >
      <p className={styles.modalText}>{text}</p>
    </Modal>
  );
}

export function PasswordField({
  label,
  value,
  onChange,
  error,
  hint,
  autoComplete,
  name,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: string;
  autoComplete: 'current-password' | 'new-password';
  name: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <Field label={label} required hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <div className={styles.passwordWrap}>
          <input
            id={id}
            name={name}
            type={visible ? 'text' : 'password'}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            autoComplete={autoComplete}
            required
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={[
              fieldStyles.control,
              invalid ? fieldStyles.invalid : '',
              styles.passwordInput,
            ]
              .filter(Boolean)
              .join(' ')}
          />
          <button
            type="button"
            className={styles.passwordToggle}
            onClick={() => setVisible((current) => !current)}
            aria-label={visible ? 'Скрыть пароль' : 'Показать пароль'}
            aria-pressed={visible}
          >
            {visible ? 'Скрыть' : 'Показать'}
          </button>
        </div>
      )}
    </Field>
  );
}
