/**
 * Карта сайта.
 *
 * Собирается из реальных данных каталога. Товары берутся страницами
 * по максимуму, который отдаёт API, — тянуть весь каталог одним
 * запросом публичный эндпоинт не позволяет и не должен.
 */

import type { MetadataRoute } from 'next';

import { fetchCategories, fetchProducts, flattenCategories } from '@/lib/api/catalog';
import { absoluteUrl } from '@/lib/seo';

// Предел обхода: карта сайта не должна превращаться в выгрузку каталога.
const MAX_PRODUCT_PAGES = 20;
const PAGE_SIZE = 60;

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticPages: MetadataRoute.Sitemap = [
    { url: absoluteUrl('/'), priority: 1 },
    { url: absoluteUrl('/catalog'), priority: 0.9 },
    { url: absoluteUrl('/services'), priority: 0.6 },
    { url: absoluteUrl('/delivery'), priority: 0.5 },
    { url: absoluteUrl('/faq'), priority: 0.5 },
    { url: absoluteUrl('/contacts'), priority: 0.5 },
  ];

  const categories = await fetchCategories().catch(() => []);
  const categoryPages: MetadataRoute.Sitemap = flattenCategories(categories).map((category) => ({
    url: absoluteUrl(`/catalog/${category.slug}`),
    priority: 0.8,
  }));

  const productPages: MetadataRoute.Sitemap = [];
  for (let page = 1; page <= MAX_PRODUCT_PAGES; page += 1) {
    const result = await fetchProducts({ page, pageSize: PAGE_SIZE }).catch(() => null);
    if (!result) break;
    for (const product of result.items) {
      productPages.push({ url: absoluteUrl(`/product/${product.slug}`), priority: 0.7 });
    }
    if (page >= result.pages) break;
  }

  return [...staticPages, ...categoryPages, ...productPages];
}
