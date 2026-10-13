/**
 * Каталог: категории, товары, карточка, похожие позиции.
 *
 * Параметры повторяют контракт `/api/v1/public` один в один. Фильтров,
 * которых backend не поддерживает, здесь нет намеренно: витрина не
 * должна обещать то, чего сервер не умеет.
 */

import type {
  CategoryDetail,
  CategoryFacet,
  CategoryNode,
  ProductDetail,
  ProductListItem,
  ProductPage,
  ProductSort,
  PublicAvailability,
} from '@oinau/api-types';

import { apiRequest, apiRequestOrNull, type QueryValue } from '@/lib/api/client';
import { CATALOG_PAGE_SIZE } from '@/lib/config';

const CATALOG_TTL = 60;

export type ProductQuery = {
  category?: string;
  search?: string;
  availability?: PublicAvailability;
  minPrice?: string;
  maxPrice?: string;
  featured?: boolean;
  /** Фильтры по характеристикам: `код:slug`. */
  attrs?: string[];
  sort?: ProductSort;
  page?: number;
  pageSize?: number;
};

export async function fetchCategories(): Promise<CategoryNode[]> {
  return apiRequest<CategoryNode[]>('/api/v1/public/categories', {
    revalidate: CATALOG_TTL,
  });
}

export async function fetchCategory(slug: string): Promise<CategoryDetail | null> {
  return apiRequestOrNull<CategoryDetail>(`/api/v1/public/categories/${slug}`, {
    revalidate: CATALOG_TTL,
  });
}

export async function fetchProducts(query: ProductQuery = {}): Promise<ProductPage> {
  const params: Record<string, QueryValue> = {
    category: query.category,
    search: query.search,
    availability: query.availability,
    min_price: query.minPrice,
    max_price: query.maxPrice,
    featured: query.featured,
    attr: query.attrs && query.attrs.length > 0 ? query.attrs : undefined,
    sort: query.sort,
    page: query.page ?? 1,
    page_size: query.pageSize ?? CATALOG_PAGE_SIZE,
  };
  return apiRequest<ProductPage>('/api/v1/public/products', {
    query: params,
    revalidate: CATALOG_TTL,
  });
}

/** Фильтры раздела по характеристикам (цвет, материал, ...). */
export async function fetchCategoryFacets(slug: string): Promise<CategoryFacet[]> {
  const facets = await apiRequestOrNull<CategoryFacet[]>(
    `/api/v1/public/categories/${slug}/facets`,
    { revalidate: CATALOG_TTL },
  );
  return facets ?? [];
}

export async function fetchProduct(slug: string): Promise<ProductDetail | null> {
  return apiRequestOrNull<ProductDetail>(`/api/v1/public/products/${slug}`, {
    revalidate: CATALOG_TTL,
  });
}

export async function fetchRelatedProducts(slug: string): Promise<ProductListItem[]> {
  const related = await apiRequestOrNull<ProductListItem[]>(
    `/api/v1/public/products/${slug}/related`,
    { revalidate: CATALOG_TTL },
  );
  return related ?? [];
}

/** Плоский список категорий — для выпадающих списков и вкладок. */
export function flattenCategories(
  nodes: CategoryNode[],
  depth = 0,
): Array<CategoryNode & { level: number }> {
  return nodes.flatMap((node) => [
    { ...node, level: depth },
    ...flattenCategories(node.children ?? [], depth + 1),
  ]);
}

export function findCategory(nodes: CategoryNode[], slug: string): CategoryNode | undefined {
  return flattenCategories(nodes).find((node) => node.slug === slug);
}
