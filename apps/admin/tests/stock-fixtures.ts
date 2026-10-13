/**
 * Склады и остатки для тестов — формы из сгенерированных типов.
 */

import type { ProductStockListItem, Warehouse } from '@/lib/api/types';

import { makeStock } from './product-fixtures';

export const STOCK_LIST = '/api/v1/admin/stock';
export const WAREHOUSES = '/api/v1/admin/warehouses';
export const REGIONS = '/api/v1/public/regions';

export function makeWarehouse(overrides: Partial<Warehouse> = {}): Warehouse {
  return {
    id: 1,
    code: 'main',
    name: 'Склад Алматы',
    region_id: 1,
    region_code: 'almaty',
    region_name: 'Алматы',
    is_active: true,
    external_id: null,
    sync_source: 'manual',
    ...overrides,
  };
}

export const WAREHOUSE_LIST: Warehouse[] = [
  makeWarehouse(),
  makeWarehouse({
    id: 2,
    code: 'astana',
    name: 'Склад Астана',
    region_id: null,
    region_code: null,
    region_name: null,
    is_active: false,
    external_id: '1C-WH-2',
    sync_source: '1c',
  }),
];

export function makeStockRow(overrides: Partial<ProductStockListItem> = {}): ProductStockListItem {
  return {
    ...makeStock(),
    name: 'Канат полипропиленовый 16 мм',
    status: 'PUBLISHED',
    is_active: true,
    pricing_type: 'TIERED',
    external_id: '1C-00042',
    primary_category: {
      category_id: 2,
      slug: 'kanaty',
      name: 'Канаты',
      is_primary: true,
      sort_order: 0,
      is_active: true,
    },
    stock_updated_at: '2026-09-14T03:00:00Z',
    ...overrides,
  };
}

/** Товар без остатков: свободно ноль, на сайте «Под заказ» вручную. */
export function emptyStockRow(): ProductStockListItem {
  return makeStockRow({
    product_id: 6,
    sku: 'SID-01',
    name: 'Сиденье качелей',
    unit: 'pcs',
    external_id: null,
    primary_category: null,
    entries: [
      {
        warehouse_id: 1,
        warehouse_code: 'main',
        warehouse_name: 'Склад Алматы',
        warehouse_is_active: true,
        quantity: '0.000',
        reserved: '0.000',
        available: '0.000',
        sync_source: null,
        synced_at: null,
        external_id: null,
        updated_at: null,
      },
    ],
    total_quantity: '0.000',
    total_reserved: '0.000',
    total_available: '0.000',
    public_availability: 'ON_REQUEST',
    stock_display_override: 'ON_REQUEST',
    stock_updated_at: null,
  });
}
