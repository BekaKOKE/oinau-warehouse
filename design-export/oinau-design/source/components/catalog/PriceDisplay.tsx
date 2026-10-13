/**
 * Цена по правилам backend. Единственное место, где `PriceInfo`
 * превращается в текст — чтобы «от 2 600 ₸» и «Цена по запросу»
 * выглядели одинаково в каталоге и в карточке товара.
 */

import type { PriceInfo } from '@oinau/api-types';

import { describePrice } from '@/lib/format';
import styles from './ProductCard.module.css';

export function PriceDisplay({
  price,
  unit,
  className,
}: {
  price: PriceInfo;
  unit: string;
  className?: string;
}) {
  const display = describePrice(price, unit);

  if (display.onRequest) {
    return (
      <p className={[styles.price, className ?? ''].filter(Boolean).join(' ')}>
        <span className={styles.priceOnRequest}>Цена по запросу</span>
      </p>
    );
  }

  return (
    <p className={[styles.price, className ?? ''].filter(Boolean).join(' ')}>
      {display.prefix ? <span className={styles.pricePrefix}>{display.prefix}</span> : null}
      <span className={styles.priceAmount}>{display.amount}</span>
      <span className={styles.priceSuffix}>{display.suffix}</span>
    </p>
  );
}
