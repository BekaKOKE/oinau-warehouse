import { Icon } from '@/components/ui/Icon';

import styles from './Products.module.css';

/**
 * Миниатюра товара. Обычный <img>, а не next/image: ссылки ведут на CDN
 * вариантов, уже уменьшенных воркером, — оптимизатор Next.js здесь лишний.
 */
export function ProductThumb({
  url,
  count = 0,
  size = 40,
}: {
  url: string | null | undefined;
  count?: number;
  size?: number;
}) {
  return (
    <span className={styles.thumb} style={{ width: size, height: size }}>
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" loading="lazy" width={size} height={size} />
      ) : (
        <span
          className={styles.thumbEmpty}
          title={count > 0 ? 'Изображение ещё обрабатывается' : 'Нет изображения'}
        >
          <Icon name="image" size={Math.round(size / 2.4)} />
        </span>
      )}
    </span>
  );
}
