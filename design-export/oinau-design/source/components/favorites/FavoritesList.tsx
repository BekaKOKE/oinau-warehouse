/**
 * Список избранного.
 *
 * Рисуется из снимка в браузере: ни одного запроса к API. До того как
 * localStorage прочитан, показываются скелетоны — иначе на мгновение
 * мелькнёт «пусто» даже у того, кто сохранял позиции.
 */

'use client';

import Link from 'next/link';

import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/States';
import { useRequestDrawer } from '@/components/request/RequestDrawerContext';
import { useRequest } from '@/components/request/RequestProvider';
import { useFavorites } from './FavoritesProvider';
import styles from './FavoritesList.module.css';

export function FavoritesList() {
  const { items, ready, remove } = useFavorites();
  const { add } = useRequest();
  const { open } = useRequestDrawer();

  if (!ready) {
    return (
      <div className={styles.list}>
        {[0, 1, 2].map((index) => (
          <Skeleton key={index} height="106px" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="В избранном пока пусто"
        text="Нажмите на сердечко в карточке товара, чтобы вернуться к нему позже."
        action={<ButtonLink href="/catalog">Перейти в каталог</ButtonLink>}
      />
    );
  }

  return (
    <ul className={styles.list}>
      {items.map((item) => (
        <li key={item.sku} className={styles.item}>
          <div className={styles.thumb}>
            {item.imageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={item.imageUrl} alt="" loading="lazy" />
            ) : (
              <span>{item.sku}</span>
            )}
          </div>

          <div className={styles.body}>
            <Link href={`/product/${item.slug}`} className={styles.name}>
              {item.name}
            </Link>
            <div className={styles.meta}>
              <span>{item.sku}</span>
              <span>{item.availabilityLabel}</span>
            </div>
            <p className={styles.price}>{item.priceLabel}</p>
          </div>

          <div className={styles.actions}>
            <Button
              size="sm"
              variant="secondary"
              block={false}
              onClick={() => {
                add({
                  sku: item.sku,
                  slug: item.slug,
                  name: item.name,
                  unit: item.unit,
                  minOrderQty: 1,
                  priceLabel: item.priceLabel,
                  imageUrl: item.imageUrl,
                });
                open();
              }}
            >
              В заявку
            </Button>
            <Button
              size="sm"
              variant="outline"
              block={false}
              onClick={() => remove(item.sku)}
              aria-label={`Убрать из избранного: ${item.name}`}
            >
              Убрать
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
