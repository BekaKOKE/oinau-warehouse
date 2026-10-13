/**
 * Блок заказа: количество, «В корзину» и «Купить в 1 клик».
 *
 * Количество не опускается ниже минимальной партии (`min_order_qty`) —
 * того же значения, по которому backend отвергает заявку. «В 1 клик»
 * открывает быстрый заказ с этим товаром, цветом и количеством.
 */

'use client';

import { useState } from 'react';

import type { PriceInfo, ProductColorOption, ProductDetail } from '@oinau/api-types';

import { FavoriteButton } from '@/components/favorites/FavoriteButton';
import { OneClickButton } from '@/components/quick-order/OneClickButton';
import { AddToRequestButton } from '@/components/request/AddToRequestButton';
import { thumbSource } from '@/components/ui/ProductImage';
import { describeAvailability, describePrice, formatQuantity, unitLabel } from '@/lib/format';
import { lineFromDetail } from '@/lib/request-line';
import styles from './Product.module.css';

export function OrderPanel({
  product,
  price: priceInfo = product.price,
  color = null,
}: {
  product: ProductDetail;
  /** Цена выбранного цвета; без цвета — цена товара. */
  price?: PriceInfo;
  color?: ProductColorOption | null;
}) {
  const minimum = Number(product.min_order_qty) || 1;
  const step = minimum < 1 ? minimum : 1;
  const [quantity, setQuantity] = useState(minimum);

  const price = describePrice(priceInfo, product.unit);
  const availability = describeAvailability(color?.availability ?? product.availability);
  const line = lineFromDetail(product, price.label, color);
  const main = product.images?.find((image) => image.is_main) ?? product.images?.[0];

  return (
    <div className={styles.order}>
      <label className={styles.quantityLabel} htmlFor="product-quantity">
        Количество, {unitLabel(product.unit)}
      </label>
      <div className={styles.orderRow}>
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

        <div className={styles.ctaMain}>
          <AddToRequestButton
            line={line}
            quantity={quantity}
            onRequestPrice={price.onRequest}
            size="lg"
            variant="primary"
            openDrawer
          />
        </div>

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

      <OneClickButton
        size="lg"
        className={styles.oneClick}
        label="Купить в 1 клик"
        product={{
          sku: product.sku,
          name: product.name,
          unit: product.unit,
          minOrderQty: minimum,
          quantity: Math.max(quantity, minimum),
          priceLabel: price.label,
          imageUrl: main ? thumbSource(main) : undefined,
          color: color?.code,
          colorName: color?.name,
        }}
      />

      {minimum > 1 ? (
        <p className={styles.orderNote}>
          Минимальная партия — {formatQuantity(product.min_order_qty)} {unitLabel(product.unit)}.
        </p>
      ) : null}
    </div>
  );
}
