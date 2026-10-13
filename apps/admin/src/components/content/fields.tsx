'use client';

/**
 * Поля разделов CMS.
 *
 * Весь текст — простой: обычные input/textarea без визуального редактора.
 * Абзацы — переводы строк, оформление остаётся за витриной.
 */

import { useEffect, useRef, type ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Field, Input, Select, Textarea, type SelectOption } from '@/components/ui/Field';
import { EmptyState } from '@/components/ui/States';
import {
  DEFAULT_LOCALE,
  EXTRA_LOCALE,
  TEXT_LIMITS,
  TEXT_MULTILINE,
  type Loc,
  type TextKind,
} from '@/lib/content/fields';
import { formatCount } from '@/lib/format';

import { GroupError, useContentForm, useFieldError } from './FormContext';
import styles from './Content.module.css';

function counterHint(value: string, limit: number): string | null {
  const length = Array.from(value.trim()).length;
  // Счётчик нужен, когда предел близко; на коротком тексте он только шумит.
  return length >= limit * 0.8 ? `${formatCount(length)} из ${formatCount(limit)}` : null;
}

type LocFieldProps = {
  label: string;
  path: string;
  value: Loc;
  onChange: (value: Loc) => void;
  kind: TextKind;
  required?: boolean;
  hint?: ReactNode;
  placeholder?: string;
  rows?: number;
};

/** Локализованный текст: русская версия всегда, казахская — по переключателю. */
export function LocField({
  label,
  path,
  value,
  onChange,
  kind,
  required,
  hint,
  placeholder,
  rows,
}: LocFieldProps) {
  const { disabled, showKk, clearErrors } = useContentForm();
  const ruError = useFieldError(path);
  const kkPath = `${path}.${EXTRA_LOCALE}`;
  const kkError = useFieldError(kkPath);
  const limit = TEXT_LIMITS[kind];
  const multiline = TEXT_MULTILINE[kind];

  const control = (locale: string, errorPath: string) => {
    const text = value[locale] ?? '';
    const common = {
      value: text,
      disabled,
      placeholder: locale === DEFAULT_LOCALE ? placeholder : undefined,
      lang: locale,
      onChange: (event: { target: { value: string } }) => {
        onChange({ ...value, [locale]: event.target.value });
        clearErrors(errorPath);
      },
    };
    return multiline ? (
      <Textarea {...common} rows={rows ?? (kind === 'text' ? 5 : 3)} />
    ) : (
      <Input {...common} />
    );
  };

  const ruText = value[DEFAULT_LOCALE] ?? '';
  return (
    <div className={styles.locField}>
      <Field
        label={showKk ? `${label} · RU` : label}
        required={required}
        hint={counterHint(ruText, limit) ?? hint}
        error={ruError}
      >
        {control(DEFAULT_LOCALE, path)}
      </Field>
      {showKk ? (
        <Field
          label={`${label} · KK`}
          hint={counterHint(value[EXTRA_LOCALE] ?? '', limit) ?? 'Необязательно'}
          error={kkError}
          className={styles.kkField}
        >
          {control(EXTRA_LOCALE, kkPath)}
        </Field>
      ) : null}
    </div>
  );
}

type TextFieldProps = {
  label: string;
  path: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  hint?: ReactNode;
  placeholder?: string;
  type?: 'text' | 'email' | 'tel' | 'url';
  inputMode?: 'text' | 'numeric' | 'decimal' | 'tel' | 'email' | 'url';
  mono?: boolean;
};

export function TextField({
  label,
  path,
  value,
  onChange,
  required,
  hint,
  placeholder,
  type = 'text',
  inputMode,
  mono,
}: TextFieldProps) {
  const { disabled, clearErrors } = useContentForm();
  const error = useFieldError(path);
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      <Input
        type={type}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        inputMode={inputMode}
        className={mono ? 'mono' : undefined}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => {
          onChange(event.target.value);
          clearErrors(path);
        }}
      />
    </Field>
  );
}

export function SelectField({
  label,
  path,
  value,
  options,
  placeholder,
  onChange,
  required,
}: {
  label: string;
  path: string;
  value: string;
  options: readonly SelectOption[];
  placeholder?: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const { disabled, clearErrors } = useContentForm();
  const error = useFieldError(path);
  return (
    <Field label={label} required={required} error={error}>
      <Select
        value={value}
        options={options}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.value);
          clearErrors(path);
        }}
      />
    </Field>
  );
}

// ---------------------------------------------------------------- список

