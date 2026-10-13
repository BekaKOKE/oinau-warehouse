'use client';

/**
 * Варианты значений характеристики типа OPTION.
 *
 * Каждый вариант сохраняется своим запросом (POST / PATCH / DELETE
 * /attributes/{id}/options): это отдельные сущности, на них ссылаются
 * значения товаров. Используемый вариант backend удалить не даст (409).
 */

import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Field, Input } from '@/components/ui/Field';
import { EmptyState } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { attributesApi } from '@/lib/api/endpoints';
import type { AttributeOption, AttributeRead } from '@/lib/api/types';
import { DEFAULT_LOCALE, optionDraftError, optionValue } from '@/lib/attributeForm';
import { extractFieldErrors, isForbidden } from '@/lib/errors';
import { slugFromName } from '@/lib/products';

import styles from './Attributes.module.css';

function withoutKey<T>(
  record: Record<string | number, T>,
  key: string | number,
): Record<string | number, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

type RowState = { value: string; slug: string; sortOrder: string };

function rowFrom(option: AttributeOption): RowState {
  return { value: optionValue(option), slug: option.slug, sortOrder: String(option.sort_order) };
}

type Props = {
  attribute: AttributeRead;
  canWrite: boolean;
  onChanged: (attribute: AttributeRead) => void;
};

