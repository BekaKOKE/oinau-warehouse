'use client';

/**
 * Характеристики категории.
 *
 * PUT /categories/{id}/attributes заменяет набор целиком, поэтому экран
 * редактирует список и сохраняет его одной операцией: порядок в списке
 * становится sort_order, флаг «обязательная» — is_required. Список для
 * добавления — актуальные характеристики из API, без копий на фронтенде.
 */

import { useEffect, useMemo, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Checkbox, Field, Select } from '@/components/ui/Field';
import { Card } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { attributesApi, categoriesApi } from '@/lib/api/endpoints';
import { VALUE_TYPE_META } from '@/lib/attributeForm';
import {
  assignedFromApi,
  assignedSignature,
  assignedToItems,
  type AssignedAttribute,
} from '@/lib/categories';
import { describeError, isForbidden } from '@/lib/errors';
import { useQuery } from '@/lib/hooks/useQuery';
import { moveItem } from '@/lib/media';

import styles from './Categories.module.css';

export function CategoryAttributesEditor({
  categoryId,
  canWrite,
}: {
  categoryId: number;
  canWrite: boolean;
}) {
  const toast = useToast();
  const assigned = useQuery(
    (signal) => categoriesApi.attributes(categoryId, { signal }),
    [categoryId],
  );
  const all = useQuery((signal) => attributesApi.listAll({ signal }), [], { enabled: canWrite });

  const initial = useMemo(() => assignedFromApi(assigned.data ?? []), [assigned.data]);
  const [items, setItems] = useState<AssignedAttribute[]>(initial);
  const [selected, setSelected] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setItems(initial), [initial]);

  const dirty = assignedSignature(items) !== assignedSignature(initial);
  const chosen = new Set(items.map((item) => item.attribute_id));
  const available = (all.data ?? [])
    .filter((attribute) => !chosen.has(attribute.id))
    .map((attribute) => ({
      value: String(attribute.id),
      label: `${attribute.name} (${attribute.code}) — ${VALUE_TYPE_META[attribute.value_type].label}${attribute.is_active ? '' : ', отключена'}`,
    }));

  const add = () => {
    const attribute = (all.data ?? []).find((item) => String(item.id) === selected);
    if (!attribute) return;
    setItems((current) => [
      ...current,
      {
        attribute_id: attribute.id,
        sort_order: current.length,
        is_required: false,
        code: attribute.code,
        name: attribute.name,
        value_type: attribute.value_type,
        unit: attribute.unit,
      },
    ]);
    setSelected('');
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await categoriesApi.setAttributes(categoryId, assignedToItems(items));
      assigned.setData(saved);
      toast.success('Характеристики категории сохранены');
    } catch (reason) {
      setError(describeError(reason));
      toast.error(isForbidden(reason) ? 'Нет права изменять категории' : 'Не сохранено', reason);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      title="Характеристики категории"
      description="Эти поля появятся в карточках товаров категории. Порядок здесь — порядок на сайте."
    >
      {assigned.status === 'error' && !assigned.data ? (
        <ErrorState error={assigned.error} onRetry={assigned.reload} compact />
      ) : !assigned.data ? (
        <div className={styles.stack} aria-busy="true">
          <Skeleton height={40} />
          <Skeleton height={40} />
        </div>
      ) : (
        <>
          {error ? (
            <div className={styles.formAlert} role="alert">
              {error}
            </div>
          ) : null}
          {items.length === 0 ? (
            <EmptyState icon="attributes" title="Характеристики не назначены" compact />
          ) : (
            <ol className={styles.assignedList} aria-label="Назначенные характеристики">
              {items.map((item, index) => (
                <li key={item.attribute_id} className={styles.assignedItem}>
                  <span className={styles.assignedPosition}>{index + 1}</span>
                  <span className={styles.assignedMain}>
                    <span className={styles.strong}>
                      {item.unit ? `${item.name}, ${item.unit}` : item.name}
                    </span>
                    <span className={`mono ${styles.muted}`}>{item.code}</span>
                  </span>
                  <Badge tone="neutral">{VALUE_TYPE_META[item.value_type].label}</Badge>
                  <Checkbox
                    label="Обязательная"
                    checked={Boolean(item.is_required)}
                    disabled={!canWrite || saving}
                    onChange={(event) =>
                      setItems((current) =>
                        current.map((entry) =>
                          entry.attribute_id === item.attribute_id
                            ? { ...entry, is_required: event.target.checked }
                            : entry,
                        ),
                      )
                    }
                  />
                  {canWrite ? (
                    <span className={styles.assignedActions}>
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="chevronUp"
                        aria-label={`Поднять «${item.name}»`}
                        disabled={saving || index === 0}
                        onClick={() => setItems((current) => moveItem(current, index, index - 1))}
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="chevronDown"
                        aria-label={`Опустить «${item.name}»`}
                        disabled={saving || index === items.length - 1}
                        onClick={() => setItems((current) => moveItem(current, index, index + 1))}
                      />
                      <Button
                        size="sm"
                        variant="dangerGhost"
                        icon="close"
                        aria-label={`Убрать «${item.name}»`}
                        disabled={saving}
                        onClick={() =>
                          setItems((current) =>
                            current.filter((entry) => entry.attribute_id !== item.attribute_id),
                          )
                        }
                      />
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          )}

          {canWrite ? (
            <>
              <div className={styles.addRow}>
                <Field label="Добавить характеристику">
                  <Select
                    options={available}
                    placeholder={
                      all.status === 'loading'
                        ? 'Загружаем характеристики…'
                        : available.length === 0
                          ? 'Все характеристики уже назначены'
                          : 'Выберите характеристику'
                    }
                    value={selected}
                    disabled={saving || all.status !== 'success'}
                    onChange={(event) => setSelected(event.target.value)}
                  />
                </Field>
                <Button icon="plus" disabled={!selected || saving} onClick={add}>
                  Добавить
                </Button>
              </div>
              {all.status === 'error' ? (
                <ErrorState error={all.error} onRetry={all.reload} compact />
              ) : null}
              <div className={styles.actions}>
                <span className={styles.muted}>
                  {dirty ? 'Есть несохранённые изменения' : 'Набор сохраняется целиком.'}
                </span>
                <div className={styles.actionsRight}>
                  <Button
                    variant="ghost"
                    disabled={!dirty || saving}
                    onClick={() => setItems(initial)}
                  >
                    Отменить
                  </Button>
                  <Button
                    variant="primary"
                    loading={saving}
                    disabled={!dirty}
                    onClick={() => void save()}
                  >
                    Сохранить характеристики
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </>
      )}
    </Card>
  );
}
