/**
 * Чистые функции раздела товаров: фильтры, форма, характеристики, цены,
 * медиа. Decimal нигде не проходит через Number.
 */

import { ApiError } from '@oinau/api-client';
import { describe, expect, it } from 'vitest';

import { buildAttributeItems, buildDefs, sameItems, valuesFromProduct } from '@/lib/attributes';
import { normalizeDecimalInput } from '@/lib/decimal';
import { hasPendingImages, moveItem } from '@/lib/media';
import { listPrice, newTierRow, previewPrice, validatePricing } from '@/lib/pricing';
import {
  buildCreatePayload,
  buildUpdatePayload,
  formFromProduct,
  mainFormErrorsFromApi,
  validateMainForm,
} from '@/lib/productForm';
import {
  flattenCategoryTree,
  productFiltersFromParams,
  productFiltersToQuery,
  productFiltersToSearch,
  skuError,
  slugError,
  slugFromName,
} from '@/lib/products';

import {
  CATEGORY_ATTRIBUTES,
  CATEGORY_TREE,
  MATERIAL_ATTRIBUTE,
  makeImage,
  makeProduct,
} from './product-fixtures';

const NBSP = ' ';

describe('фильтры списка товаров', () => {
  it('разбирает адрес и отбрасывает неизвестные значения', () => {
    const filters = productFiltersFromParams(
      new URLSearchParams(
        'status=PUBLISHED&is_active=false&is_featured=maybe&category_id=x&include_deleted=true&sort=price&page=3',
      ),
    );
    expect(filters).toMatchObject({
      status: 'PUBLISHED',
      active: 'false',
      featured: '',
      categoryId: '',
      includeDeleted: true,
      sort: 'updated',
      page: 3,
    });
  });

  it('пишет в адрес только заданные значения и строит query backend', () => {
    const filters = productFiltersFromParams(new URLSearchParams(''));
    const next = {
      ...filters,
      active: 'true' as const,
      categoryId: '2',
      externalId: ' 1C-1 ',
      sort: 'sku' as const,
    };
    expect(productFiltersToSearch(next)).toBe(
      '?is_active=true&category_id=2&external_id=1C-1&sort=sku',
    );
    expect(productFiltersToQuery(next)).toEqual({
      search: undefined,
      status: undefined,
      is_active: true,
      is_featured: undefined,
      category_id: 2,
      external_id: '1C-1',
      include_deleted: undefined,
      sort: 'sku',
      page: 1,
      page_size: 24,
    });
  });
});

describe('артикул, slug, категории', () => {
  it('формат артикула и slug как у backend', () => {
    expect(skuError('KAN-16/PP.1_a')).toBeNull();
    expect(skuError('КАН 16')).not.toBeNull();
    expect(slugError('kanat-16')).toBeNull();
    expect(slugError('Kanat_16')).not.toBeNull();
  });

  it('slug из названия — транслитерация только по кнопке', () => {
    expect(slugFromName('Канат полипропиленовый Ø16 мм')).toBe('kanat-polipropilenovyy-16-mm');
    expect(slugFromName('Қазақ өнім')).toBe('kazak-onim');
  });

  it('дерево категорий раскладывается с путём', () => {
    const flat = flattenCategoryTree(CATEGORY_TREE);
    expect(flat.map((item) => item.path)).toEqual([
      'Комплектующие',
      'Комплектующие / Канаты',
      'Комплектующие / Крепления',
    ]);
    expect(flat[2]?.isActive).toBe(false);
  });
});

