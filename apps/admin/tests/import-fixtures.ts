/**
 * Импорт и экспорт каталога: ответы backend в тестах.
 *
 * Формы взяты из сгенерированных типов — руками ничего не описывается.
 */

import type {
  ImportCommitResult,
  ImportJob,
  ImportJobDetail,
  ImportIssue,
  ImportPreview,
  ImportSummary,
} from '@/lib/api/types';

export const EXPORT_URL = '/api/v1/admin/catalog/export';
export const TEMPLATE_URL = '/api/v1/admin/catalog/imports/template';
export const PREVIEW_URL = '/api/v1/admin/catalog/imports/preview';
export const HISTORY_URL = '/api/v1/admin/catalog/imports';
export const JOB_UUID = '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60';
export const COMMIT_URL = `${HISTORY_URL}/${JOB_UUID}/commit`;
export const JOB_URL = `${HISTORY_URL}/${JOB_UUID}`;

export function makeSummary(overrides: Partial<ImportSummary> = {}): ImportSummary {
  return {
    rows_total: 12,
    sheets: { Products: 3, Prices: 4 },
    products: { create: 2, update: 1, unchanged: 5 },
    categories: { create: 0, update: 1, unchanged: 3 },
    attributes: { create: 0, update: 0, unchanged: 2 },
    attribute_options: { create: 1, update: 0, unchanged: 0 },
    ...overrides,
  };
}

export function makeJob(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    uuid: JOB_UUID,
    kind: 'catalog',
    status: 'VALID',
    filename: 'catalog.xlsx',
    file_size: 2048,
    file_sha256: 'a'.repeat(64),
    rows_total: 12,
    products_created: 2,
    products_updated: 1,
    products_unchanged: 5,
    error_count: 0,
    warning_count: 0,
    failure_code: null,
    created_by_id: 1,
    committed_by_id: null,
    created_at: '2026-09-17T06:00:00Z',
    committed_at: null,
    expires_at: '2026-09-18T06:00:00Z',
    can_commit: true,
    ...overrides,
  };
}

export function makeIssue(overrides: Partial<ImportIssue> = {}): ImportIssue {
  return {
    sheet: 'Products',
    row: 12,
    column: 'sku',
    code: 'required',
    message: 'Значение обязательно',
    value: null,
    ...overrides,
  };
}

export function makePreview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    job: makeJob(),
    valid: true,
    summary: makeSummary(),
    error_count: 0,
    errors: [],
    warning_count: 0,
    warnings: [],
    changes: [
      { row: 2, sku: 'KAN-16-PP', action: 'update', changed: ['pricing', 'categories'] },
      { row: 3, sku: 'KAN-20-PP', action: 'create', changed: [] },
    ],
    changes_truncated: false,
    ...overrides,
  };
}

export function invalidPreview(): ImportPreview {
  return makePreview({
    job: makeJob({ status: 'INVALID', can_commit: false, error_count: 2, warning_count: 1 }),
    valid: false,
    error_count: 2,
    errors: [
      makeIssue(),
      makeIssue({
        row: 14,
        column: 'price',
        code: 'invalid_value',
        message: 'Цена должна быть больше нуля',
        value: '-10',
      }),
    ],
    warning_count: 1,
    warnings: [
      makeIssue({
        row: 15,
        column: null,
        code: 'product_without_price',
        message: 'У товара не будет цены',
      }),
    ],
    changes: [],
  });
}

export function makeCommit(overrides: Partial<ImportCommitResult> = {}): ImportCommitResult {
  return {
    job: makeJob({
      status: 'COMMITTED',
      can_commit: false,
      committed_at: '2026-09-17T06:05:00Z',
      committed_by_id: 1,
    }),
    summary: makeSummary(),
    warnings: [],
    ...overrides,
  };
}

export function makeJobDetail(overrides: Partial<ImportJobDetail> = {}): ImportJobDetail {
  return {
    ...makeJob({ status: 'COMMITTED', can_commit: false, committed_at: '2026-09-17T06:05:00Z' }),
    summary: makeSummary(),
    errors: [],
    warnings: [],
    ...overrides,
  };
}
