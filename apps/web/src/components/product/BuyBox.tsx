/**
 * Цена, выбор цвета и заказ на странице товара.
 *
 * Один клиентский блок, потому что выбранный цвет меняет всё сразу: цены
 * по количеству (у цвета бывает надбавка), позицию корзины и «заказ в 1
 * клик». Цену цвета считает backend и отдаёт в `colors[].price` — здесь
 * она только показывается.
 */

'use client';

import { useState } from 'react';

import type { PriceInfo, ProductDetail } from '@oinau/api-types';

import {
  currencySymbol,
  describePrice,
  formatAmount,
  formatQuantity,
  unitLabel,
} from '@/lib/format';
import { ColorPicker, defaultColor } from './ColorPicker';
import { OrderPanel } from './OrderPanel';
import styles from './Product.module.css';

function PriceBlock({ price, unit }: { price: PriceInfo; unit: string }) {
  const display = describePrice(price, unit);
  const symbol = currencySymbol(price.currency);
  const tiers = price.tiers ?? [];
  const unitName = unitLabel(unit);

  if (display.onRequest) {
    return (
      <>
        <p className={styles.priceOnRequest}>Цена по запросу</p>
        <p className={styles.priceNote}>
          Стоимость зависит от объёма и исполнения — рассчитаем в ответ на заявку.
        </p>
      </>
    );
  }
  if (tiers.length > 1) {
    // Ступени — колонки, как в прайсе: «от 1 м | от 100 м | …», под ними цены.
    return (
      <div className={styles.tierScroll}>
        <table className={styles.tierTable}>
          <caption className={styles.tierCaption}>Цена за {unitName}</caption>
          <thead>
            <tr>
              {tiers.map((tier) => (
                <th scope="col" key={`${tier.min_quantity}-${tier.price}`}>
                  от {formatQuantity(tier.min_quantity)} {unitName}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {tiers.map((tier) => (
                <td key={`${tier.min_quantity}-${tier.price}`} className={styles.tierTablePrice}>
                  {formatAmount(tier.price)} {symbol}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <p className={styles.priceMain}>
      {display.prefix ? <span className={styles.priceFrom}>{display.prefix}</span> : null}
      <span className={styles.priceValue}>{display.amount}</span>
      <span className={styles.priceUnit}>{display.suffix}</span>
    </p>
  );
}

export function BuyBox({ product }: { product: ProductDetail }) {
  const colors = product.colors ?? [];
  const [code, setCode] = useState(() => defaultColor(colors));
  const color = colors.find((item) => item.code === code) ?? null;
  const price = color?.price ?? product.price;

  return (
    <>
      {colors.length > 0 ? <ColorPicker colors={colors} value={code} onChange={setCode} /> : null}
      <PriceBlock price={price} unit={product.unit} />
      <OrderPanel product={product} price={price} color={color} />
    </>
  );
}
