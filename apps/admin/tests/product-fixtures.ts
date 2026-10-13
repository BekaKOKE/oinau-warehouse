/**
 * Данные товаров для тестов: формы — сгенерированные типы OpenAPI.
 */

import type {
  AttributeRead,
  CategoryAttribute,
  CategoryTreeNode,
  PricingRead,
  ProductImage,
  ProductListRow,
  ProductRead,
  ProductStock,
} from '@/lib/api/types';

export const PRODUCT_ID = 5;
export const PRODUCT_URL = `/api/v1/admin/products/${PRODUCT_ID}`;

export function makeProductRow(overrides: Partial<ProductListRow> = {}): ProductListRow {
  return {
    id: PRODUCT_ID,
    sku: 'KAN-16-PP',
    slug: 'kanat-16-pp',
    name: 'Канат полипропиленовый 16 мм',
    status: 'PUBLISHED',
    is_active: true,
    is_featured: true,
    is_publicly_visible: true,
    unit: 'm',
    brand: null,
    external_id: '1C-00042',
    primary_category: {
      category_id: 2,
      slug: 'kanaty',
      name: 'Канаты',
      is_primary: true,
      sort_order: 0,
      is_active: true,
    },
    categories_count: 2,
    created_at: '2026-09-10T08:00:00Z',
    updated_at: '2026-09-14T03:00:00Z',
    deleted_at: null,
    main_image_url: 'http://cdn.test/products/abc/variants/thumb.webp',
    images_count: 2,
    pricing_type: 'TIERED',
    currency: 'KZT',
    min_price: '2600.00',
    max_price: '3500.00',
    public_availability: 'IN_STOCK',
    stock_display_override: null,
    ...overrides,
  };
}

export function makeProduct(overrides: Partial<ProductRead> = {}): ProductRead {
  return {
    id: PRODUCT_ID,
    sku: 'KAN-16-PP',
    slug: 'kanat-16-pp',
    name: 'Канат полипропиленовый 16 мм',
    status: 'PUBLISHED',
    is_active: true,
    is_featured: false,
    is_publicly_visible: true,
    unit: 'm',
    brand: null,
    external_id: null,
    primary_category: null,
    categories_count: 1,
    created_at: '2026-09-10T08:00:00Z',
    updated_at: '2026-09-14T03:00:00Z',
    deleted_at: null,
    min_order_qty: '1.000',
    specs: {},
    translations: {
      ru: {
        name: 'Канат полипропиленовый 16 мм',
        short_description: 'Армированный канат',
        description: null,
        seo_title: 'SEO заголовок каната',
        seo_description: 'SEO описание',
      },
    },
    categories: [
      {
        category_id: 2,
        slug: 'kanaty',
        name: 'Канаты',
        is_primary: true,
        sort_order: 0,
        is_active: true,
      },
    ],
    attributes: [
      {
        attribute_id: 10,
        code: 'diameter',
        name: 'Диаметр',
        value_type: 'NUMBER',
        unit: 'мм',
        value_numeric: '16.000',
      },
      {
        attribute_id: 11,
        code: 'material',
        name: 'Материал',
        value_type: 'OPTION',
        unit: null,
        option_id: 100,
        option_slug: 'pp',
        option_value: 'Полипропилен',
      },
    ],
    pricing_type: 'TIERED',
    stock_display_override: null,
    sync_source: 'manual',
    synced_at: null,
    ...overrides,
  };
}

export const CATEGORY_TREE: CategoryTreeNode[] = [
  {
    id: 1,
    slug: 'komplektuyushchie',
    name: 'Комплектующие',
    depth: 0,
    sort_order: 0,
    is_active: true,
    products_count: 3,
    children: [
      {
        id: 2,
        slug: 'kanaty',
        name: 'Канаты',
        depth: 1,
        sort_order: 0,
        is_active: true,
        products_count: 1,
        children: [],
      },
      {
        id: 3,
        slug: 'krepleniya',
        name: 'Крепления',
        depth: 1,
        sort_order: 1,
        is_active: false,
        products_count: 2,
        children: [],
      },
    ],
  },
];

