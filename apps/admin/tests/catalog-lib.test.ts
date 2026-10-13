/**
 * Чистые функции категорий и характеристик.
 */

import { ApiError } from '@oinau/api-client';
import { describe, expect, it } from 'vitest';

import {
  attributeErrorsFromApi,
  buildAttributeCreate,
  buildAttributeUpdate,
  EMPTY_ATTRIBUTE_FORM,
  formFromAttribute,
  validateAttributeForm,
} from '@/lib/attributeForm';
import {
  assignedFromApi,
  assignedToItems,
  buildCategoryCreate,
  buildCategoryUpdate,
  categoryErrorsFromApi,
  emptyCategoryForm,
  filterTree,
  formFromCategory,
  indexTree,
  isCategoryFormDirty,
  parentOptions,
  pathOf,
  subtreeIds,
  validateCategoryForm,
} from '@/lib/categories';

import { makeAttribute, makeCategory, makeTree, materialAttribute } from './catalog-fixtures';

describe('дерево категорий', () => {
  it('путь, потомки и варианты родителя без самой ветки', () => {
    const tree = makeTree();
    const index = indexTree(tree);
    expect(pathOf(index, 4)).toBe('Комплектующие / Канаты / Стальные');
    const ropes = index.byId.get(2);
    expect([...subtreeIds(ropes!)]).toEqual([2, 4]);
    expect(parentOptions(tree, subtreeIds(ropes!)).map((option) => option.value)).toEqual([
      '1',
      '3',
      '5',
    ]);
    expect(parentOptions(tree, new Set()).find((option) => option.value === '3')?.label).toContain(
      '(скрыта)',
    );
  });

  it('удалённые категории не предлагаются в родители', () => {
    const tree = makeTree();
    tree[1] = { ...tree[1]!, deleted_at: '2026-09-01T00:00:00Z' };
    expect(parentOptions(tree, new Set()).map((option) => option.value)).not.toContain('5');
  });

  it('поиск оставляет совпадения вместе с предками', () => {
    const result = filterTree(makeTree(), 'стальн');
    expect(result.map((node) => node.id)).toEqual([1]);
    expect(result[0]?.children?.map((node) => node.id)).toEqual([2]);
    expect(result[0]?.children?.[0]?.children?.map((node) => node.id)).toEqual([4]);
    expect(filterTree(makeTree(), 'krepl').map((node) => node.id)).toEqual([1]);
  });
});

