/**
 * Данные для тестов в форме ответов публичного API.
 *
 * Формы повторяют схемы backend, включая главное: денежные значения
 * и количества — строки.
 */

import type {
  CategoryNode,
  PriceInfo,
  ProductDetail,
  ProductListItem,
  ProductPage,
} from '@oinau/api-types';

export const fixedPrice: PriceInfo = {
  type: 'FIXED',
  currency: 'KZT',
  price: '15900.00',
  from_price: '15900.00',
  to_price: null,
  tiers: [],
};

export const tieredPrice: PriceInfo = {
  type: 'TIERED',
  currency: 'KZT',
  price: null,
  from_price: '2600.00',
  to_price: '3500.00',
  tiers: [
    { min_quantity: '1.000', max_quantity: '49.000', price: '3500.00' },
    { min_quantity: '50.000', max_quantity: null, price: '2600.00' },
  ],
};

export const fromPrice: PriceInfo = {
  type: 'FROM',
  currency: 'KZT',
  price: null,
  from_price: '2800.00',
  to_price: '3100.00',
  tiers: [],
};

export const onRequestPrice: PriceInfo = {
  type: 'ON_REQUEST',
  currency: 'KZT',
  price: null,
  from_price: null,
  to_price: null,
  tiers: [],
};

export function makeProduct(overrides: Partial<ProductListItem> = {}): ProductListItem {
  return {
    sku: 'RP-016',
    slug: 'kanat-armirovannyj-16-mm',
    name: 'Канат армированный Ø16 мм',
    short_description: 'Шестипрядный канат с оцинкованным сердечником.',
    unit: 'm',
    min_order_qty: '1.000',
    is_featured: false,
    price: tieredPrice,
    availability: 'IN_STOCK',
    image: null,
    characteristics: [],
    specs: {},
    ...overrides,
  };
}

export function makeProductPage(
  items: ProductListItem[],
  overrides: Partial<ProductPage> = {},
): ProductPage {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 24,
    pages: 1,
    ...overrides,
  };
}

export function makeProductDetail(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    sku: 'RP-016',
    slug: 'kanat-armirovannyj-16-mm',
    name: 'Канат армированный Ø16 мм',
    short_description: 'Шестипрядный канат.',
    description: 'Подробное описание каната.',
    brand: 'OINAU',
    unit: 'm',
    min_order_qty: '5.000',
    is_featured: true,
    price: tieredPrice,
    availability: 'IN_STOCK',
    breadcrumbs: [{ slug: 'kanaty-i-seti', name: 'Канаты и сети' }],
    categories: [{ slug: 'kanaty-i-seti', name: 'Канаты и сети' }],
    images: [],
    documents: [],
    characteristics: [{ code: 'diameter', name: 'Диаметр', value: '16 мм' }],
    specs: {},
    seo_title: null,
    seo_description: null,
    ...overrides,
  };
}

export function makeCategories(): CategoryNode[] {
  return [
    {
      slug: 'komplektuyushchie',
      name: 'Комплектующие',
      depth: 0,
      product_count: 20,
      children: [
        { slug: 'kanaty-i-seti', name: 'Канаты и сети', depth: 1, product_count: 3, children: [] },
        {
          slug: 'krepleniya-i-podvesy',
          name: 'Крепления и подвесы',
          depth: 1,
          product_count: 3,
          children: [],
        },
      ],
    },
  ];
}
