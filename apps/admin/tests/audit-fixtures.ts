/**
 * Данные журнала аудита и сводки каталога для тестов.
 *
 * Формы — как у backend: Page[AuditLogRead] и CatalogSummaryRead.
 */

import type { AuditLogEntry, CatalogSummary, ContentSectionSummary } from '@/lib/api/types';

export const AUDIT_URL = '/api/v1/admin/audit';
export const SUMMARY_URL = '/api/v1/admin/catalog/summary';
export const CONTENT_URL = '/api/v1/admin/content';

export const STAFF_UUID = '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60';

export function makeAuditEntry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id: 1001,
    created_at: '2026-09-17T09:15:00Z',
    action: 'catalog.product_updated',
    actor: 'user',
    entity_type: 'product',
    entity_id: 42,
    user: {
      uuid: STAFF_UUID,
      full_name: 'Данияр Ахметов',
      email: 'daniyar@oinau-pro.kz',
    },
    changes: { status: { old: 'DRAFT', new: 'PUBLISHED' } },
    request_id: 'req-7f3a',
    ...overrides,
  };
}

export const AUDIT_ROWS: AuditLogEntry[] = [
  makeAuditEntry(),
  makeAuditEntry({
    id: 1002,
    created_at: '2026-09-17T08:40:00Z',
    action: 'pricing.updated',
    entity_type: 'product_pricing',
    entity_id: 42,
    changes: { price: { old: '3500.00', new: '3200.00' }, pricing_type: 'FIXED' },
    request_id: 'req-1b2c',
  }),
  makeAuditEntry({
    id: 1003,
    created_at: '2026-09-16T11:05:00Z',
    action: 'catalog.product_updated',
    actor: 'import',
    user: null,
    entity_id: 51,
    changes: { import_job: 'IMP-2026-0004', sku: { old: 'AV-810', new: 'AV-820' } },
    request_id: null,
  }),
];

export const CATALOG_SUMMARY: CatalogSummary = {
  products: {
    total: 120,
    active: 96,
    inactive: 24,
    publicly_visible: 88,
    featured: 6,
    draft: 12,
    published: 100,
    archived: 8,
    deleted: 3,
  },
  content: {
    without_images: 9,
    without_ready_images: 11,
    without_price: 5,
    price_on_request: 17,
  },
  availability: {
    in_stock: 70,
    out_of_stock: 14,
    on_request: 36,
    overridden: 4,
  },
  categories: { total: 15, active: 14, deleted: 1 },
};

export const CONTENT_SECTIONS: ContentSectionSummary[] = [
  { key: 'home', is_configured: true, updated_at: '2026-09-15T06:00:00Z', updated_by_id: 1 },
  { key: 'contacts', is_configured: true, updated_at: '2026-09-16T06:00:00Z', updated_by_id: 1 },
  { key: 'delivery', is_configured: false, updated_at: null, updated_by_id: null },
  { key: 'faq', is_configured: true, updated_at: '2026-09-10T06:00:00Z', updated_by_id: 1 },
  { key: 'requisites', is_configured: false, updated_at: null, updated_by_id: null },
  { key: 'settings', is_configured: true, updated_at: '2026-09-01T06:00:00Z', updated_by_id: 1 },
];
