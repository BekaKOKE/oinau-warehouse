/**
 * Карточка товара в списке.
 *
 * Порядок как в макете: фото с меткой наличия в углу → артикул →
 * название → краткое описание → цена → оптовая ступень → «В корзину»
 * и «1 клик». Цена — самый заметный элемент после названия.
 * Оплаты на сайте нет: корзина собирает заявку менеджеру.
 */

import Link from 'next/link';

import type { ProductListItem } from '@oinau/api-types';

import { FavoriteButton } from '@/components/favorites/FavoriteButton';
import { OneClickButton } from '@/components/quick-order/OneClickButton';
import { AddToRequestButton } from '@/components/request/AddToRequestButton';
import { badgeStyles } from '@/components/ui/AvailabilityBadge';
import { ButtonLink } from '@/components/ui/Button';
import { ProductImageView, thumbSource } from '@/components/ui/ProductImage';
import { favoriteFromProduct } from '@/lib/favorite-item';
import { describeAvailability, describePrice, describeWholesale } from '@/lib/format';
import { lineFromListItem } from '@/lib/request-line';
import { ColorSwatches } from './ColorSwatches';
import { PriceDisplay } from './PriceDisplay';
import styles from './ProductCard.module.css';

const CARD_SIZES = '(max-width: 560px) 50vw, (max-width: 1180px) 33vw, 300px';

const STOCK_TONE = {
  success: badgeStyles.stock,
  warning: `${badgeStyles.stock} ${badgeStyles.stockWarning}`,
  muted: `${badgeStyles.stock} ${badgeStyles.stockMuted}`,
} as const;

export function ProductCard({
  product,
  priority = false,
}: {
  product: ProductListItem;
  priority?: boolean;
}) {
  const price = describePrice(product.price, product.unit);
  const availability = describeAvailability(product.availability);
  const wholesale = describeWholesale(product.price, product.unit);
  const href = `/product/${product.slug}`;
  // Товар с цветами кладётся в корзину со страницы товара: там выбирается
  // цвет и видна его цена.
  const hasColors = (product.colors ?? []).length > 0;

  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <div className={badgeStyles.corner}>
          <span className={STOCK_TONE[availability.tone]}>{availability.label}</span>
          {product.is_featured ? <span className={badgeStyles.featured}>Хит</span> : null}
        </div>
        <FavoriteButton item={favoriteFromProduct(product, price.label, availability.label)} />
        <Link href={href} className={styles.mediaLink} tabIndex={-1} aria-hidden="true">
          <ProductImageView
            image={product.image}
            label={product.sku}
            alt={product.name}
            sizes={CARD_SIZES}
            priority={priority}
            fit="contain"
            className={styles.image}
          />
        </Link>
      </div>

      <div className={styles.body}>
        <p className={styles.sku}>
          <span className={styles.skuLabel}>арт.</span> <span>{product.sku}</span>
        </p>

        <h3 className={styles.heading}>
          <Link href={href} className={styles.name}>
            {product.name}
          </Link>
        </h3>

        <ColorSwatches colors={product.colors} className={styles.swatches} />

        {product.short_description ? (
          <p className={styles.spec}>{product.short_description}</p>
        ) : null}

        <div className={styles.footer}>
          <PriceDisplay price={product.price} unit={product.unit} />
          {wholesale ? <p className={styles.wholesale}>{wholesale}</p> : null}
          <div className={styles.actions}>
            {hasColors ? (
              <ButtonLink
                href={href}
                size="sm"
                variant={price.onRequest ? 'outline' : 'primary'}
                className={styles.cta}
                aria-label={`Выбрать цвет: ${product.name}`}
              >
                Выбрать цвет
              </ButtonLink>
            ) : (
              <AddToRequestButton
                line={lineFromListItem(product, price.label)}
                onRequestPrice={price.onRequest}
                variant={price.onRequest ? 'outline' : 'primary'}
                size="sm"
                compact
                className={styles.cta}
              />
            )}
            <OneClickButton
              className={styles.oneClick}
              product={{
                sku: product.sku,
                name: product.name,
                unit: product.unit,
                priceLabel: price.label,
                imageUrl: product.image ? thumbSource(product.image) : undefined,
              }}
            />
          </div>
        </div>
      </div>
    </article>
  );
}
