/**
 * Состояние каталога живёт в URL, а не в React-состоянии.
 *
 * Иначе отфильтрованную выдачу невозможно отправить коллеге ссылкой,
 * кнопка «назад» теряет фильтры, а серверный рендер не знает, что
 * показывать. Здесь единственное место, где строка запроса
 * превращается в параметры API и обратно.
 */

import type { ProductSort, PublicAvailability } from '@oinau/api-types';

import type { ProductQuery } from '@/lib/api/catalog';
import { CATALOG_PAGE_SIZE, TABLE_PAGE_SIZE } from '@/lib/config';

export type CatalogSearchParams = Record<string, string | string[] | undefined>;

/** Вид выдачи: таблица (по умолчанию, B2B) или плитка. */
export type CatalogView = 'table' | 'grid';

export type CatalogFilters = {
  category?: string;
  search?: string;
  availability?: PublicAvailability;
  minPrice?: string;
  maxPrice?: string;
  /** Фильтры по характеристикам: `код:slug` варианта, как в API. */
  attrs: string[];
  sort: ProductSort;
  page: number;
  view: CatalogView;
  /** Позиций на странице; не задано — по умолчанию для вида. */
  perPage?: number;
};

const SORTS: readonly ProductSort[] = [
  'relevance',
  'newest',
  'price_asc',
  'price_desc',
  'name',
  'sku',
] as const;

export const SORT_LABELS: Record<ProductSort, string> = {
  relevance: 'По релевантности',
  newest: 'Сначала новые',
  price_asc: 'Цена: сначала дешёвые',
  price_desc: 'Цена: сначала дорогие',
  name: 'По названию',
  sku: 'По артикулу',
};

/** Сколько строк можно показать на странице (не больше лимита API). */
export const PER_PAGE_OPTIONS = [24, 48, 60] as const;

/** Та же проверка, что у backend: `код:slug`. */
const ATTR_PATTERN = /^[a-z0-9_]{1,64}:[a-z0-9-]{1,200}$/;
const MAX_ATTRS = 20;

const AVAILABILITIES: readonly PublicAvailability[] = [
  'IN_STOCK',
  'OUT_OF_STOCK',
  'ON_REQUEST',
] as const;

export const AVAILABILITY_LABELS: Record<PublicAvailability, string> = {
  IN_STOCK: 'В наличии',
  OUT_OF_STOCK: 'Нет в наличии',
  ON_REQUEST: 'Под заказ',
};

function many(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return (Array.isArray(value) ? value : [value]).map((item) => item.trim()).filter(Boolean);
}

function single(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : undefined;
}

/** Неотрицательное десятичное число или ничего: мусор в цене игнорируется. */
function amount(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return /^\d+(\.\d{1,2})?$/.test(value) ? value : undefined;
}

export function parseCatalogParams(
  params: CatalogSearchParams,
  overrides: Partial<CatalogFilters> = {},
): CatalogFilters {
  const sort = single(params.sort);
  const availability = single(params.availability);
  const page = Number.parseInt(single(params.page) ?? '1', 10);
  const perPage = Number.parseInt(single(params.per_page) ?? '', 10);
  // Дубли и мусор отбрасываются: backend вернул бы на них 422.
  const attrs = [...new Set(many(params.attr).filter((item) => ATTR_PATTERN.test(item)))];

  return {
    category: single(params.category),
    search: single(params.search),
    availability: AVAILABILITIES.find((item) => item === availability),
    minPrice: amount(single(params.min_price)),
    maxPrice: amount(single(params.max_price)),
    attrs: attrs.slice(0, MAX_ATTRS),
    sort: SORTS.find((item) => item === sort) ?? 'relevance',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    view: single(params.view) === 'table' ? 'table' : 'grid',
    perPage: PER_PAGE_OPTIONS.find((item) => item === perPage),
    ...overrides,
  };
}

