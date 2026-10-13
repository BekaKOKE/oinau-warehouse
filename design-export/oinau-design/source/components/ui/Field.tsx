/**
 * Поля формы с подписью и сообщением об ошибке.
 *
 * Подпись всегда связана с полем через `htmlFor`, а ошибка — через
 * `aria-describedby` и `aria-invalid`: иначе средство чтения с экрана
 * произносит поле без объяснения, почему форма не отправилась.
 */

'use client';

import { useId } from 'react';
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';

import styles from './Field.module.css';

type FieldShellProps = {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: (props: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
};

export function Field({ label, required, hint, error, children }: FieldShellProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ');

  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
        {required ? (
          <span className={styles.required} aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children({ id, describedBy: describedBy || undefined, invalid: Boolean(error) })}
      {hint ? (
        <span className={styles.hint} id={hintId}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span className={styles.error} id={errorId} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

type BaseProps = { label: string; required?: boolean; hint?: string; error?: string };

export type TextFieldProps = BaseProps &
  Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'required'>;

export function TextField({ label, required, hint, error, className, ...rest }: TextFieldProps) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <input
          {...rest}
          id={id}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={[styles.control, invalid ? styles.invalid : '', className ?? '']
            .filter(Boolean)
            .join(' ')}
        />
      )}
    </Field>
  );
}

export type TextAreaFieldProps = BaseProps &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id' | 'required'>;

export function TextAreaField({
  label,
  required,
  hint,
  error,
  className,
  ...rest
}: TextAreaFieldProps) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <textarea
          {...rest}
          id={id}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={[styles.control, invalid ? styles.invalid : '', className ?? '']
            .filter(Boolean)
            .join(' ')}
        />
      )}
    </Field>
  );
}

export type SelectFieldProps = BaseProps &
  Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'required'> & { children: ReactNode };

export function SelectField({
  label,
  required,
  hint,
  error,
  className,
  children,
  ...rest
}: SelectFieldProps) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <select
          {...rest}
          id={id}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={[styles.control, invalid ? styles.invalid : '', className ?? '']
            .filter(Boolean)
            .join(' ')}
        >
          {children}
        </select>
      )}
    </Field>
  );
}

export { styles as fieldStyles };
