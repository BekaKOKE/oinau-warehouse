/**
 * Чистые функции склада: фильтры, тело PUT остатков (Decimal строкой),
 * разбор ошибок, формы склада.
 */

import { ApiError } from '@oinau/api-client';
import { describe, expect, it } from 'vitest';

import {
  availableTone,
  buildStockItems,
  buildWarehouseCreate,
  buildWarehouseUpdate,
  changedEntries,
  DEFAULT_STOCK_FILTERS,
  draftFromStock,
  EMPTY_WAREHOUSE_FORM,
  formFromWarehouse,
  parseStockFilters,
  serializeStockFilters,
  stockErrorsFromApi,
  stockListQuery,
  syncSourceMeta,
  validateWarehouseForm,
  warehouseErrorsFromApi,
} from '@/lib/stock';

import { makeStock } from './product-fixtures';
import { makeWarehouse } from './stock-fixtures';

describe('фильтры остатков в адресе', () => {
  it('разбор, запись и запрос к backend', () => {
    const filters = parseStockFilters(
      new URLSearchParams(
        'search=кан&warehouse=2&source=1c&availability=IN_STOCK&sort=updated&page=3',
      ),
    );
    expect(filters).toEqual({
      search: 'кан',
      warehouseId: '2',
      source: '1c',
      availability: 'IN_STOCK',
      sort: 'updated',
      page: 3,
    });
    expect(serializeStockFilters(filters)).toBe(
      '?search=%D0%BA%D0%B0%D0%BD&warehouse=2&source=1c&availability=IN_STOCK&sort=updated&page=3',
    );
    expect(stockListQuery(filters, 24)).toEqual({
      search: 'кан',
      warehouse_id: 2,
      sync_source: '1c',
      availability: 'IN_STOCK',
      sort: 'updated',
      page: 3,
      page_size: 24,
    });
  });

  it('мусор в адресе отбрасывается; по умолчанию — пустой адрес', () => {
    expect(
      parseStockFilters(
        new URLSearchParams('warehouse=x&source=ftp&availability=MAYBE&sort=drop&page=-1'),
      ),
    ).toEqual(DEFAULT_STOCK_FILTERS);
    expect(serializeStockFilters(DEFAULT_STOCK_FILTERS)).toBe('');
  });
});

describe('правка остатков', () => {
  it('только изменённые склады, количества — строками без потери точности', () => {
    const stock = makeStock();
    const initial = draftFromStock(stock);
    expect(initial[1]).toEqual({ quantity: '152.5', reserved: '2.5' });

    const draft = { ...initial, 1: { quantity: '12 345 678 901,125', reserved: '0,5' } };
    const changed = changedEntries(stock.entries ?? [], draft, initial);
    expect(changed.map((entry) => entry.warehouse_id)).toEqual([1]);
    expect(buildStockItems(changed, draft)).toEqual({
      items: [{ warehouse_id: 1, quantity: '12345678901.125', reserved: '0.5' }],
      errors: {},
    });
  });

  it('пустой резерв — ноль; резерв больше остатка и лишние знаки — ошибки у полей', () => {
    const stock = makeStock();
    const entries = stock.entries ?? [];
    expect(
      buildStockItems(entries.slice(0, 1), { 1: { quantity: '5', reserved: '' } }).items,
    ).toEqual([{ warehouse_id: 1, quantity: '5', reserved: '0' }]);
    expect(
      buildStockItems(entries.slice(0, 1), { 1: { quantity: '5', reserved: '5.001' } }),
    ).toEqual({
      items: [],
      errors: { '1.reserved': 'Резерв больше остатка' },
    });
    expect(
      buildStockItems(entries.slice(0, 1), { 1: { quantity: '1.2345', reserved: '-1' } }).errors,
    ).toEqual({
      '1.quantity': 'Не больше 3 знаков после запятой',
      '1.reserved': 'Введите неотрицательное число',
    });
  });

  it('422 backend: позиция тела запроса → склад', () => {
    const error = new ApiError(422, 'validation_error', 'x', {
      fields: [
        { loc: ['body', 'items', 1], msg: 'Value error, Резерв 9 больше остатка 1' },
        { loc: ['body', 'items', 0, 'quantity'], msg: 'Слишком много знаков' },
        { loc: ['body', 'items'], msg: 'Склад указан в запросе несколько раз' },
      ],
    });
    const sent = [
      { warehouse_id: 7, quantity: '1', reserved: '0' },
      { warehouse_id: 9, quantity: '1', reserved: '9' },
    ];
    const mapped = stockErrorsFromApi(error, sent);
    expect(mapped.fields['9.reserved']).toContain('Резерв 9 больше остатка 1');
    expect(mapped.fields['7.quantity']).toBe('Слишком много знаков');
    expect(mapped.form).toBe('Склад указан в запросе несколько раз');
  });

  it('подписи источника и тон свободного остатка', () => {
    expect(syncSourceMeta('1c').label).toBe('1С');
    expect(syncSourceMeta(null).label).toBe('Нет данных');
    expect(syncSourceMeta('api').label).toBe('api');
    expect(availableTone('0.000')).toBe('danger');
    expect(availableTone('0.001')).toBe('success');
  });
});

describe('форма склада', () => {
  it('создание и проверка кода', () => {
    expect(
      Object.keys(
        validateWarehouseForm({ ...EMPTY_WAREHOUSE_FORM, code: 'Main Склад' }, true),
      ).sort(),
    ).toEqual(['code', 'name']);
    expect(
      buildWarehouseCreate({
        code: ' main-2 ',
        name: ' Склад ',
        regionId: '3',
        externalId: '',
        isActive: true,
      }),
    ).toEqual({ code: 'main-2', name: 'Склад', region_id: 3, external_id: null, is_active: true });
  });

  it('правка: только изменения, кода нет; снятие региона — null', () => {
    const initial = formFromWarehouse(makeWarehouse({ external_id: '1C-1' }));
    const payload = buildWarehouseUpdate(
      { ...initial, code: 'other', regionId: '', externalId: '', isActive: false },
      initial,
    );
    expect(payload).toEqual({ region_id: null, external_id: null, is_active: false });
    expect(payload).not.toHaveProperty('code');
    expect(validateWarehouseForm({ ...initial, code: 'BAD CODE' }, false)).toEqual({});
  });

  it('ошибки backend по полям', () => {
    expect(warehouseErrorsFromApi(new ApiError(409, 'warehouse_code_exists', 'Код занят'))).toEqual(
      {
        code: 'Код занят',
      },
    );
    expect(
      warehouseErrorsFromApi(new ApiError(409, 'external_id_exists', 'Внешний код занят')),
    ).toEqual({
      externalId: 'Внешний код занят',
    });
    expect(warehouseErrorsFromApi(new ApiError(404, 'not_found', 'Склад не найден'))).toEqual({
      _form: 'Склад не найден',
    });
    expect(
      warehouseErrorsFromApi(
        new ApiError(422, 'validation_error', 'x', {
          fields: [{ loc: ['body', 'region_id'], msg: 'Регион не найден' }],
        }),
      ),
    ).toEqual({ regionId: 'Регион не найден' });
  });
});
