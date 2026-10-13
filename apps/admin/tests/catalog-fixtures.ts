/**
 * Категории и характеристики для тестов — формы из сгенерированных типов.
 */

import type { AttributeRead, CategoryRead, CategoryTreeNode } from '@/lib/api/types';

export function treeNode(
  overrides: Partial<CategoryTreeNode> & Pick<CategoryTreeNode, 'id' | 'name' | 'slug'>,
): CategoryTreeNode {
  return {
    parent_id: null,
    depth: 0,
    sort_order: 0,
    is_active: true,
    products_count: 0,
    deleted_at: null,
    children: [],
    ...overrides,
  };
}

/**
 * Комплектующие (1)
 *   ├─ Канаты (2), 3 товара
 *   │    └─ Стальные (4)
 *   └─ Крепления (3), скрыта
 * Сиденья (5)
 */
export function makeTree(): CategoryTreeNode[] {
  return [
    treeNode({
      id: 1,
      name: 'Комплектующие',
      slug: 'komplektuyushchie',
      products_count: 1,
      children: [
        treeNode({
          id: 2,
          name: 'Канаты',
          slug: 'kanaty',
          parent_id: 1,
          depth: 1,
          products_count: 3,
          children: [
            treeNode({ id: 4, name: 'Стальные', slug: 'stalnye', parent_id: 2, depth: 2 }),
          ],
        }),
        treeNode({
          id: 3,
          name: 'Крепления',
          slug: 'krepleniya',
          parent_id: 1,
          depth: 1,
          is_active: false,
        }),
      ],
    }),
    treeNode({ id: 5, name: 'Сиденья', slug: 'sideniya' }),
  ];
}

export function makeCategory(overrides: Partial<CategoryRead> = {}): CategoryRead {
  return {
    id: 2,
    slug: 'kanaty',
    parent_id: 1,
    path: '1.2',
    depth: 1,
    sort_order: 0,
    is_active: true,
    external_id: null,
    name: 'Канаты',
    translations: {
      ru: {
        name: 'Канаты',
        description: 'Канаты для площадок',
        seo_title: 'Канаты SEO',
        seo_description: null,
      },
    },
    products_count: 3,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
    deleted_at: null,
    ...overrides,
  };
}

export function makeAttribute(overrides: Partial<AttributeRead> = {}): AttributeRead {
  return {
    id: 10,
    code: 'diameter',
    value_type: 'NUMBER',
    unit: 'мм',
    is_filterable: true,
    is_visible: true,
    is_active: true,
    sort_order: 1,
    name: 'Диаметр',
    names: { ru: 'Диаметр' },
    options: [],
    usage_count: 0,
    categories: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

export function materialAttribute(overrides: Partial<AttributeRead> = {}): AttributeRead {
  return makeAttribute({
    id: 11,
    code: 'material',
    value_type: 'OPTION',
    unit: null,
    name: 'Материал',
    names: { ru: 'Материал' },
    options: [
      { id: 100, slug: 'pp', sort_order: 0, values: { ru: 'Полипропилен' } },
      { id: 101, slug: 'steel', sort_order: 1, values: { ru: 'Сталь' } },
    ],
    usage_count: 4,
    categories: [{ id: 2, slug: 'kanaty', name: 'Канаты' }],
    ...overrides,
  });
}
