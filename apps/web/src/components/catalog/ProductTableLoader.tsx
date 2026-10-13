/**
 * Таблица с подгрузкой «Показать ещё».
 *
 * Первая страница приходит с сервера (индексируется, открывается
 * ссылкой), следующие браузер дозапрашивает у того же публичного API
 * с теми же фильтрами и дописывает строки в таблицу. Постраничные
 * ссылки под таблицей остаются — ими удобно вернуться к нужному месту.
 */

'use client';

import { useState } from 'react';

import type { ProductListItem } from '@oinau/api-types';

import { Button } from '@/components/ui/Button';
import { describeError } from '@/lib/api/client';
import { fetchProducts, type ProductQuery } from '@/lib/api/catalog';
import { formatCount } from '@/lib/format';
import { ProductTable } from './ProductTable';
import styles from './Catalog.module.css';

export function ProductTableLoader({
  initialItems,
  query,
  page,
  pages,
  total,
}: {
  initialItems: ProductListItem[];
  query: ProductQuery;
  page: number;
  pages: number;
  total: number;
}) {
  const [items, setItems] = useState(initialItems);
  const [lastPage, setLastPage] = useState(page);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadMore() {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchProducts({ ...query, page: lastPage + 1 });
      setItems((current) => {
        // Каталог мог измениться между запросами — строки не дублируются.
        const known = new Set(current.map((item) => item.sku));
        return [...current, ...next.items.filter((item) => !known.has(item.sku))];
      });
      setLastPage(next.page);
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setLoading(false);
    }
  }

  const remaining = Math.max(total - items.length, 0);

  return (
    <>
      <ProductTable products={items} />
      {lastPage < pages ? (
        <div className={styles.loadMore}>
          <Button type="button" variant="outline" onClick={loadMore} disabled={loading}>
            {loading ? 'Загрузка…' : `Показать ещё (осталось ${formatCount(remaining)})`}
          </Button>
          {error ? (
            <p className={styles.loadMoreError} role="alert">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
