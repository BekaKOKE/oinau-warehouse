/**
 * Цены по количеству для таблицы товаров раздела.
 *
 * Колонки «от 1», «от 100», «от 1000» строятся из ступеней, которые
 * backend прислал вместе со списком (та же модель, что в карточке
 * товара). Цена в колонке — цена ступени, в диапазон которой попадает
 * это количество; ничего не пересчитывается и не выдумывается.
 */

import type { PriceInfo, ProductListItem } from '@oinau/api-types';

/** Больше колонок не помещается в строку таблицы — тогда цены списком. */
export const MAX_TIER_COLUMNS = 4;

/**
 * Цена за единицу при заказе `quantity` штук или null, если на такое
 * количество цены нет (разрыв ступеней, цена по запросу).
 */
export function priceAt(price: PriceInfo, quantity: number): string | null {
  if (price.type === 'ON_REQUEST') return null;
  const tiers = price.tiers ?? [];
  if (price.type === 'FIXED') return price.price ?? tiers[0]?.price ?? null;
  const tier = tiers.find(
    (item) =>
      Number(item.min_quantity) <= quantity &&
      (item.max_quantity === null ||
        item.max_quantity === undefined ||
        quantity <= Number(item.max_quantity)),
  );
  return tier?.price ?? null;
}

/**
 * Общие колонки количества для страницы или null, если ступени у товаров
 * слишком разные (тогда в строке — компактный список ступеней товара).
 */
export function tierColumns(items: readonly ProductListItem[]): number[] | null {
  const quantities = new Set<number>();
  for (const item of items) {
    if (item.price.type !== 'TIERED' && item.price.type !== 'FROM') continue;
    for (const tier of item.price.tiers ?? []) quantities.add(Number(tier.min_quantity));
  }
  if (quantities.size < 2 || quantities.size > MAX_TIER_COLUMNS) return null;
  return [...quantities].sort((a, b) => a - b);
}
