/**
 * Главная страница.
 *
 * Серверный компонент: данные грузятся на сервере одним заходом,
 * в браузер уезжает только интерактив (шапка, метки, быстрый заказ).
 */

import type { Metadata } from 'next';

import type { CategoryNode } from '@oinau/api-types';

import { Hero, SOLUTIONS_ANCHOR } from '@/components/home/Hero';
import { CategoryGrid, type CategoryPreview } from '@/components/home/CategoryGrid';
import { AboutBlock, Advantages, FeaturedProducts } from '@/components/home/HomeSections';
import { SkuQuickBar } from '@/components/home/SkuQuickBar';
import { fetchCategories, fetchProducts } from '@/lib/api/catalog';
import { fetchHomeContent } from '@/lib/api/content';
import { SITE_TAGLINE } from '@/lib/config';
import { metadataFromSeo } from '@/lib/seo';

export async function generateMetadata(): Promise<Metadata> {
  const content = await fetchHomeContent();
  return metadataFromSeo(content?.seo, {
    title: `OINAU PRO — ${SITE_TAGLINE}`,
    description: SITE_TAGLINE,
    path: '/',
  });
}

/** Разделы, которые показывает сетка каталога (см. CategoryGrid). */
function gridCategories(categories: CategoryNode[]): CategoryNode[] {
  return categories.some((node) => (node.children ?? []).length > 0)
    ? categories.flatMap((node) => node.children ?? [])
    : categories;
}

/**
 * Обложка и «от N ₸» каждого раздела — из его самых дешёвых позиций.
 * Запросы параллельные и кешируются вместе с каталогом; упавший запрос
 * оставляет раздел без обложки, а не ломает главную.
 */
async function categoryPreviews(
  categories: CategoryNode[],
): Promise<Record<string, CategoryPreview>> {
  const entries = await Promise.all(
    categories.map(async (category) => {
      const page = await fetchProducts({
        category: category.slug,
        sort: 'price_asc',
        pageSize: 6,
      }).catch(() => null);
      if (!page || page.items.length === 0) return null;
      const priced = page.items.find((item) => item.price.price || item.price.from_price);
      const withImage = page.items.find((item) => item.image);
      const preview: CategoryPreview = {
        image: withImage?.image ?? null,
        fromPrice: priced ? (priced.price.from_price ?? priced.price.price ?? null) : null,
        currency: priced?.price.currency ?? 'KZT',
      };
      return [category.slug, preview] as const;
    }),
  );
  return Object.fromEntries(entries.filter((entry) => entry !== null));
}

export default async function HomePage() {
  // Независимые запросы идут параллельно: последовательная цепочка
  // сложила бы их задержки.
  const [content, categories, featured, catalog] = await Promise.all([
    fetchHomeContent(),
    fetchCategories().catch(() => []),
    fetchProducts({ featured: true, pageSize: 8 }).catch(() => null),
    fetchProducts({ pageSize: 1 }).catch(() => null),
  ]);

  const totalProducts = catalog?.total ?? 0;

  // Если избранных товаров нет, показываем первые позиции каталога:
  // пустой блок «часто заказывают» выглядит как поломка.
  const [featuredItems, previews] = await Promise.all([
    featured && featured.items.length > 0
      ? Promise.resolve(featured.items.slice(0, 8))
      : fetchProducts({ pageSize: 8 })
          .then((page) => page.items)
          .catch(() => []),
    categoryPreviews(gridCategories(categories)),
  ]);

  return (
    <>
      <Hero content={content} />
      <SkuQuickBar examples={featuredItems.map((item) => item.sku)} />
      <CategoryGrid
        categories={categories}
        previews={previews}
        totalProducts={totalProducts}
        anchorId={SOLUTIONS_ANCHOR}
      />
      <FeaturedProducts products={featuredItems} />
      <Advantages content={content} />
      <AboutBlock content={content} />
    </>
  );
}