export function OptionsManager({ attribute, canWrite, onChanged }: Props) {
  const toast = useToast();
  const confirm = useConfirm();
  const options = attribute.options ?? [];
  const [rows, setRows] = useState<Record<number, RowState>>({});
  const [errors, setErrors] = useState<Record<string, { value?: string; slug?: string }>>({});
  const [busy, setBusy] = useState<number | 'new' | null>(null);
  const [draft, setDraft] = useState<RowState>({ value: '', slug: '', sortOrder: '' });

  const refresh = async () => onChanged(await attributesApi.get(attribute.id));

  const fieldErrors = (error: unknown): { value?: string; slug?: string } => {
    if (error instanceof ApiError && error.status === 409 && error.code === 'slug_exists') {
      return { slug: error.message };
    }
    const fields = extractFieldErrors(error);
    return {
      slug: fields.slug,
      value: fields[`values.${DEFAULT_LOCALE}`] ?? fields.values ?? fields._form,
    };
  };

  const saveRow = async (option: AttributeOption) => {
    const row = rows[option.id];
    if (!row) return;
    const local = optionDraftError(row);
    const sortOrder = Number.parseInt(row.sortOrder, 10);
    if (Object.keys(local).length > 0 || !Number.isFinite(sortOrder)) {
      setErrors((state) => ({ ...state, [option.id]: local }));
      return;
    }
    setBusy(option.id);
    try {
      await attributesApi.updateOption(attribute.id, option.id, {
        slug: row.slug.trim() !== option.slug ? row.slug.trim() : undefined,
        sort_order: sortOrder !== option.sort_order ? sortOrder : undefined,
        values:
          row.value.trim() !== optionValue(option)
            ? { [DEFAULT_LOCALE]: row.value.trim() }
            : undefined,
      });
      setRows((state) => withoutKey(state, option.id));
      setErrors((state) => withoutKey(state, String(option.id)));
      await refresh();
      toast.success('Вариант сохранён');
    } catch (error) {
      setErrors((state) => ({ ...state, [option.id]: fieldErrors(error) }));
      toast.error(
        isForbidden(error) ? 'Нет права изменять характеристики' : 'Вариант не сохранён',
        error,
      );
    } finally {
      setBusy(null);
    }
  };

  const removeRow = async (option: AttributeOption) => {
    const approved = await confirm({
      title: `Удалить вариант «${optionValue(option)}»?`,
      description: 'Удалить можно только вариант, который не выбран ни у одного товара.',
      confirmLabel: 'Удалить',
    });
    if (!approved) return;
    setBusy(option.id);
    try {
      await attributesApi.removeOption(attribute.id, option.id);
      await refresh();
      toast.success('Вариант удалён');
    } catch (error) {
      toast.error(
        error instanceof ApiError && error.code === 'attribute_option_in_use'
          ? 'Вариант выбран у товаров — сначала замените его в карточках'
          : isForbidden(error)
            ? 'Нет права изменять характеристики'
            : 'Вариант не удалён',
        error,
      );
    } finally {
      setBusy(null);
    }
  };

  const addOption = async () => {
    const local = optionDraftError(draft);
    if (Object.keys(local).length > 0) {
      setErrors((state) => ({ ...state, new: local }));
      return;
    }
    setBusy('new');
    try {
      await attributesApi.createOption(attribute.id, {
        slug: draft.slug.trim(),
        sort_order: draft.sortOrder.trim() ? Number.parseInt(draft.sortOrder, 10) : options.length,
        values: { [DEFAULT_LOCALE]: draft.value.trim() },
      });
      setDraft({ value: '', slug: '', sortOrder: '' });
      setErrors((state) => withoutKey(state, 'new'));
      await refresh();
      toast.success('Вариант добавлен');
    } catch (error) {
      setErrors((state) => ({ ...state, new: fieldErrors(error) }));
      toast.error(
        isForbidden(error) ? 'Нет права изменять характеристики' : 'Вариант не добавлен',
        error,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={styles.section} aria-labelledby="attribute-options">
      <p id="attribute-options" className={styles.subheading}>
        Варианты значений
      </p>
      {options.length === 0 ? (
        <EmptyState
          icon="attributes"
          title="Вариантов пока нет"
          description="Без вариантов значение нельзя выбрать в товаре."
          compact
        />
      ) : (
        <ol className={styles.optionList} aria-label="Варианты значений">
          {options.map((option) => {
            const row = rows[option.id] ?? rowFrom(option);
            const edited = Boolean(rows[option.id]);
            const rowErrors = errors[option.id] ?? {};
            const update = (patch: Partial<RowState>) =>
              setRows((state) => ({ ...state, [option.id]: { ...row, ...patch } }));
            return (
              <li key={option.id} className={styles.optionRow}>
                <Field label="Значение" error={rowErrors.value}>
                  <Input
                    value={row.value}
                    disabled={!canWrite || busy === option.id}
                    onChange={(event) => update({ value: event.target.value })}
                  />
                </Field>
                <Field label="slug" error={rowErrors.slug}>
                  <Input
                    className="mono"
                    value={row.slug}
                    disabled={!canWrite || busy === option.id}
                    onChange={(event) => update({ slug: event.target.value })}
                  />
                </Field>
                <Field label="Порядок">
                  <Input
                    inputMode="numeric"
                    value={row.sortOrder}
                    disabled={!canWrite || busy === option.id}
                    onChange={(event) => update({ sortOrder: event.target.value })}
                  />
                </Field>
                {canWrite ? (
                  <div className={styles.optionActions}>
                    {edited ? (
                      <Button
                        size="sm"
                        variant="primary"
                        loading={busy === option.id}
                        onClick={() => void saveRow(option)}
                      >
                        Сохранить
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="dangerGhost"
                      icon="trash"
                      aria-label={`Удалить вариант «${optionValue(option)}»`}
                      disabled={busy !== null}
                      onClick={() => void removeRow(option)}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      {canWrite ? (
        <div className={`${styles.optionRow} ${styles.newOption}`}>
          <Field label="Новый вариант" error={errors.new?.value}>
            <Input
              value={draft.value}
              disabled={busy === 'new'}
              onChange={(event) =>
                setDraft((state) => ({
                  ...state,
                  value: event.target.value,
                  slug:
                    state.slug === slugFromName(state.value)
                      ? slugFromName(event.target.value)
                      : state.slug,
                }))
              }
            />
          </Field>
          <Field label="slug" error={errors.new?.slug}>
            <Input
              className="mono"
              value={draft.slug}
              disabled={busy === 'new'}
              onChange={(event) => setDraft((state) => ({ ...state, slug: event.target.value }))}
            />
          </Field>
          <Field label="Порядок">
            <Input
              inputMode="numeric"
              placeholder={String(options.length)}
              value={draft.sortOrder}
              disabled={busy === 'new'}
              onChange={(event) =>
                setDraft((state) => ({ ...state, sortOrder: event.target.value }))
              }
            />
          </Field>
          <div className={styles.optionActions}>
            <Button size="sm" icon="plus" loading={busy === 'new'} onClick={() => void addOption()}>
              Добавить
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