describe('основная форма товара', () => {
  it('PATCH содержит только изменения, перевод — целиком с SEO-полями', () => {
    const product = makeProduct();
    const form = { ...formFromProduct(product), name: 'Канат 16 мм', minOrderQty: '10,5' };
    expect(buildUpdatePayload(form, product)).toEqual({
      min_order_qty: '10.5',
      translations: {
        ru: {
          name: 'Канат 16 мм',
          short_description: 'Армированный канат',
          description: null,
          seo_title: 'SEO заголовок каната',
          seo_description: 'SEO описание',
        },
      },
    });
    expect(buildUpdatePayload(formFromProduct(product), product)).toEqual({});
  });

  it('min_order_qty из API «1.000» не считается изменением', () => {
    expect(formFromProduct(makeProduct()).minOrderQty).toBe('1');
  });

  it('локальная проверка обязательных полей', () => {
    const errors = validateMainForm({
      ...formFromProduct(makeProduct()),
      name: ' ',
      sku: 'a b',
      minOrderQty: '0',
    });
    expect(Object.keys(errors).sort()).toEqual(['minOrderQty', 'name', 'sku']);
  });

  it('создание: категории и характеристики в том же запросе, пустые поля — null', () => {
    const form = { ...formFromProduct(makeProduct()), brand: '', externalId: '' };
    const payload = buildCreatePayload(form, {
      categories: [{ category_id: 2, is_primary: true, sort_order: 0 }],
      attributes: [{ attribute_id: 10, value_numeric: '16' }],
    });
    expect(payload).toMatchObject({ brand: null, external_id: null, min_order_qty: '1' });
    expect(payload.translations.ru?.name).toBe('Канат полипропиленовый 16 мм');
    expect(payload.categories).toHaveLength(1);
  });

  it('409 и 422 backend привязываются к полям', () => {
    expect(mainFormErrorsFromApi(new ApiError(409, 'sku_exists', 'Артикул уже занят'))).toEqual({
      sku: 'Артикул уже занят',
    });
    expect(mainFormErrorsFromApi(new ApiError(409, 'product_slug_exists', 'Slug занят'))).toEqual({
      slug: 'Slug занят',
    });
    expect(
      mainFormErrorsFromApi(
        new ApiError(422, 'validation_error', 'x', {
          fields: [
            { loc: ['body', 'translations', 'ru', 'name'], msg: 'Field required' },
            { loc: ['body'], msg: 'Value error, Обязателен перевод для локали ru' },
          ],
        }),
      ),
    ).toEqual({ name: 'Field required', _form: 'Обязателен перевод для локали ru' });
  });
});

describe('характеристики', () => {
  const defs = buildDefs([CATEGORY_ATTRIBUTES], makeProduct().attributes ?? [], {
    11: MATERIAL_ATTRIBUTE.options ?? [],
  });

  it('значения товара → форма → тело PUT без изменений', () => {
    const values = valuesFromProduct(makeProduct().attributes ?? []);
    const built = buildAttributeItems(defs, values);
    expect(built).toEqual({
      ok: true,
      items: [
        { attribute_id: 10, value_numeric: '16' },
        { attribute_id: 11, option_id: 100 },
      ],
    });
  });

  it('все типы backend: число (в т.ч. отрицательное), да/нет, несколько вариантов, текст', () => {
    const built = buildAttributeItems(defs, {
      10: { type: 'NUMBER', text: '-2,5' },
      11: { type: 'OPTION', optionIds: [100, 101] },
      12: { type: 'BOOLEAN', value: 'false' },
      13: { type: 'STRING', text: '  синий ' },
    });
    expect(built.ok && built.items).toEqual([
      { attribute_id: 10, value_numeric: '-2.5' },
      { attribute_id: 11, option_id: 100 },
      { attribute_id: 11, option_id: 101 },
      { attribute_id: 12, value_bool: false },
      { attribute_id: 13, value_string: 'синий' },
    ]);
  });

  it('некорректное число — ошибка у характеристики, а не округление', () => {
    const built = buildAttributeItems(defs, { 10: { type: 'NUMBER', text: '1.2345' } });
    expect(built).toEqual({ ok: false, errors: { 10: 'Не больше 3 знаков после запятой' } });
  });

  it('сравнение наборов не зависит от порядка', () => {
    expect(
      sameItems(
        [
          { attribute_id: 1, option_id: 2 },
          { attribute_id: 1, option_id: 3 },
        ],
        [
          { attribute_id: 1, option_id: 3 },
          { attribute_id: 1, option_id: 2 },
        ],
      ),
    ).toBe(true);
  });
});

