/**
 * Таблица товаров раздела — основной вид B2B-каталога.
 *
 * Строка = позиция: фото, артикул, название с характеристиками, цены
 * по количеству, наличие и заказ. На десктопе — таблица для быстрого
 * сравнения десятков позиций; на телефоне та же выдача — списком
 * карточек (таблица и список рисуются оба, видимость — в CSS).
 *
 * Точный остаток на витрину не выводится: публичный API отдаёт только
 * статус наличия.
 */

import Link from 'next/link';

import type { ProductListItem } from '@oinau/api-types';

import { ProductImageView } from '@/components/ui/ProductImage';
import {
  currencySymbol,
  describeAvailability,
  describePrice,
  formatAmount,
  formatQuantity,
  formatTierRange,
  unitLabel,
} from '@/lib/format';
import { priceAt, tierColumns } from '@/lib/price-table';
import { ColorSwatches } from './ColorSwatches';
import { RowOrder } from './RowOrder';
import styles from './ProductTable.module.css';

// Сколько параметров показывать в строке — остальное на странице товара.
const MAX_FEATURES = 4;

type Feature = { name: string; value: string };

/** Характеристики-фильтры, затем описательные — без повторов по названию. */
export function productFeatures(product: ProductListItem): Feature[] {
  const result: Feature[] = [];
  const seen = new Set<string>();
  for (const item of product.characteristics ?? []) {
    if (seen.has(item.name)) continue;
    seen.add(item.name);
    result.push({ name: item.name, value: item.value });
  }
  for (const [name, value] of Object.entries(product.specs ?? {})) {
    if (seen.has(name)) continue;
    seen.add(name);
    result.push({ name, value: String(value) });
  }
  return result.slice(0, MAX_FEATURES);
}

function Features({ product }: { product: ProductListItem }) {
  const features = productFeatures(product);
  if (features.length === 0) return null;
  return (
    <dl className={styles.features}>
      {features.map((feature) => (
        <div key={feature.name} className={styles.feature}>
          <dt>{feature.name}</dt>
          <dd>{feature.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Ступени одного товара, когда общих колонок для страницы нет. */
function TierList({ product }: { product: ProductListItem }) {
  const display = describePrice(product.price, product.unit);
  const tiers = product.price.tiers ?? [];
  const symbol = currencySymbol(product.price.currency);
  if (display.onRequest) return <span className={styles.onRequest}>По запросу</span>;
  if (tiers.length < 2) return <span className={styles.price}>{display.label}</span>;
  return (
    <ul className={styles.tierList}>
      {tiers.map((tier) => (
        <li key={tier.min_quantity}>
          <span className={styles.tierQty}>
            {tier.max_quantity
              ? formatTierRange(tier.min_quantity, tier.max_quantity)
              : `от ${formatQuantity(tier.min_quantity)}`}
          </span>
          <span className={styles.tierPrice}>
            {formatAmount(tier.price)} {symbol}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Availability({ product }: { product: ProductListItem }) {
  const { label, tone } = describeAvailability(product.availability);
  return (
    <span className={`${styles.stock} ${styles[tone]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {label}
    </span>
  );
}

export function ProductTable({ products }: { products: ProductListItem[] }) {
  const columns = tierColumns(products);
  const currency = currencySymbol(products[0]?.price.currency ?? 'KZT');

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className="visuallyHidden">Товары раздела</caption>
        <thead>
          <tr>
            <th scope="col" className={styles.colImage}>
              <span className="visuallyHidden">Фото</span>
            </th>
            <th scope="col" className={styles.colSku}>
              Артикул
            </th>
            <th scope="col">Наименование</th>
            {columns ? (
              columns.map((quantity) => (
                <th key={quantity} scope="col" className={styles.colPrice}>
                  от {formatQuantity(String(quantity))}
                </th>
              ))
            ) : (
              <th scope="col" className={styles.colPrice}>
                Цена
              </th>
            )}
            <th scope="col" className={styles.colStock}>
              Наличие
            </th>
            <th scope="col" className={styles.colOrder}>
              <span className="visuallyHidden">Заказ</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {products.map((product, index) => {
            const display = describePrice(product.price, product.unit);
            const href = `/product/${product.slug}`;
            return (
              <tr key={product.sku}>
                <td className={styles.colImage}>
                  <Link href={href} tabIndex={-1} aria-hidden="true" className={styles.thumb}>
                    <ProductImageView
                      image={product.image}
                      label={product.sku}
                      alt={product.name}
                      sizes="96px"
                      priority={index < 6}
                      fit="contain"
                      className={styles.frame}
                    />
                  </Link>
                </td>
                <td className={styles.colSku}>
                  <span className={styles.sku}>{product.sku}</span>
                </td>
                <td>
                  <Link href={href} className={styles.name}>
                    {product.name}
                  </Link>
                  <Features product={product} />
                  <ColorSwatches colors={product.colors} className={styles.swatches} />
                </td>
                {columns ? (
                  display.onRequest ? (
                    <td colSpan={columns.length} className={styles.colPrice}>
                      <span className={styles.onRequest}>Цена по запросу</span>
                    </td>
                  ) : (
                    columns.map((quantity) => {
                      const value = priceAt(product.price, quantity);
                      return (
                        <td key={quantity} className={styles.colPrice}>
                          {value ? (
                            <span className={styles.price}>
                              {formatAmount(value)} {currency}
                            </span>
                          ) : (
                            <span className={styles.empty} aria-label="нет цены">
                              —
                            </span>
                          )}
                        </td>
                      );
                    })
                  )
                ) : (
                  <td className={styles.colPrice}>
                    <TierList product={product} />
                  </td>
                )}
                <td className={styles.colStock}>
                  <Availability product={product} />
                </td>
                <td className={styles.colOrder}>
                  <RowOrder
                    product={product}
                    priceLabel={display.label}
                    onRequest={display.onRequest}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <ul className={styles.cards} aria-label="Товары раздела">
        {products.map((product) => {
          const display = describePrice(product.price, product.unit);
          const href = `/product/${product.slug}`;
          return (
            <li key={product.sku} className={styles.card}>
              <Link href={href} tabIndex={-1} aria-hidden="true" className={styles.cardThumb}>
                <ProductImageView
                  image={product.image}
                  label={product.sku}
                  alt={product.name}
                  sizes="96px"
                  fit="contain"
                  className={styles.frame}
                />
              </Link>
              <div className={styles.cardBody}>
                <p className={styles.cardMeta}>
                  <span className={styles.sku}>арт. {product.sku}</span>
                  <Availability product={product} />
                </p>
                <Link href={href} className={styles.name}>
                  {product.name}
                </Link>
                <Features product={product} />
                <ColorSwatches colors={product.colors} />
                <div className={styles.cardPrice}>
                  <TierList product={product} />
                  {!display.onRequest ? (
                    <span className={styles.cardUnit}>за {unitLabel(product.unit)}</span>
                  ) : null}
                </div>
                <RowOrder
                  product={product}
                  priceLabel={display.label}
                  onRequest={display.onRequest}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