/** Размер страницы: выбранный или по умолчанию для вида выдачи. */
export function pageSizeOf(filters: Pick<CatalogFilters, 'view' | 'perPage'>): number {
  if (filters.perPage) return filters.perPage;
  return filters.view === 'grid' ? CATALOG_PAGE_SIZE : TABLE_PAGE_SIZE;
}

export function toProductQuery(filters: CatalogFilters): ProductQuery {
  return {
    category: filters.category,
    search: filters.search,
    availability: filters.availability,
    minPrice: filters.minPrice,
    maxPrice: filters.maxPrice,
    attrs: filters.attrs,
    sort: filters.sort,
    page: filters.page,
    pageSize: pageSizeOf(filters),
  };
}

/**
 * Обратное преобразование: фильтры → строка запроса.
 *
 * Значения по умолчанию в URL не пишутся — ссылка на первую страницу
 * каталога должна выглядеть как `/catalog`, а не как `/catalog?page=1&sort=relevance`.
 */
export function buildCatalogQuery(
  filters: Partial<CatalogFilters>,
  options: { keepCategory?: boolean } = {},
): string {
  const params = new URLSearchParams();
  if (options.keepCategory !== false && filters.category) {
    params.set('category', filters.category);
  }
  if (filters.search) params.set('search', filters.search);
  if (filters.availability) params.set('availability', filters.availability);
  if (filters.minPrice) params.set('min_price', filters.minPrice);
  if (filters.maxPrice) params.set('max_price', filters.maxPrice);
  for (const attr of filters.attrs ?? []) params.append('attr', attr);
  if (filters.sort && filters.sort !== 'relevance') params.set('sort', filters.sort);
  if (filters.view === 'table') params.set('view', 'table');
  if (filters.perPage) params.set('per_page', String(filters.perPage));
  if (filters.page && filters.page > 1) params.set('page', String(filters.page));

  const query = params.toString();
  return query ? `?${query}` : '';
}

export function catalogHref(
  filters: Partial<CatalogFilters>,
  options: { basePath?: string; keepCategory?: boolean } = {},
): string {
  const base = options.basePath ?? '/catalog';
  return `${base}${buildCatalogQuery(filters, { keepCategory: options.keepCategory })}`;
}

export type ActiveFilterChip = {
  key: string;
  label: string;
  /** Фильтры без этого значения — ссылка «снять». */
  next: Partial<CatalogFilters>;
};

/** Активные фильтры в виде снимаемых плашек. */
export function activeChips(
  filters: CatalogFilters,
  categoryName?: string,
  currencySign = '₸',
  /** Подписи характеристик: `код:slug` -> «Цвет: чёрный». */
  attrLabels: Record<string, string> = {},
): ActiveFilterChip[] {
  const chips: ActiveFilterChip[] = [];
  const base = { ...filters, page: 1 };

  if (filters.category && categoryName) {
    chips.push({
      key: 'category',
      label: categoryName,
      next: { ...base, category: undefined },
    });
  }
  if (filters.search) {
    chips.push({
      key: 'search',
      label: `«${filters.search}»`,
      next: { ...base, search: undefined },
    });
  }
  if (filters.availability) {
    chips.push({
      key: 'availability',
      label: AVAILABILITY_LABELS[filters.availability],
      next: { ...base, availability: undefined },
    });
  }
  if (filters.minPrice) {
    chips.push({
      key: 'min_price',
      label: `от ${filters.minPrice} ${currencySign}`,
      next: { ...base, minPrice: undefined },
    });
  }
  if (filters.maxPrice) {
    chips.push({
      key: 'max_price',
      label: `до ${filters.maxPrice} ${currencySign}`,
      next: { ...base, maxPrice: undefined },
    });
  }
  for (const attr of filters.attrs ?? []) {
    chips.push({
      key: `attr:${attr}`,
      label: attrLabels[attr] ?? attr,
      next: { ...base, attrs: (filters.attrs ?? []).filter((item) => item !== attr) },
    });
  }
  return chips;
}