describe('цены', () => {
  it('FIXED: одна ступень от 1 без верхней границы, цена строкой', () => {
    const result = validatePricing('FIXED', [newTierRow({ price: '3 500,50' })]);
    expect(result).toEqual({
      ok: true,
      payload: { pricing_type: 'FIXED', tiers: [{ min_qty: '1', max_qty: null, price: '3500.5' }] },
    });
  });

  it('TIERED: ступени сортируются, значения не проходят через float', () => {
    const result = validatePricing('TIERED', [
      newTierRow({ minQty: '10', maxQty: '', price: '0.1' }),
      newTierRow({ minQty: '1', maxQty: '9.999', price: '0.30' }),
    ]);
    expect(result).toEqual({
      ok: true,
      payload: {
        pricing_type: 'TIERED',
        tiers: [
          { min_qty: '1', max_qty: '9.999', price: '0.3' },
          { min_qty: '10', max_qty: null, price: '0.1' },
        ],
      },
    });
  });

  it('пересечение, две открытые ступени и лишние знаки — ошибки', () => {
    const overlap = validatePricing('TIERED', [
      newTierRow({ minQty: '1', maxQty: '10', price: '5' }),
      newTierRow({ minQty: '10', maxQty: '20', price: '4' }),
    ]);
    expect(overlap.ok).toBe(false);

    const open = validatePricing('FROM', [
      newTierRow({ minQty: '1', price: '5' }),
      newTierRow({ minQty: '50', price: '4' }),
    ]);
    expect(open).toMatchObject({
      ok: false,
      form: 'Открытая ступень («и более») может быть только одна',
    });

    const row = newTierRow({ minQty: '1', price: '10.001' });
    expect(validatePricing('TIERED', [row])).toEqual({
      ok: false,
      rows: { [row.key]: { price: 'Не больше 2 знаков после запятой' } },
    });
  });

  it('ON_REQUEST — без ступеней', () => {
    expect(validatePricing('ON_REQUEST', [newTierRow({ price: '1' })])).toEqual({
      ok: true,
      payload: { pricing_type: 'ON_REQUEST', tiers: [] },
    });
  });

  it('превью совпадает с правилами витрины', () => {
    expect(
      previewPrice(
        { pricing_type: 'FIXED', tiers: [{ min_qty: '1', price: '3500.00' }] },
        'm',
        'KZT',
      ).headline,
    ).toBe(`3${NBSP}500 ₸ / м`);
    const tiered = previewPrice(
      {
        pricing_type: 'TIERED',
        tiers: [
          { min_qty: '1', max_qty: '9', price: '3500.00' },
          { min_qty: '10', max_qty: null, price: '2600.50' },
        ],
      },
      'pcs',
      'KZT',
    );
    expect(tiered.headline).toBe(`от 2${NBSP}600,50 ₸ / шт`);
    expect(tiered.table).toEqual([
      { range: '1–9', price: `3${NBSP}500${NBSP}₸` },
      { range: '10 и более', price: `2${NBSP}600,50${NBSP}₸` },
    ]);
    expect(previewPrice({ pricing_type: 'ON_REQUEST', tiers: [] }, 'm', 'KZT').headline).toBe(
      'Цена по запросу',
    );
  });

  it('цена в строке списка', () => {
    expect(listPrice('TIERED', '2600.00', 'KZT')).toBe(`от 2${NBSP}600${NBSP}₸`);
    expect(listPrice('FIXED', '1200.50', 'KZT')).toBe(`1${NBSP}200,50${NBSP}₸`);
    expect(listPrice('ON_REQUEST', null, 'KZT')).toBe('По запросу');
    expect(listPrice('FIXED', null, 'KZT')).toBe('Нет цены');
  });

  it('отрицательные числа разрешаются только явно', () => {
    expect(normalizeDecimalInput('-1', { maxFraction: 2 }).ok).toBe(false);
    expect(normalizeDecimalInput('-0', { maxFraction: 2, allowNegative: true })).toEqual({
      ok: true,
      value: '0',
    });
  });
});

describe('медиа', () => {
  it('перемещение изображения', () => {
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
    expect(moveItem(['a', 'b'], 0, 5)).toEqual(['a', 'b']);
  });

  it('галерея ждёт воркера, пока есть PENDING/PROCESSING', () => {
    expect(hasPendingImages({ product_id: 1, items: [makeImage({ status: 'READY' })] })).toBe(
      false,
    );
    expect(hasPendingImages({ product_id: 1, items: [makeImage({ status: 'PROCESSING' })] })).toBe(
      true,
    );
  });
});