export const CATEGORY_ATTRIBUTES: CategoryAttribute[] = [
  {
    attribute_id: 10,
    code: 'diameter',
    name: 'Диаметр',
    value_type: 'NUMBER',
    unit: 'мм',
    sort_order: 1,
    is_required: true,
  },
  {
    attribute_id: 11,
    code: 'material',
    name: 'Материал',
    value_type: 'OPTION',
    unit: null,
    sort_order: 2,
    is_required: false,
  },
  {
    attribute_id: 12,
    code: 'certified',
    name: 'Сертифицирован',
    value_type: 'BOOLEAN',
    unit: null,
    sort_order: 3,
    is_required: false,
  },
  {
    attribute_id: 13,
    code: 'color_note',
    name: 'Цвет',
    value_type: 'STRING',
    unit: null,
    sort_order: 4,
    is_required: false,
  },
];

export const MATERIAL_ATTRIBUTE: AttributeRead = {
  id: 11,
  code: 'material',
  value_type: 'OPTION',
  unit: null,
  is_filterable: true,
  is_visible: true,
  is_active: true,
  sort_order: 2,
  name: 'Материал',
  names: { ru: 'Материал' },
  options: [
    { id: 100, slug: 'pp', sort_order: 0, values: { ru: 'Полипропилен' } },
    { id: 101, slug: 'steel', sort_order: 1, values: { ru: 'Сталь' } },
  ],
  usage_count: 1,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
};

export function makePricing(overrides: Partial<PricingRead> = {}): PricingRead {
  return {
    product_id: PRODUCT_ID,
    sku: 'KAN-16-PP',
    pricing_type: 'ON_REQUEST',
    currency: 'KZT',
    price_list_code: 'default',
    tiers: [],
    min_price: null,
    max_price: null,
    ...overrides,
  };
}

export function makeStock(overrides: Partial<ProductStock> = {}): ProductStock {
  return {
    product_id: PRODUCT_ID,
    sku: 'KAN-16-PP',
    unit: 'm',
    entries: [
      {
        warehouse_id: 1,
        warehouse_code: 'main',
        warehouse_name: 'Склад Алматы',
        warehouse_is_active: true,
        quantity: '152.500',
        reserved: '2.500',
        available: '150.000',
        sync_source: 'manual',
        synced_at: null,
        external_id: null,
        updated_at: '2026-09-14T03:00:00Z',
      },
      {
        warehouse_id: 2,
        warehouse_code: 'astana',
        warehouse_name: 'Склад Астана',
        warehouse_is_active: false,
        quantity: '40.000',
        reserved: '0.000',
        available: '40.000',
        sync_source: '1c',
        synced_at: '2026-09-13T10:00:00Z',
        external_id: '1C-WH-2',
        updated_at: '2026-09-13T10:00:00Z',
      },
    ],
    total_quantity: '152.500',
    total_reserved: '2.500',
    total_available: '150.000',
    public_availability: 'IN_STOCK',
    stock_display_override: null,
    ...overrides,
  };
}

export function makeImage(overrides: Partial<ProductImage> = {}): ProductImage {
  const id = overrides.id ?? 1;
  return {
    id,
    media_uuid: `00000000-0000-4000-8000-00000000000${id}`,
    kind: 'PHOTO',
    alt: {},
    is_main: false,
    sort_order: id,
    status: 'READY',
    is_publicly_visible: true,
    url: `http://cdn.test/products/${id}/variants/large.webp`,
    variants: {
      large: `http://cdn.test/products/${id}/variants/large.webp`,
      thumb: `http://cdn.test/products/${id}/variants/thumb.webp`,
    },
    width: 800,
    height: 600,
    original_filename: `photo-${id}.jpg`,
    content_type: 'image/jpeg',
    size_bytes: 1024,
    created_at: '2026-09-14T03:00:00Z',
    ...overrides,
  };
}
