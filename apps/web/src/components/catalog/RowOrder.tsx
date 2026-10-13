/**
 * Заказ из строки таблицы: количество, «В корзину» и «1 клик».
 *
 * Количество не опускается ниже минимальной партии — того же значения,
 * по которому backend отвергает заявку. Товар с цветами кладётся
 * в корзину со страницы товара: в строке цвет не выбрать.
 */

'use client';

import { useState } from 'react';

import type { ProductListItem } from '@oinau/api-types';

import { OneClickButton } from '@/components/quick-order/OneClickButton';
import { AddToRequestButton } from '@/components/request/AddToRequestButton';
import { ButtonLink } from '@/components/ui/Button';
import { thumbSource } from '@/components/ui/ProductImage';
import { unitLabel } from '@/lib/format';
import { lineFromListItem } from '@/lib/request-line';
import styles from './ProductTable.module.css';

export function RowOrder({
  product,
  priceLabel,
  onRequest,
}: {
  product: ProductListItem;
  priceLabel: string;
  onRequest: boolean;
}) {
  const minimum = Number(product.min_order_qty) || 1;
  const [quantity, setQuantity] = useState(minimum);
  const line = { ...lineFromListItem(product, priceLabel), minOrderQty: minimum };

  if ((product.colors ?? []).length > 0) {
    return (
      <div className={styles.order}>
        <ButtonLink
          href={`/product/${product.slug}`}
          size="sm"
          variant={onRequest ? 'outline' : 'primary'}
          className={styles.add}
          aria-label={`Выбрать цвет: ${product.sku}`}
        >
          Выбрать цвет
        </ButtonLink>
      </div>
    );
  }

  return (
    <div className={styles.order}>
      <input
        className={styles.qty}
        type="number"
        inputMode="decimal"
        min={minimum}
        step={minimum < 1 ? minimum : 1}
        value={quantity}
        aria-label={`Количество, ${unitLabel(product.unit)}: ${product.sku}`}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) setQuantity(next);
        }}
        onBlur={() => setQuantity((value) => (value < minimum ? minimum : value))}
      />
      <AddToRequestButton
        line={line}
        quantity={Math.max(quantity, minimum)}
        onRequestPrice={onRequest}
        variant={onRequest ? 'outline' : 'primary'}
        size="sm"
        compact
        block={false}
        className={styles.add}
      />
      <OneClickButton
        className={styles.oneClick}
        label="1 клик"
        product={{
          sku: product.sku,
          name: product.name,
          unit: product.unit,
          minOrderQty: minimum,
          quantity: Math.max(quantity, minimum),
          priceLabel,
          imageUrl: product.image ? thumbSource(product.image) : undefined,
        }}
      />
    </div>
  );
}
