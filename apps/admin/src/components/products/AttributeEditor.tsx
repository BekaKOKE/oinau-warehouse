'use client';

/**
 * Значения характеристик: поле ввода по типу характеристики backend.
 *
 * Набор характеристик берётся из категорий товара (GET /categories/{id}/
 * attributes) плюс уже заполненные у товара. Варианты для OPTION —
 * из GET /attributes/{id}: у списка характеристик категории их нет.
 */

import { useMemo } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Checkbox, Field, Input, Select } from '@/components/ui/Field';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { attributesApi, categoriesApi } from '@/lib/api/endpoints';
import type { AttributeOption, ProductAttributeRead } from '@/lib/api/types';
import {
  buildDefs,
  emptyValue,
  optionLabel,
  VALUE_TYPE_LABELS,
  type AttributeDef,
  type AttributeValue,
  type AttributeValues,
} from '@/lib/attributes';
import { useQuery } from '@/lib/hooks/useQuery';

import styles from './ProductEditor.module.css';

const BOOLEAN_OPTIONS = [
  { value: 'true', label: 'Да' },
  { value: 'false', label: 'Нет' },
];

/** Определения характеристик для набора категорий и заполненных значений. */
export function useAttributeDefs(
  categoryIds: readonly number[],
  existing: readonly ProductAttributeRead[],
) {
  const key = [...categoryIds].sort((a, b) => a - b).join(',');
  const existingKey = existing.map((item) => item.attribute_id).join(',');

  return useQuery(
    async (signal) => {
      const perCategory = await Promise.all(
        categoryIds.map((id) => categoriesApi.attributes(id, { signal })),
      );
      const optionIds = new Set<number>();
      for (const list of perCategory) {
        for (const item of list) if (item.value_type === 'OPTION') optionIds.add(item.attribute_id);
      }
      for (const item of existing)
        if (item.value_type === 'OPTION') optionIds.add(item.attribute_id);
      const details = await Promise.all(
        [...optionIds].map((id) => attributesApi.get(id, { signal })),
      );
      const options: Record<number, AttributeOption[]> = {};
      for (const detail of details) {
        options[detail.id] = [...(detail.options ?? [])].sort(
          (a, b) => a.sort_order - b.sort_order,
        );
      }
      return buildDefs(perCategory, existing, options);
    },
    [key, existingKey],
  );
}

type EditorProps = {
  defs: AttributeDef[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  values: AttributeValues;
  errors: Record<number, string>;
  disabled?: boolean;
  onChange: (attributeId: number, value: AttributeValue) => void;
};

export function AttributeEditor({
  defs,
  loading,
  error,
  onRetry,
  values,
  errors,
  disabled = false,
  onChange,
}: EditorProps) {
  const groups = useMemo(() => {
    const list = defs ?? [];
    return {
      category: list.filter((def) => def.fromCategory),
      other: list.filter((def) => !def.fromCategory),
    };
  }, [defs]);

  if (error && !defs) return <ErrorState error={error} onRetry={onRetry} compact />;
  if (loading && !defs) {
    return (
      <div className={styles.skeletonStack} aria-busy="true">
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Skeleton height={36} />
      </div>
    );
  }
  if (!defs || defs.length === 0) {
    return (
      <EmptyState
        icon="attributes"
        title="Характеристик нет"
        description="Характеристики появляются, когда они назначены категориям товара."
        compact
      />
    );
  }

  const render = (def: AttributeDef) => {
    const value = values[def.id] ?? emptyValue(def.valueType);
    const label = (
      <span className={styles.attrLabel}>
        <span>{def.unit ? `${def.name}, ${def.unit}` : def.name}</span>
        <Badge tone="neutral">{VALUE_TYPE_LABELS[def.valueType]}</Badge>
      </span>
    );
    const hint = def.required
      ? 'Рекомендуется заполнить: отмечена обязательной в категории'
      : undefined;

    switch (value.type) {
      case 'STRING':
        return (
          <Field
            key={def.id}
            label={label}
            hint={hint}
            error={errors[def.id]}
            required={def.required}
          >
            <Input
              maxLength={255}
              value={value.text}
              disabled={disabled}
              onChange={(event) => onChange(def.id, { type: 'STRING', text: event.target.value })}
            />
          </Field>
        );
      case 'NUMBER':
        return (
          <Field
            key={def.id}
            label={label}
            hint={hint}
            error={errors[def.id]}
            required={def.required}
          >
            <Input
              inputMode="decimal"
              value={value.text}
              disabled={disabled}
              onChange={(event) => onChange(def.id, { type: 'NUMBER', text: event.target.value })}
            />
          </Field>
        );
      case 'BOOLEAN':
        return (
          <Field
            key={def.id}
            label={label}
            hint={hint}
            error={errors[def.id]}
            required={def.required}
          >
            <Select
              options={BOOLEAN_OPTIONS}
              placeholder="Не указано"
              value={value.value}
              disabled={disabled}
              onChange={(event) =>
                onChange(def.id, {
                  type: 'BOOLEAN',
                  value: event.target.value as '' | 'true' | 'false',
                })
              }
            />
          </Field>
        );
      case 'OPTION':
        return (
          <fieldset key={def.id} className={styles.optionGroup} disabled={disabled}>
            <legend>
              {label}
              {def.required ? <span className={styles.required}> *</span> : null}
            </legend>
            {def.options.length === 0 ? (
              <p className={styles.muted}>У характеристики нет вариантов значений.</p>
            ) : (
              <div className={styles.optionList}>
                {def.options.map((option) => (
                  <Checkbox
                    key={option.id}
                    label={optionLabel(option)}
                    checked={value.optionIds.includes(option.id)}
                    onChange={(event) =>
                      onChange(def.id, {
                        type: 'OPTION',
                        optionIds: event.target.checked
                          ? [...value.optionIds, option.id]
                          : value.optionIds.filter((id) => id !== option.id),
                      })
                    }
                  />
                ))}
              </div>
            )}
            {errors[def.id] ? <p className={styles.errorText}>{errors[def.id]}</p> : null}
          </fieldset>
        );
    }
  };

  return (
    <div className={styles.attributes}>
      {groups.category.length > 0 ? (
        <div className={styles.formGrid}>{groups.category.map(render)}</div>
      ) : null}
      {groups.other.length > 0 ? (
        <div className={groups.category.length > 0 ? styles.otherAttributes : undefined}>
          <p className={styles.subheading}>
            Не назначены категориям товара
            <span className={styles.muted}> — очистите значение, если оно больше не нужно</span>
          </p>
          <div className={styles.formGrid}>{groups.other.map(render)}</div>
        </div>
      ) : null}
    </div>
  );
}
