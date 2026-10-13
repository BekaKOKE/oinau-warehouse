/**
 * Позиция заявки и её сборка из ответов каталога.
 *
 * Обычный модуль, а не часть `RequestProvider`: карточку товара
 * рисует серверный компонент, а функцию, экспортированную из
 * `'use client'`, на сервере вызвать нельзя — Next.js видит в ней
 * ссылку на клиентский модуль, а не код.
 */

import type { ProductColorOption, ProductDetail, ProductListItem } from '@oinau/api-types';

export type RequestLine = {
  sku: string;
  slug: string;
  name: string;
  unit: string;
  quantity: number;
  minOrderQty: number;
  /** Готовая строка цены на момент добавления — только для показа. */
  priceLabel: string;
  imageUrl?: string;
  /** Код цвета из каталога; без цвета — товар без выбора цвета. */
  color?: string;
  colorName?: string;
  colorHex?: string;
};

export type NewRequestLine = Omit<RequestLine, 'quantity'>;

/**
 * Ключ позиции: один товар в одном цвете — одна позиция.
 * Тот же товар в другом цвете — отдельная позиция, как и на backend.
 */
export function lineKey(line: Pick<RequestLine, 'sku' | 'color'>): string {
  return line.color ? `${line.sku}:${line.color}` : line.sku;
}

/** Позиция заявки из карточки каталога. */
export function lineFromListItem(product: ProductListItem, priceLabel: string): NewRequestLine {
  return {
    sku: product.sku,
    slug: product.slug,
    name: product.name,
    unit: product.unit,
    minOrderQty: 1,
    priceLabel,
    imageUrl: product.image?.variants?.thumb ?? product.image?.url,
  };
}

/** Позиция заявки со страницы товара: там известна минимальная партия и цвет. */
export function lineFromDetail(
  product: ProductDetail,
  priceLabel: string,
  color?: ProductColorOption | null,
): NewRequestLine {
  const main = product.images?.find((image) => image.is_main) ?? product.images?.[0];
  return {
    sku: product.sku,
    slug: product.slug,
    name: product.name,
    unit: product.unit,
    minOrderQty: Number(product.min_order_qty) || 1,
    priceLabel,
    imageUrl: main?.variants?.thumb ?? main?.url,
    ...(color ? { color: color.code, colorName: color.name, colorHex: color.hex } : {}),
  };
}
