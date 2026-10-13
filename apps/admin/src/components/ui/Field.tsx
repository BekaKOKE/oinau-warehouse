'use client';

/**
 * Поля форм.
 *
 * `Field` связывает подпись, подсказку и ошибку с полем через id и
 * aria-атрибуты: ошибка backend (422) должна читаться и глазами,
 * и скринридером, а не только красной рамкой.
 */

import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

import styles from './Field.module.css';

type ControlProps = {
  id?: string;
  'aria-invalid'?: boolean;
  'aria-describedby'?: string;
};

type FieldProps = {
  label: ReactNode;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  className?: string;
  children: ReactElement<ControlProps>;
};

export function Field({ label, hint, error, required, className, children }: FieldProps) {
  const generated = useId();
  const id = (isValidElement(children) && children.props.id) || generated;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {required ? (
          <span className={styles.required} aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {cloneElement(children, {
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })}
      {hint && !error ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={[styles.control, className].filter(Boolean).join(' ')}
        {...rest}
      />
    );
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, rows = 4, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={[styles.control, styles.textarea, className].filter(Boolean).join(' ')}
      {...rest}
    />
  );
});

export type SelectOption = { value: string; label: string };

type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> & {
  options: readonly SelectOption[];
  /** Пустой вариант первым пунктом («Все статусы»). */
  placeholder?: string;
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, options, placeholder, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={[styles.control, styles.select, className].filter(Boolean).join(' ')}
      {...rest}
    >
      {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
});

type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode };

export function Checkbox({ label, className, ...rest }: CheckboxProps) {
  return (
    <label className={[styles.checkbox, className].filter(Boolean).join(' ')}>
      <input type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
}

type SwitchProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'role'> & {
  label: ReactNode;
  description?: ReactNode;
};

export function Switch({ label, description, className, ...rest }: SwitchProps) {
  return (
    <label className={[styles.switch, className].filter(Boolean).join(' ')}>
      <input type="checkbox" role="switch" {...rest} />
      <span className={styles.track} aria-hidden="true" />
      <span className={styles.switchText}>
        <span>{label}</span>
        {description ? <span className={styles.hint}>{description}</span> : null}
      </span>
    </label>
  );
}
