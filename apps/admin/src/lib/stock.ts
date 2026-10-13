/**
 * Остатки и склады: подписи, фильтры списка, формы.
 *
 * Правил склада здесь нет. Свободный остаток, итоги и публичный статус
 * считает backend — экран их только показывает. Фронтенд проверяет лишь
 * то, что backend всё равно отвергнет (формат числа, резерв больше
 * остатка), чтобы не отправлять заведомо плохой запрос.
 */

import { ApiError } from '@/lib/api/client';
import type {
  ProductStock,
  PublicAvailability,
  StockDisplayOverride,
  StockEntry,
  StockListSort,
  StockSource,
  StockUpdate,
  Warehouse,
  WarehouseCreate,
  WarehouseUpdate,
} from '@/lib/api/types';
import { compareDecimal, normalizeDecimalInput } from '@/lib/decimal';
import { extractFieldErrors } from '@/lib/errors';
import { AVAILABILITY, type EnumMeta } from '@/lib/labels';

// ------------------------------------------------------------- подписи

export const SYNC_SOURCE: Record<StockSource, EnumMeta> = {
  manual: { label: 'Вручную', tone: 'neutral' },
  excel: { label: 'Excel', tone: 'info' },
  '1c': { label: '1С', tone: 'accent' },
};

function isStockSource(value: string): value is StockSource {
  return value in SYNC_SOURCE;
}

/** Подпись источника. Строка остатка без данных — «Нет данных». */
export function syncSourceMeta(value: string | null | undefined): EnumMeta {
  if (!value) return { label: 'Нет данных', tone: 'neutral' };
  return isStockSource(value) ? SYNC_SOURCE[value] : { label: value, tone: 'neutral' };
}

export const OVERRIDE_OPTIONS: { value: StockDisplayOverride | ''; label: string }[] = [
  { value: '', label: 'Автоматически — по остаткам' },
  { value: 'IN_STOCK', label: 'Всегда «В наличии»' },
  { value: 'OUT_OF_STOCK', label: 'Всегда «Нет в наличии»' },
  { value: 'ON_REQUEST', label: 'Всегда «Под заказ»' },
];

export const STOCK_SORT: Record<StockListSort, string> = {
  sku: 'По артикулу',
  name: 'По названию',
  available_asc: 'Свободно: меньше сначала',
  available_desc: 'Свободно: больше сначала',
  updated: 'Недавно изменённые',
};

/** Свободный остаток backend → тон бейджа. Сравнение строк, без float. */
export function availableTone(available: string): EnumMeta['tone'] {
  return compareDecimal(available, '0') > 0 ? 'success' : 'danger';
}

// --------------------------------------------------------- фильтры списка

export type StockFilters = {
  search: string;
  warehouseId: string;
  source: StockSource | '';
  availability: PublicAvailability | '';
  sort: StockListSort;
  page: number;
};

export const DEFAULT_STOCK_FILTERS: StockFilters = {
  search: '',
  warehouseId: '',
  source: '',
  availability: '',
  sort: 'sku',
  page: 1,
};

