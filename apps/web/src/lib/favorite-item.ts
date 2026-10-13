/**
 * Избранная позиция и её сборка из ответа каталога.
 *
 * Вынесено из провайдера по той же причине, что и `request-line`:
 * карточку товара рисует сервер, и функция должна жить вне
 * клиентского модуля.
 */

import type { ProductDetail, ProductListItem } from '@oinau/api-types';

export type FavoriteItem = {
  sku: string;
  slug: string;
  name: string;
  unit: string;
  priceLabel: string;
  availabilityLabel: string;
  imageUrl?: string;
};

export function favoriteFromProduct(
  product: ProductListItem,
  priceLabel: string,
  availabilityLabel: string,
): FavoriteItem {
  return {
    sku: product.sku,
    slug: product.slug,
    name: product.name,
    unit: product.unit,
    priceLabel,
    availabilityLabel,
    imageUrl: product.image?.variants?.small ?? product.image?.url,
  };
}

/**
 * Карточка товара в форме элемента списка — чтобы избранное кабинета
 * рисовалось той же `ProductCard`, что и каталог.
 */
export function listItemFromDetail(product: ProductDetail): ProductListItem {
  return {
    sku: product.sku,
    slug: product.slug,
    name: product.name,
    short_description: product.short_description,
    unit: product.unit,
    min_order_qty: product.min_order_qty,
    is_featured: product.is_featured,
    price: product.price,
    availability: product.availability,
    image: product.images?.[0] ?? null,
    characteristics: product.characteristics ?? [],
    specs: product.specs ?? {},
  };
}
