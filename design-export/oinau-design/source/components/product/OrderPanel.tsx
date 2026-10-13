/**
 * Блок заказа: количество и добавление в заявку.
 *
 * Количество не опускается ниже минимальной партии (`min_order_qty`) —
 * того же значения, по которому backend отвергает заявку.
 */

'use client';

import { useState } from 'react';

import type { ProductDetail } from '@oinau/api-types';

import { FavoriteButton } from '@/components/favorites/FavoriteButton';
import { AddToRequestButton } from '@/components/request/AddToRequestButton';
import { describeAvailability, describePrice, formatQuantity, unitLabel } from '@/lib/format';
import { lineFromDetail } from '@/lib/request-line';
import styles from './Product.module.css';

export function OrderPanel({ product }: { product: ProductDetail }) {
  const minimum = Number(product.min_order_qty) || 1;
  const step = minimum < 1 ? minimum : 1;
  const [quantity, setQuantity] = useState(minimum);

  const price = describePrice(product.price, product.unit);
  const availability = describeAvailability(product.availability);
  const line = lineFromDetail(product, price.label);
  const main = product.images?.find((image) => image.is_main) ?? product.images?.[0];

  return (
    <>
      <div className={styles.orderRow}>
        <div className={styles.quantity}>
          <label className={styles.quantityLabel} htmlFor="product-quantity">
            Количество, {unitLabel(product.unit)}
          </label>
          <div className={styles.quantityControl}>
            <button
              type="button"
              className={styles.quantityButton}
              onClick={() => setQuantity((value) => Math.max(value - step, minimum))}
              disabled={quantity <= minimum}
              aria-label="Уменьшить количество"
            >
              −
            </button>
            <input
              id="product-quantity"
              className={styles.quantityInput}
              type="number"
              inputMode="decimal"
              min={minimum}
              step={step}
              value={quantity}
              onChange={(event) => {
                const next = Number(event.target.value);
                if (Number.isFinite(next)) setQuantity(next);
              }}
              onBlur={() => setQuantity((value) => (value < minimum ? minimum : value))}
            />
            <button
              type="button"
              className={styles.quantityButton}
              onClick={() => setQuantity((value) => value + step)}
              aria-label="Увеличить количество"
            >
              +
            </button>
          </div>
        </div>
      </div>

      <div className={styles.cta}>
        <span className={styles.ctaMain}>
          <AddToRequestButton
            line={line}
            quantity={quantity}
            onRequestPrice={price.onRequest}
            size="lg"
            variant="primary"
            openDrawer
          />
        </span>
        <FavoriteButton
          inline
          item={{
            sku: product.sku,
            slug: product.slug,
            name: product.name,
            unit: product.unit,
            priceLabel: price.label,
            availabilityLabel: availability.label,
            imageUrl: main?.variants?.small ?? main?.url,
          }}
        />
      </div>

      {minimum > 1 ? (
        <p className={styles.priceNote}>
          Минимальная партия — {formatQuantity(product.min_order_qty)} {unitLabel(product.unit)}.
        </p>
      ) : null}
    </>
  );
}
