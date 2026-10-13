/**
 * Избранное в аккаунте.
 *
 * Список артикулов хранит кабинет, а цену, фото и наличие — каталог.
 * Для каждой позиции страницы берётся публичная карточка товара,
 * и позиция рисуется той же `ProductCard`, что и в каталоге: цена
 * всегда актуальная, а не снимок недельной давности.
 *
 * Товар, снятый с публикации, остаётся в списке компактной строкой
 * с кнопкой удаления — молча прятать его было бы странно.
 */

'use client';

import { useEffect, useState } from 'react';

import type { CustomerFavorite, ProductListItem } from '@oinau/api-types';

import { ProductCard } from '@/components/catalog/ProductCard';
import gridStyles from '@/components/catalog/ProductGrid.module.css';
import { useFavorites } from '@/components/favorites/FavoritesProvider';
import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState, ProductCardSkeleton } from '@/components/ui/States';
import { fetchProduct } from '@/lib/api/catalog';
import { fetchFavorites } from '@/lib/api/customer';
import { describeCabinetError, formatDate } from '@/lib/cabinet/format';
import { listItemFromDetail } from '@/lib/favorite-item';
import { CabinetPagination, PageHead } from './CabinetUi';
import styles from './Cabinet.module.css';

const FAVORITES_PAGE_SIZE = 24;

type Entry = { favorite: CustomerFavorite; product: ProductListItem | null };

type Loaded = { entries: Entry[]; page: number; pages: number; total: number };

async function loadEntry(favorite: CustomerFavorite): Promise<Entry> {
  try {
    const product = await fetchProduct(favorite.slug);
    return { favorite, product: product ? listItemFromDetail(product) : null };
  } catch {
    return { favorite, product: null };
  }
}

export function CabinetFavorites({ page }: { page: number }) {
  const { has, remove, ready } = useFavorites();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    (async () => {
      const result = await fetchFavorites({ page, pageSize: FAVORITES_PAGE_SIZE });
      const entries = await Promise.all(result.items.map(loadEntry));
      if (!cancelled) {
        setData({ entries, page: result.page, pages: result.pages, total: result.total });
      }
    })().catch((caught: unknown) => {
      if (!cancelled) setError(describeCabinetError(caught));
    });
    return () => {
      cancelled = true;
    };
  }, [page, attempt]);

  // Сердечко на карточке или кнопка «Убрать» удаляют позицию через общий
  // провайдер — страница просто перестаёт её показывать.
  const visible = data?.entries.filter((entry) => !ready || has(entry.favorite.sku)) ?? [];

  return (
    <>
      <PageHead
        title="Избранное"
        lead="Сохранённые товары хранятся в аккаунте и доступны с любого устройства."
      />

      {error ? (
        <ErrorState
          title="Не удалось загрузить избранное"
          text={error}
          action={<Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>}
        />
      ) : !data ? (
        <div className={gridStyles.grid} aria-busy="true" aria-label="Загрузка избранного">
          {[0, 1, 2].map((index) => (
            <ProductCardSkeleton key={index} />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          title="В избранном пока пусто"
          text="Нажмите на сердечко в карточке товара, чтобы сохранить его в аккаунте."
          action={<ButtonLink href="/catalog">Перейти в каталог</ButtonLink>}
        />
      ) : (
        <>
          <div className={`${gridStyles.grid} ${styles.favoritesGrid}`}>
            {visible.map(({ favorite, product }) =>
              product ? (
                <div key={favorite.sku} className={styles.favoriteCell}>
                  <ProductCard product={product} />
                  <button
                    type="button"
                    className={styles.favoriteRemove}
                    onClick={() => remove(favorite.sku)}
                    aria-label={`Убрать из избранного: ${favorite.name}`}
                  >
                    Убрать из избранного
                  </button>
                </div>
              ) : (
                <article key={favorite.sku} className={styles.unavailableCard}>
                  <p className={styles.unavailableBadge}>Недоступен</p>
                  <h3 className={styles.itemName}>{favorite.name}</h3>
                  <p className={`${styles.rowSub} ${styles.mono}`}>Арт. {favorite.sku}</p>
                  <p className={styles.muted}>
                    Товар снят с публикации. Добавлен {formatDate(favorite.added_at)}.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    block={false}
                    onClick={() => remove(favorite.sku)}
                    aria-label={`Убрать из избранного: ${favorite.name}`}
                  >
                    Убрать
                  </Button>
                </article>
              ),
            )}
          </div>
          <CabinetPagination
            basePath="/cabinet/favorites"
            page={data.page}
            pages={data.pages}
            total={data.total}
            shown={visible.length}
          />
        </>
      )}
    </>
  );
}
