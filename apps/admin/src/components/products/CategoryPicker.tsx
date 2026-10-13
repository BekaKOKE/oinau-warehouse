'use client';

/**
 * Категории товара: выбор из дерева, основная категория, удаление.
 *
 * Основная задаёт канонический адрес и хлебные крошки на витрине. Если её
 * не отметить, backend сам сделает основной первую — интерфейс показывает
 * это заранее, чтобы результат не был сюрпризом.
 */

import { useMemo, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field, Select } from '@/components/ui/Field';
import { EmptyState } from '@/components/ui/States';
import type { ProductCategoryItem } from '@/lib/api/types';
import { categoryOptions, type FlatCategory } from '@/lib/products';

import styles from './ProductEditor.module.css';

type Props = {
  value: readonly ProductCategoryItem[];
  categories: readonly FlatCategory[];
  loading?: boolean;
  disabled?: boolean;
  onChange: (items: ProductCategoryItem[]) => void;
};

export function CategoryPicker({ value, categories, loading, disabled, onChange }: Props) {
  const [selected, setSelected] = useState('');
  const byId = useMemo(() => new Map(categories.map((item) => [item.id, item])), [categories]);
  const chosen = new Set(value.map((item) => item.category_id));
  const available = categoryOptions(categories.filter((item) => !chosen.has(item.id)));
  const hasPrimary = value.some((item) => item.is_primary);

  const add = () => {
    const id = Number(selected);
    if (!id || chosen.has(id)) return;
    onChange([
      ...value,
      { category_id: id, is_primary: value.length === 0, sort_order: value.length },
    ]);
    setSelected('');
  };

  const remove = (id: number) => {
    const rest = value.filter((item) => item.category_id !== id);
    // Удалили основную — основной становится первая из оставшихся, как у backend.
    if (rest.length > 0 && !rest.some((item) => item.is_primary)) {
      rest[0] = { ...rest[0]!, is_primary: true };
    }
    onChange(rest.map((item, index) => ({ ...item, sort_order: index })));
  };

  const makePrimary = (id: number) =>
    onChange(value.map((item) => ({ ...item, is_primary: item.category_id === id })));

  return (
    <div className={styles.picker}>
      {value.length === 0 ? (
        <EmptyState
          icon="categories"
          title="Категории не выбраны"
          description="Товар без категории не попадёт в разделы каталога на сайте."
          compact
        />
      ) : (
        <ul className={styles.categoryList} aria-label="Выбранные категории">
          {value.map((item, index) => {
            const category = byId.get(item.category_id);
            const primary = item.is_primary || (!hasPrimary && index === 0);
            return (
              <li key={item.category_id} className={styles.categoryItem}>
                <label className={styles.primaryRadio}>
                  <input
                    type="radio"
                    name="primary-category"
                    checked={primary}
                    disabled={disabled}
                    onChange={() => makePrimary(item.category_id)}
                  />
                  <span className={styles.categoryName}>
                    {category?.path ?? `Категория #${item.category_id}`}
                  </span>
                </label>
                <span className={styles.categoryBadges}>
                  {primary ? <Badge tone="info">Основная</Badge> : null}
                  {category && !category.isActive ? <Badge tone="warning">Скрыта</Badge> : null}
                </span>
                <Button
                  size="sm"
                  variant="dangerGhost"
                  icon="close"
                  aria-label={`Убрать категорию ${category?.name ?? item.category_id}`}
                  disabled={disabled}
                  onClick={() => remove(item.category_id)}
                />
              </li>
            );
          })}
        </ul>
      )}

      {!disabled ? (
        <div className={styles.pickerAdd}>
          <Field label="Добавить категорию">
            <Select
              options={available}
              placeholder={loading ? 'Загружаем категории…' : 'Выберите категорию'}
              value={selected}
              disabled={loading}
              onChange={(event) => setSelected(event.target.value)}
            />
          </Field>
          <Button icon="plus" onClick={add} disabled={!selected}>
            Добавить
          </Button>
        </div>
      ) : null}
    </div>
  );
}
