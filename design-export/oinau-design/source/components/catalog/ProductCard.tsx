/**
 * Карточка товара в списке.
 *
 * B2B-набор данных: артикул на виду, наличие рядом с ценой, единица
 * измерения обязательна. Кнопка ведёт в заявку, а не в корзину с
 * оплатой — оплаты на сайте нет.
 */

import Link from 'next/link';

import type { ProductListItem } from '@oinau/api-types';

import { FavoriteButton } from '@/components/favorites/FavoriteButton';
import { AddToRequestButton } from '@/components/request/AddToRequestButton';
import { AvailabilityBadge, badgeStyles } from '@/components/ui/AvailabilityBadge';
import { ProductImageView } from '@/components/ui/ProductImage';
import { favoriteFromProduct } from '@/lib/favorite-item';
import { describeAvailability, describePrice } from '@/lib/format';
import { lineFromListItem } from '@/lib/request-line';
import { PriceDisplay } from './PriceDisplay';
import styles from './ProductCard.module.css';

const CARD_SIZES = '(max-width: 620px) 50vw, (max-width: 1100px) 33vw, 260px';

export function ProductCard({
  product,
  priority = false,
}: {
  product: ProductListItem;
  priority?: boolean;
}) {
  const price = describePrice(product.price, product.unit);
  const availability = describeAvailability(product.availability);
  const href = `/product/${product.slug}`;

  return (
    <article className={styles.card}>
      {product.is_featured ? <span className={badgeStyles.featured}>Хит</span> : null}
      <FavoriteButton item={favoriteFromProduct(product, price.label, availability.label)} />

      <Link href={href} className={styles.media} tabIndex={-1} aria-hidden="true">
        <ProductImageView
          image={product.image}
          label={product.sku}
          alt={product.name}
          sizes={CARD_SIZES}
          priority={priority}
        />
      </Link>

      <div className={styles.body}>
        <Link href={href} className={styles.name}>
          {product.name}
        </Link>

        <div className={styles.meta}>
          <span className={styles.sku}>{product.sku}</span>
          <AvailabilityBadge value={product.availability} />
        </div>

        {product.short_description ? (
          <p className={styles.summary}>{product.short_description}</p>
        ) : null}

        <PriceDisplay price={product.price} unit={product.unit} />

        <div className={styles.action}>
          <AddToRequestButton
            line={lineFromListItem(product, price.label)}
            onRequestPrice={price.onRequest}
            variant={price.onRequest ? 'outline' : 'secondary'}
          />
        </div>
      </div>
    </article>
  );
}
