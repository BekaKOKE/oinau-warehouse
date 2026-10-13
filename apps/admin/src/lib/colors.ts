/**
 * Цвета товара: черновик формы и проверка перед отправкой.
 *
 * Статус наличия цвета и итоги считает backend — экран их показывает.
 * Здесь только то, что backend всё равно отвергнет (формат числа), чтобы
 * не отправлять заведомо плохой запрос.
 */

import type { Color, ProductColors, ProductColorsUpdate } from '@/lib/api/types';
import { compareDecimal, normalizeDecimalInput } from '@/lib/decimal';
import { trimQuantity } from '@/lib/stock';

export type ColorDraftRow = { colorId: number; quantity: string; priceDelta: string };

export function draftFromColors(colors: ProductColors): ColorDraftRow[] {
  return (colors.items ?? []).map((item) => ({
    colorId: item.color_id,
    quantity: trimQuantity(item.quantity),
    priceDelta: trimQuantity(item.price_delta),
  }));
}

export function isColorDraftDirty(draft: ColorDraftRow[], initial: ColorDraftRow[]): boolean {
  return JSON.stringify(draft) !== JSON.stringify(initial);
}

/** Тело PUT или ошибки полей по ключу `${colorId}.quantity` / `.priceDelta`. */
export function buildColorItems(draft: ColorDraftRow[]): {
  body: ProductColorsUpdate;
  errors: Record<string, string>;
} {
  const errors: Record<string, string> = {};
  const items: ProductColorsUpdate['items'] = [];
  for (const row of draft) {
    const quantity = normalizeDecimalInput(row.quantity || '0', { maxFraction: 3 });
    const delta = normalizeDecimalInput(row.priceDelta || '0', { maxFraction: 2 });
    if (!quantity.ok) errors[`${row.colorId}.quantity`] = quantity.error;
    if (!delta.ok) errors[`${row.colorId}.priceDelta`] = delta.error;
    if (quantity.ok && delta.ok) {
      items.push({ color_id: row.colorId, quantity: quantity.value, price_delta: delta.value });
    }
  }
  return { body: { items }, errors };
}

/** Сумма по цветам не совпадает с общим остатком по складам. */
export function totalsMismatch(colors: ProductColors): boolean {
  if ((colors.items ?? []).length === 0) return false;
  return compareDecimal(colors.colors_total, colors.stock_total) !== 0;
}

/** Цвета, которые ещё можно добавить: активные и не выбранные. */
export function addableColors(palette: readonly Color[], draft: ColorDraftRow[]): Color[] {
  const taken = new Set(draft.map((row) => row.colorId));
  return palette.filter((color) => color.is_active && !taken.has(color.id));
}

/** Код цвета из названия: «Тёмно-синий» → «temno-siniy». */
export { slugFromName as colorCodeFromName } from '@/lib/products';