export function parseStockFilters(params: URLSearchParams): StockFilters {
  const warehouse = params.get('warehouse') ?? '';
  const source = params.get('source') ?? '';
  const availability = params.get('availability') ?? '';
  const sort = params.get('sort') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  return {
    search: (params.get('search') ?? '').slice(0, 100),
    warehouseId: /^\d+$/.test(warehouse) ? warehouse : '',
    source: isStockSource(source) ? source : '',
    availability: availability in AVAILABILITY ? (availability as PublicAvailability) : '',
    sort: sort in STOCK_SORT ? (sort as StockListSort) : 'sku',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function serializeStockFilters(filters: StockFilters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.warehouseId) params.set('warehouse', filters.warehouseId);
  if (filters.source) params.set('source', filters.source);
  if (filters.availability) params.set('availability', filters.availability);
  if (filters.sort !== 'sku') params.set('sort', filters.sort);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function stockListQuery(filters: StockFilters, pageSize: number) {
  return {
    search: filters.search.trim() || undefined,
    warehouse_id: filters.warehouseId ? Number(filters.warehouseId) : undefined,
    sync_source: filters.source || undefined,
    availability: filters.availability || undefined,
    sort: filters.sort,
    page: filters.page,
    page_size: pageSize,
  };
}

// ------------------------------------------------------- правка остатков

export type StockDraft = Record<number, { quantity: string; reserved: string }>;

/** «152.500» → «152.5»: в поле ввода без хвостовых нулей. */
export function trimQuantity(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value;
}

export function draftFromStock(stock: ProductStock): StockDraft {
  const draft: StockDraft = {};
  for (const entry of stock.entries ?? []) {
    draft[entry.warehouse_id] = {
      quantity: trimQuantity(entry.quantity),
      reserved: trimQuantity(entry.reserved),
    };
  }
  return draft;
}

export function changedEntries(
  entries: readonly StockEntry[],
  draft: StockDraft,
  initial: StockDraft,
): StockEntry[] {
  return entries.filter((entry) => {
    const value = draft[entry.warehouse_id];
    const before = initial[entry.warehouse_id];
    return (
      value && before && (value.quantity !== before.quantity || value.reserved !== before.reserved)
    );
  });
}

export type StockItemsResult = { items: StockUpdate['items']; errors: Record<string, string> };

/**
 * Тело PUT по изменённым складам: количества строками, до 3 знаков
 * (NUMERIC(14,3)). Ошибки — по ключу `{warehouse_id}.quantity|reserved`.
 */
export function buildStockItems(
  changed: readonly StockEntry[],
  draft: StockDraft,
): StockItemsResult {
  const errors: Record<string, string> = {};
  const items: StockUpdate['items'] = [];
  for (const entry of changed) {
    const value = draft[entry.warehouse_id];
    if (!value) continue;
    const quantity = normalizeDecimalInput(value.quantity, { maxFraction: 3 });
    const reserved = normalizeDecimalInput(value.reserved.trim() || '0', { maxFraction: 3 });
    if (!quantity.ok) errors[`${entry.warehouse_id}.quantity`] = quantity.error;
    if (!reserved.ok) errors[`${entry.warehouse_id}.reserved`] = reserved.error;
    if (!quantity.ok || !reserved.ok) continue;
    if (compareDecimal(reserved.value, quantity.value) > 0) {
      errors[`${entry.warehouse_id}.reserved`] = 'Резерв больше остатка';
      continue;
    }
    items.push({
      warehouse_id: entry.warehouse_id,
      quantity: quantity.value,
      reserved: reserved.value,
    });
  }
  return { items, errors };
}

/**
 * 422 backend → ошибки полей. Путь `items.{i}.quantity` указывает на
 * позицию в теле запроса, поэтому нужен тот же список, что ушёл в PUT;
 * ошибка всей позиции (`items.{i}`, проверка резерва) — у резерва.
 */
export function stockErrorsFromApi(
  error: unknown,
  sent: StockUpdate['items'],
): { fields: Record<string, string>; form?: string } {
  const raw = extractFieldErrors(error);
  const fields: Record<string, string> = {};
  let form: string | undefined;
  for (const [path, message] of Object.entries(raw)) {
    const match = /^items\.(\d+)(?:\.(quantity|reserved))?$/.exec(path);
    const item = match ? sent[Number(match[1])] : undefined;
    if (match && item) fields[`${item.warehouse_id}.${match[2] ?? 'reserved'}`] = message;
    else form = form ?? message;
  }
  return { fields, form };
}

// ------------------------------------------------------------------ склады

export type WarehouseForm = {
  code: string;
  name: string;
  regionId: string;
  externalId: string;
  isActive: boolean;
};

export type WarehouseFormErrors = Partial<Record<keyof WarehouseForm | '_form', string>>;

export const EMPTY_WAREHOUSE_FORM: WarehouseForm = {
  code: '',
  name: '',
  regionId: '',
  externalId: '',
  isActive: true,
};

export const WAREHOUSE_CODE_PATTERN = /^[a-z0-9_-]+$/;

export function formFromWarehouse(warehouse: Warehouse): WarehouseForm {
  return {
    code: warehouse.code,
    name: warehouse.name,
    regionId: warehouse.region_id ? String(warehouse.region_id) : '',
    externalId: warehouse.external_id ?? '',
    isActive: warehouse.is_active,
  };
}

export function validateWarehouseForm(form: WarehouseForm, creating: boolean): WarehouseFormErrors {
  const errors: WarehouseFormErrors = {};
  if (!form.name.trim()) errors.name = 'Введите название';
  else if (form.name.trim().length > 255) errors.name = 'Не длиннее 255 символов';
  if (creating) {
    const code = form.code.trim();
    if (!code) errors.code = 'Введите код';
    else if (code.length > 64) errors.code = 'Не длиннее 64 символов';
    else if (!WAREHOUSE_CODE_PATTERN.test(code)) {
      errors.code = 'Только строчная латиница, цифры, «-» и «_»';
    }
  }
  if (form.externalId.trim().length > 64) errors.externalId = 'Не длиннее 64 символов';
  return errors;
}

export function buildWarehouseCreate(form: WarehouseForm): WarehouseCreate {
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    region_id: form.regionId ? Number(form.regionId) : null,
    external_id: form.externalId.trim() || null,
    is_active: form.isActive,
  };
}

/** Только изменённые поля; кода в WarehouseUpdate нет — он неизменяем. */
export function buildWarehouseUpdate(form: WarehouseForm, initial: WarehouseForm): WarehouseUpdate {
  const payload: WarehouseUpdate = {};
  if (form.name.trim() !== initial.name) payload.name = form.name.trim();
  if (form.regionId !== initial.regionId) {
    payload.region_id = form.regionId ? Number(form.regionId) : null;
  }
  if (form.externalId.trim() !== initial.externalId) {
    payload.external_id = form.externalId.trim() || null;
  }
  if (form.isActive !== initial.isActive) payload.is_active = form.isActive;
  return payload;
}

export function warehouseErrorsFromApi(error: unknown): WarehouseFormErrors {
  if (error instanceof ApiError && error.status === 409) {
    if (error.code === 'warehouse_code_exists') return { code: error.message };
    if (error.code === 'external_id_exists') return { externalId: error.message };
    return { _form: error.message };
  }
  if (error instanceof ApiError && error.status === 404) return { _form: error.message };
  const fields = extractFieldErrors(error);
  const map: Record<string, keyof WarehouseFormErrors> = {
    code: 'code',
    name: 'name',
    region_id: 'regionId',
    external_id: 'externalId',
    is_active: 'isActive',
  };
  const result: WarehouseFormErrors = {};
  for (const [path, message] of Object.entries(fields)) {
    const key = map[path] ?? '_form';
    result[key] = result[key] ?? message;
  }
  return result;
}
