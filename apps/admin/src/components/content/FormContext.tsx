'use client';

/**
 * Общее состояние формы раздела для полей: ошибки, режим только чтения,
 * показ казахской версии.
 *
 * Поля регистрируют свои пути: ошибка backend по пути, для которого на
 * экране нет поля, не должна потеряться — её покажет сводка над формой.
 */

import { createContext, useContext, useEffect, useId, useState, type ReactNode } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Icon } from '@/components/ui/Icon';
import { pathWithin } from '@/lib/content/errors';
import type { FieldErrors } from '@/lib/errors';

import styles from './Content.module.css';

export type ContentFormContextValue = {
  errors: FieldErrors;
  disabled: boolean;
  showKk: boolean;
  clearErrors: (prefix: string) => void;
  register: (path: string) => () => void;
};

const Context = createContext<ContentFormContextValue | null>(null);

export const ContentFormProvider = Context.Provider;

export function useContentForm(): ContentFormContextValue {
  const value = useContext(Context);
  if (!value) throw new Error('Поле CMS вне формы раздела');
  return value;
}

/** Регистрирует путь поля и отдаёт его ошибку. */
export function useFieldError(path: string): string | undefined {
  const { errors, register } = useContentForm();
  useEffect(() => register(path), [path, register]);
  return errors[path];
}

// --------------------------------------------------------------- панель

type PanelProps = {
  title: string;
  description?: ReactNode;
  /** Пути полей панели: при ошибке внутри панель раскрывается сама. */
  paths: readonly string[];
  defaultOpen?: boolean;
  summary?: ReactNode;
  children: ReactNode;
};

/** Сворачиваемый блок длинной формы. Содержимое не размонтируется. */
export function Panel({
  title,
  description,
  paths,
  defaultOpen = true,
  summary,
  children,
}: PanelProps) {
  const { errors } = useContentForm();
  const bodyId = useId();
  const [open, setOpen] = useState(defaultOpen);
  const hasError = Object.keys(errors).some((key) => pathWithin(key, paths));

  useEffect(() => {
    if (hasError) setOpen(true);
  }, [hasError]);

  return (
    <section className={styles.panel}>
      <h2 className={styles.panelHeading}>
        <button
          type="button"
          className={styles.panelToggle}
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((value) => !value)}
        >
          <span className={styles.panelText}>
            <span className={styles.panelTitle}>{title}</span>
            {description ? <span className={styles.panelDescription}>{description}</span> : null}
          </span>
          <span className={styles.panelMeta}>
            {hasError ? (
              <Badge tone="danger">Есть ошибки</Badge>
            ) : summary ? (
              <span className={styles.panelSummary}>{summary}</span>
            ) : null}
            <Icon name={open ? 'chevronUp' : 'chevronDown'} size={16} />
          </span>
        </button>
      </h2>
      <div id={bodyId} className={styles.panelBody} hidden={!open}>
        {children}
      </div>
    </section>
  );
}

/** Ошибка уровня группы полей (например, «кнопка без ссылки» от backend). */
export function GroupError({ path }: { path: string }) {
  const error = useFieldError(path);
  if (!error) return null;
  return (
    <p className={styles.groupError} role="alert">
      <Icon name="alert" size={14} /> {error}
    </p>
  );
}