describe('форма категории', () => {
  it('создание: перевод целиком, пустые поля — null', () => {
    const form = { ...emptyCategoryForm(1), name: 'Канаты', slug: 'kanaty' };
    expect(buildCategoryCreate(form)).toEqual({
      slug: 'kanaty',
      parent_id: 1,
      sort_order: 0,
      is_active: true,
      external_id: null,
      image: null,
      translations: {
        ru: { name: 'Канаты', description: null, seo_title: null, seo_description: null },
      },
    });
  });

  it('обновление: только изменения; перенос в корень — parent_id null', () => {
    const initial = formFromCategory(makeCategory());
    expect(buildCategoryUpdate({ ...initial, parentId: '' }, initial)).toEqual({ parent_id: null });
    expect(buildCategoryUpdate({ ...initial, name: 'Канаты стальные' }, initial)).toEqual({
      translations: {
        ru: {
          name: 'Канаты стальные',
          description: 'Канаты для площадок',
          seo_title: 'Канаты SEO',
          seo_description: null,
        },
      },
    });
    expect(buildCategoryUpdate(initial, initial)).toEqual({});
  });

  it('обложка: выбор, замена и снятие; ссылка на миниатюру не считается изменением', () => {
    const initial = formFromCategory(
      makeCategory({
        image: { uuid: 'aaaaaaaa-0000-4000-8000-000000000001', url: '/thumb-1.webp' },
      }),
    );
    expect(initial.imageUuid).toBe('aaaaaaaa-0000-4000-8000-000000000001');
    expect(initial.imageUrl).toBe('/thumb-1.webp');

    const replaced = {
      ...initial,
      imageUuid: 'bbbbbbbb-0000-4000-8000-000000000002',
      imageUrl: '/thumb-2.webp',
    };
    expect(buildCategoryUpdate(replaced, initial)).toEqual({
      image: 'bbbbbbbb-0000-4000-8000-000000000002',
    });

    // Снятие обложки уходит как null, иначе backend её не тронет.
    expect(buildCategoryUpdate({ ...initial, imageUuid: '', imageUrl: '' }, initial)).toEqual({
      image: null,
    });

    // Миниатюра — поле показа: сама по себе несохранённых изменений не даёт.
    const sameFileOtherUrl = { ...initial, imageUrl: '/thumb-1-resized.webp' };
    expect(buildCategoryUpdate(sameFileOtherUrl, initial)).toEqual({});
    expect(isCategoryFormDirty(sameFileOtherUrl, initial)).toBe(false);
    expect(isCategoryFormDirty(replaced, initial)).toBe(true);
  });

  it('проверка формы и разбор ошибок backend по полям', () => {
    expect(
      Object.keys(
        validateCategoryForm({ ...emptyCategoryForm(), slug: 'Bad slug', sortOrder: 'x' }),
      ).sort(),
    ).toEqual(['name', 'slug', 'sortOrder']);
    expect(categoryErrorsFromApi(new ApiError(409, 'slug_exists', 'Slug уже занят'))).toEqual({
      slug: 'Slug уже занят',
    });
    expect(categoryErrorsFromApi(new ApiError(409, 'category_cycle', 'Цикл'))).toEqual({
      parentId: 'Цикл',
    });
    expect(categoryErrorsFromApi(new ApiError(409, 'category_has_children', 'Есть дети'))).toEqual({
      _form: 'Есть дети',
    });
    expect(
      categoryErrorsFromApi(
        new ApiError(422, 'validation_error', 'x', {
          fields: [{ loc: ['body', 'translations', 'ru', 'name'], msg: 'Field required' }],
        }),
      ),
    ).toEqual({ name: 'Field required' });
  });

  it('характеристики категории: порядок списка становится sort_order', () => {
    const assigned = assignedFromApi([
      {
        attribute_id: 11,
        code: 'material',
        name: 'Материал',
        value_type: 'OPTION',
        unit: null,
        sort_order: 5,
        is_required: true,
      },
      {
        attribute_id: 10,
        code: 'diameter',
        name: 'Диаметр',
        value_type: 'NUMBER',
        unit: 'мм',
        sort_order: 1,
        is_required: false,
      },
    ]);
    expect(assigned.map((item) => item.attribute_id)).toEqual([10, 11]);
    expect(assignedToItems([assigned[1]!, assigned[0]!])).toEqual([
      { attribute_id: 11, sort_order: 0, is_required: true },
      { attribute_id: 10, sort_order: 1, is_required: false },
    ]);
  });
});

describe('форма характеристики', () => {
  it('создание OPTION с вариантами; для других типов варианты не отправляются', () => {
    const form = {
      ...EMPTY_ATTRIBUTE_FORM,
      name: 'Материал',
      code: 'material',
      valueType: 'OPTION' as const,
    };
    const drafts = [
      { key: 'a', value: 'Сталь', slug: 'steel' },
      { key: 'b', value: 'Резина', slug: 'rubber' },
    ];
    expect(buildAttributeCreate(form, drafts).options).toEqual([
      { slug: 'steel', sort_order: 0, values: { ru: 'Сталь' } },
      { slug: 'rubber', sort_order: 1, values: { ru: 'Резина' } },
    ]);
    expect(buildAttributeCreate({ ...form, valueType: 'STRING' }, drafts).options).toEqual([]);
  });

  it('обновление не содержит кода и типа значения', () => {
    const initial = formFromAttribute(materialAttribute());
    const payload = buildAttributeUpdate(
      { ...initial, name: 'Материал изделия', unit: 'шт', valueType: 'STRING', code: 'other' },
      initial,
    );
    expect(payload).toEqual({ names: { ru: 'Материал изделия' }, unit: 'шт' });
    expect(payload).not.toHaveProperty('value_type');
    expect(payload).not.toHaveProperty('code');
  });

  it('код проверяется только при создании; 409 кода — у поля', () => {
    const form = { ...formFromAttribute(makeAttribute()), code: 'Bad Code' };
    expect(validateAttributeForm(form, true).code).toBeDefined();
    expect(validateAttributeForm(form, false).code).toBeUndefined();
    expect(attributeErrorsFromApi(new ApiError(409, 'attribute_code_exists', 'Код занят'))).toEqual(
      { code: 'Код занят' },
    );
  });
});
