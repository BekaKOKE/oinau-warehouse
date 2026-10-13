'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import { categoriesApi, productsApi } from '@/lib/api/endpoints';
import type { ProductCategoryItem } from '@/lib/api/types';
import { describeError, extractFieldErrors, isForbidden } from '@/lib/errors';
import { useQuery } from '@/lib/hooks/useQuery';
import { flattenCategoryTree } from '@/lib/products';

import { CategoryPicker } from '../CategoryPicker';
import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

function itemsFromProduct(product: SectionProps['product']): ProductCategoryItem[] {
  return (product.categories ?? []).map((item, index) => ({
    category_id: item.category_id,
    is_primary: item.is_primary,
    sort_order: index,
  }));
}

function signature(items: readonly ProductCategoryItem[]): string {
  return items.map((item) => `${item.category_id}:${item.is_primary ? 1 : 0}`).join(',');
}

export function CategoriesSection({
  product,
  canWrite,
  onProductChange,
  onDirtyChange,
}: SectionProps) {
  const toast = useToast();
  const initial = useMemo(() => itemsFromProduct(product), [product]);
  const [items, setItems] = useState<ProductCategoryItem[]>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tree = useQuery((signal) => categoriesApi.tree({ signal }), []);
  const flat = useMemo(() => flattenCategoryTree(tree.data ?? []), [tree.data]);
  const dirty = signature(items) !== signature(initial);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await productsApi.setCategories(product.id, items);
      onDirtyChange(false);
      onProductChange(updated);
      setItems(itemsFromProduct(updated));
      toast.success('Категории сохранены');
    } catch (reason) {
      const fields = extractFieldErrors(reason);
      setError(fields._form ?? Object.values(fields)[0] ?? describeError(reason));
      toast.error(
        isForbidden(reason) ? 'Нет права изменять товар' : 'Категории не сохранены',
        reason,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card
        title="Категории"
        description="Основная категория задаёт адрес товара в каталоге и хлебные крошки."
      >
        {error ? (
          <div className={styles.formAlert} role="alert">
            {error}
          </div>
        ) : null}
        <CategoryPicker
          value={items}
          categories={flat}
          loading={tree.status === 'loading'}
          disabled={!canWrite || saving}
          onChange={setItems}
        />
        {canWrite ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setItems(initial);
              setError(null);
            }}
            note="Набор категорий заменяется целиком при сохранении."
          />
        ) : null}
      </Card>
    </form>
  );
}
