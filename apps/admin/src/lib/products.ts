/**
 * Правила интерфейса раздела товаров: фильтры в адресе, подсказки
 * формата артикула и slug, раскладка дерева категорий.
 *
 * Проверки формата здесь — только подсказка до отправки. Решает backend:
 * его 422/409 всегда показываются у соответствующего поля.
 */

import type {
  CategoryTreeNode,
  ProductAdminSort,
  ProductListQuery,
  ProductStatus,
} from '@/lib/api/types';
import { PRODUCT_STATUS } from '@/lib/labels';

export const PRODUCT_PAGE_SIZE = 24;

export const PRODUCT_SORT_LABELS: Record<ProductAdminSort, string> = {
  updated: 'Недавно изменённые',
  newest: 'Сначала новые',
  name: 'По названию',
  sku: 'По артикулу',
};

// ------------------------------------------------------------- фильтры

/** Трёхзначный фильтр: не задан / да / нет. */
export type TriState = '' | 'true' | 'false';

export type ProductFilters = {
  search: string;
  status: ProductStatus | '';
  active: TriState;
  featured: TriState;
  categoryId: string;
  externalId: string;
  includeDeleted: boolean;
  sort: ProductAdminSort;
  page: number;
};

export const DEFAULT_PRODUCT_FILTERS: ProductFilters = {
  search: '',
  status: '',
  active: '',
  featured: '',
  categoryId: '',
  externalId: '',
  includeDeleted: false,
  sort: 'updated',
  page: 1,
};

function triState(value: string | null): TriState {
  return value === 'true' || value === 'false' ? value : '';
}

export function productFiltersFromParams(params: URLSearchParams): ProductFilters {
  const status = params.get('status') ?? '';
  const sort = params.get('sort') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  const categoryId = params.get('category_id') ?? '';
  return {
    search: (params.get('search') ?? '').slice(0, 100),
    status: status in PRODUCT_STATUS ? (status as ProductStatus) : '',
    active: triState(params.get('is_active')),
    featured: triState(params.get('is_featured')),
    categoryId: /^\d+$/.test(categoryId) ? categoryId : '',
    externalId: (params.get('external_id') ?? '').slice(0, 64),
    includeDeleted: params.get('include_deleted') === 'true',
    sort: sort in PRODUCT_SORT_LABELS ? (sort as ProductAdminSort) : DEFAULT_PRODUCT_FILTERS.sort,
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function productFiltersToSearch(filters: ProductFilters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.status) params.set('status', filters.status);
  if (filters.active) params.set('is_active', filters.active);
  if (filters.featured) params.set('is_featured', filters.featured);
  if (filters.categoryId) params.set('category_id', filters.categoryId);
  if (filters.externalId.trim()) params.set('external_id', filters.externalId.trim());
  if (filters.includeDeleted) params.set('include_deleted', 'true');
  if (filters.sort !== DEFAULT_PRODUCT_FILTERS.sort) params.set('sort', filters.sort);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function hasActiveProductFilters(filters: ProductFilters): boolean {
  return Boolean(
    filters.search.trim() ||
    filters.status ||
    filters.active ||
    filters.featured ||
    filters.categoryId ||
    filters.externalId.trim() ||
    filters.includeDeleted,
  );
}

export function productFiltersToQuery(filters: ProductFilters): ProductListQuery {
  return {
    search: filters.search.trim() || undefined,
    status: filters.status || undefined,
    is_active: filters.active ? filters.active === 'true' : undefined,
    is_featured: filters.featured ? filters.featured === 'true' : undefined,
    category_id: filters.categoryId ? Number(filters.categoryId) : undefined,
    external_id: filters.externalId.trim() || undefined,
    include_deleted: filters.includeDeleted || undefined,
    sort: filters.sort,
    page: filters.page,
    page_size: PRODUCT_PAGE_SIZE,
  };
}

// ------------------------------------------------------- артикул и slug

/** Совпадает с SKU_PATTERN / SLUG_PATTERN в schemas_admin_products.py. */
const SKU_RE = /^[A-Za-z0-9._/-]+$/;
const SLUG_RE = /^[a-z0-9-]+$/;

export function skuError(value: string): string | null {
  if (!value.trim()) return 'Укажите артикул';
  if (value.length > 64) return 'Не длиннее 64 символов';
  if (!SKU_RE.test(value)) return 'Латиница, цифры и символы . _ / -';
  return null;
}

export function slugError(value: string): string | null {
  if (!value.trim()) return 'Укажите адрес страницы (slug)';
  if (value.length > 200) return 'Не длиннее 200 символов';
  if (!SLUG_RE.test(value)) return 'Строчная латиница, цифры и дефис';
  return null;
}

const TRANSLIT: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  е: 'e',
  ё: 'e',
  ж: 'zh',
  з: 'z',
  и: 'i',
  й: 'y',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'h',
  ц: 'ts',
  ч: 'ch',
  ш: 'sh',
  щ: 'sch',
  ъ: '',
  ы: 'y',
  ь: '',
  э: 'e',
  ю: 'yu',
  я: 'ya',
  ә: 'a',
  ғ: 'g',
  қ: 'k',
  ң: 'n',
  ө: 'o',
  ұ: 'u',
  ү: 'u',
  һ: 'h',
  і: 'i',
};

/**
 * Черновик slug из названия: по кнопке «Из названия», а у новой
 * категории — сам, пока slug не правили руками. Результат видно в поле
 * до сохранения. Уникальность проверяет backend (409).
 */
export function slugFromName(name: string): string {
  return name
    .toLowerCase()
    .split('')
    .map((char) => TRANSLIT[char] ?? char)
    .join('')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 200);
}

// ------------------------------------------------------------- категории

export type FlatCategory = {
  id: number;
  name: string;
  depth: number;
  isActive: boolean;
  /** «Комплектующие / Канаты» — для поиска и подписи выбранной категории. */
  path: string;
};

/** Дерево категорий → плоский список в порядке обхода (родитель перед детьми). */
export function flattenCategoryTree(
  nodes: readonly CategoryTreeNode[],
  parents: string[] = [],
): FlatCategory[] {
  const result: FlatCategory[] = [];
  for (const node of nodes) {
    const trail = [...parents, node.name];
    result.push({
      id: node.id,
      name: node.name,
      depth: node.depth,
      isActive: node.is_active,
      path: trail.join(' / '),
    });
    result.push(...flattenCategoryTree(node.children ?? [], trail));
  }
  return result;
}

/** Опции селекта с отступом по глубине. */
export function categoryOptions(flat: readonly FlatCategory[]): { value: string; label: string }[] {
  return flat.map((item) => ({
    value: String(item.id),
    label: `${'  '.repeat(item.depth)}${item.name}${item.isActive ? '' : ' (скрыта)'}`,
  }));
}

/** Публичная страница товара на витрине. */
export function productSiteUrl(siteUrl: string, slug: string): string {
  return `${siteUrl.replace(/\/$/, '')}/product/${encodeURIComponent(slug)}`;
}
