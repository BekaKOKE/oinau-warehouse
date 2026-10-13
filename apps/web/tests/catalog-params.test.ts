/**
 * URL каталога — часть контракта: ссылку с фильтрами пересылают
 * коллеге и открывают из истории браузера.
 */

import { describe, expect, it } from 'vitest';

import {
  activeChips,
  buildCatalogQuery,
  catalogHref,
  parseCatalogParams,
  toProductQuery,
} from '@/lib/catalog-params';

describe('parseCatalogParams', () => {
  it('читает все поддерживаемые параметры', () => {
    const filters = parseCatalogParams({
      category: 'kanaty-i-seti',
      search: 'канат',
      availability: 'IN_STOCK',
      min_price: '1000',
      max_price: '5000.50',
      sort: 'price_asc',
      page: '3',
      attr: ['color:black', 'material:pp'],
      view: 'grid',
      per_page: '48',
    });

    expect(filters).toEqual({
      category: 'kanaty-i-seti',
      search: 'канат',
      availability: 'IN_STOCK',
      minPrice: '1000',
      maxPrice: '5000.50',
      attrs: ['color:black', 'material:pp'],
      sort: 'price_asc',
      page: 3,
      view: 'grid',
      perPage: 48,
    });
  });

  it('подставляет значения по умолчанию для пустого запроса', () => {
    const filters = parseCatalogParams({});
    expect(filters.sort).toBe('relevance');
    expect(filters.page).toBe(1);
    expect(filters.category).toBeUndefined();
    expect(filters.attrs).toEqual([]);
    // Раздел каталога по умолчанию — плитка
    expect(filters.view).toBe('grid');
  });

  it('отбрасывает значения, которых backend не примет', () => {
    const filters = parseCatalogParams({
      sort: 'drop table',
      availability: 'WHATEVER',
      min_price: 'сколько-нибудь',
      page: '-4',
      attr: ['color;drop', 'color:black', 'color:black'],
      per_page: '1000',
    });

    expect(filters.attrs).toEqual(['color:black']);
    expect(filters.perPage).toBeUndefined();

    expect(filters.sort).toBe('relevance');
    expect(filters.availability).toBeUndefined();
    expect(filters.minPrice).toBeUndefined();
    expect(filters.page).toBe(1);
  });

  it('переопределения имеют приоритет — страница категории задаёт раздел', () => {
    const filters = parseCatalogParams({ category: 'other' }, { category: 'kanaty-i-seti' });
    expect(filters.category).toBe('kanaty-i-seti');
  });
});

describe('toProductQuery', () => {
  it('переводит фильтры в параметры API', () => {
    const query = toProductQuery(parseCatalogParams({ search: 'канат', page: '2' }));
    expect(query).toMatchObject({ search: 'канат', page: 2, pageSize: 24 });
  });

  it('плитка — 24 позиции, выбранный размер страницы важнее', () => {
    expect(toProductQuery(parseCatalogParams({ view: 'grid' })).pageSize).toBe(24);
    expect(toProductQuery(parseCatalogParams({ view: 'table' })).pageSize).toBe(60);
    expect(toProductQuery(parseCatalogParams({ per_page: '48' })).pageSize).toBe(48);
  });

  it('передаёт фильтры по характеристикам', () => {
    const query = toProductQuery(parseCatalogParams({ attr: 'color:black' }));
    expect(query.attrs).toEqual(['color:black']);
  });
});

describe('buildCatalogQuery', () => {
  it('не пишет в URL значения по умолчанию', () => {
    expect(buildCatalogQuery({ sort: 'relevance', page: 1 })).toBe('');
  });

  it('собирает строку запроса из заданных фильтров', () => {
    const query = buildCatalogQuery({
      category: 'kanaty-i-seti',
      availability: 'IN_STOCK',
      sort: 'price_asc',
      page: 2,
    });
    expect(query).toContain('category=kanaty-i-seti');
    expect(query).toContain('availability=IN_STOCK');
    expect(query).toContain('sort=price_asc');
    expect(query).toContain('page=2');
  });

  it('фильтры характеристик, вид и размер страницы попадают в URL', () => {
    const query = buildCatalogQuery({
      attrs: ['color:black', 'color:red'],
      view: 'grid',
      perPage: 48,
    });
    expect(query).toBe('?attr=color%3Ablack&attr=color%3Ared&per_page=48');
    expect(buildCatalogQuery({ view: 'table', attrs: [] })).toBe('?view=table');
    expect(buildCatalogQuery({ view: 'grid', attrs: [] })).toBe('');
  });

  it('на странице категории раздел в запрос не дублируется', () => {
    const href = catalogHref(
      { category: 'kanaty-i-seti', sort: 'name' },
      { basePath: '/catalog/kanaty-i-seti', keepCategory: false },
    );
    expect(href).toBe('/catalog/kanaty-i-seti?sort=name');
  });
});

describe('activeChips', () => {
  it('плашка снимает свой фильтр и сбрасывает страницу', () => {
    const filters = parseCatalogParams({
      search: 'канат',
      availability: 'IN_STOCK',
      page: '4',
    });
    const chips = activeChips(filters);

    expect(chips.map((chip) => chip.key)).toEqual(['search', 'availability']);
    const search = chips.find((chip) => chip.key === 'search');
    expect(search?.next.search).toBeUndefined();
    expect(search?.next.availability).toBe('IN_STOCK');
    expect(search?.next.page).toBe(1);
  });

  it('плашка характеристики снимает только своё значение', () => {
    const filters = parseCatalogParams({ attr: ['color:black', 'color:red'] });
    const chips = activeChips(filters, undefined, '₸', { 'color:black': 'Цвет: чёрный' });
    expect(chips.map((chip) => chip.label)).toEqual(['Цвет: чёрный', 'color:red']);
    expect(chips[0]?.next.attrs).toEqual(['color:red']);
  });

  it('не показывает плашку категории без её названия', () => {
    const filters = parseCatalogParams({ category: 'kanaty-i-seti' });
    expect(activeChips(filters)).toHaveLength(0);
    expect(activeChips(filters, 'Канаты и сети')).toHaveLength(1);
  });
});