type ListEditorProps<T extends { uid: string }> = {
  path: string;
  items: T[];
  onChange: (items: T[]) => void;
  max: number;
  create: () => T;
  /** «Вопрос 3» — подпись для кнопок и подтверждения. */
  itemLabel: (index: number) => string;
  /** Текст строки в заголовке карточки (обычно русский заголовок). */
  itemSummary: (item: T) => string;
  isFilled: (item: T) => boolean;
  addLabel: string;
  emptyTitle: string;
  emptyDescription?: string;
  children: (item: T, index: number, update: (patch: Partial<T>) => void) => ReactNode;
};

/**
 * Повторяющиеся элементы: добавление, порядок кнопками, удаление.
 * Порядок в списке — порядок на сайте. Всё применяется только после
 * сохранения раздела, поэтому «Отменить» возвращает удалённое.
 */
export function ListEditor<T extends { uid: string }>({
  path,
  items,
  onChange,
  max,
  create,
  itemLabel,
  itemSummary,
  isFilled,
  addLabel,
  emptyTitle,
  emptyDescription,
  children,
}: ListEditorProps<T>) {
  const { disabled, clearErrors } = useContentForm();
  const confirm = useConfirm();
  const focusUid = useRef<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!focusUid.current) return;
    const item = listRef.current?.querySelector(`[data-uid="${focusUid.current}"]`);
    focusUid.current = null;
    item?.querySelector<HTMLElement>('input, textarea, select')?.focus();
  }, [items.length]);

  // Индексы в путях ошибок сдвигаются при любой перестановке — старые
  // ошибки списка больше не относятся к своим полям.
  const replace = (next: T[]) => {
    onChange(next);
    clearErrors(path);
  };

  const add = () => {
    const item = create();
    focusUid.current = item.uid;
    replace([...items, item]);
  };

  const move = (from: number, to: number) => {
    const next = [...items];
    const [moved] = next.splice(from, 1);
    if (moved === undefined) return;
    next.splice(to, 0, moved);
    replace(next);
  };

  const remove = async (index: number) => {
    const item = items[index];
    if (!item) return;
    if (isFilled(item)) {
      const approved = await confirm({
        title: `Удалить «${itemSummary(item) || itemLabel(index)}»?`,
        description:
          'Элемент исчезнет из списка. На сайте изменение появится после сохранения раздела; до сохранения его можно вернуть кнопкой «Отменить».',
        confirmLabel: 'Удалить',
      });
      if (!approved) return;
    }
    replace(items.filter((_, position) => position !== index));
  };

  const update = (index: number) => (patch: Partial<T>) =>
    onChange(items.map((item, position) => (position === index ? { ...item, ...patch } : item)));

  const full = items.length >= max;

  return (
    <div className={styles.list}>
      <GroupError path={path} />
      {items.length === 0 ? (
        <EmptyState
          compact
          title={emptyTitle}
          description={emptyDescription}
          action={
            disabled ? null : (
              <Button size="sm" icon="plus" onClick={add}>
                {addLabel}
              </Button>
            )
          }
        />
      ) : (
        <>
          <ol className={styles.listItems} ref={listRef}>
            {items.map((item, index) => {
              const label = itemLabel(index);
              const summary = itemSummary(item);
              return (
                <li
                  key={item.uid}
                  className={styles.listItem}
                  data-uid={item.uid}
                  aria-label={label}
                >
                  <div className={styles.listItemHead}>
                    <span className={styles.listIndex} aria-hidden="true">
                      {index + 1}
                    </span>
                    <span className={styles.listSummary}>
                      {summary || <span className={styles.muted}>Не заполнено</span>}
                    </span>
                    {disabled ? null : (
                      <span className={styles.listButtons}>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon="chevronUp"
                          aria-label={`Выше: ${label}`}
                          title="Переместить выше"
                          disabled={index === 0}
                          onClick={() => move(index, index - 1)}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon="chevronDown"
                          aria-label={`Ниже: ${label}`}
                          title="Переместить ниже"
                          disabled={index === items.length - 1}
                          onClick={() => move(index, index + 1)}
                        />
                        <Button
                          size="sm"
                          variant="dangerGhost"
                          icon="trash"
                          aria-label={`Удалить: ${label}`}
                          title="Удалить"
                          onClick={() => void remove(index)}
                        />
                      </span>
                    )}
                  </div>
                  <div className={styles.listItemBody}>{children(item, index, update(index))}</div>
                </li>
              );
            })}
          </ol>
          <div className={styles.listFooter}>
            <span className={styles.muted}>
              {formatCount(items.length)} из {formatCount(max)}
            </span>
            {disabled ? null : (
              <Button size="sm" icon="plus" onClick={add} disabled={full}>
                {addLabel}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
