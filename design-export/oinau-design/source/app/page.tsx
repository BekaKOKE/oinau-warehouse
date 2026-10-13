/**
 * Главная страница.
 *
 * Серверный компонент: данные грузятся на сервере одним заходом,
 * в браузер уезжает только интерактив (шапка, метки, заявка).
 */

import type { Metadata } from 'next';

import { Hero } from '@/components/home/Hero';
import { CategoryGrid } from '@/components/home/CategoryGrid';
import {
  AboutBlock,
  Advantages,
  FeaturedProducts,
  PromoCards,
} from '@/components/home/HomeSections';
import { fetchCategories, fetchProducts, flattenCategories } from '@/lib/api/catalog';
import { fetchHomeContent } from '@/lib/api/content';
import { SITE_TAGLINE } from '@/lib/config';
import { resolveHotspots } from '@/lib/hotspots';
import { metadataFromSeo } from '@/lib/seo';

export async function generateMetadata(): Promise<Metadata> {
  const content = await fetchHomeContent();
  return metadataFromSeo(content?.seo, {
    title: `OINAU PRO — ${SITE_TAGLINE}`,
    description: SITE_TAGLINE,
    path: '/',
  });
}

export default async function HomePage() {
  // Четыре независимых запроса идут параллельно: последовательная
  // цепочка сложила бы их задержки.
  const [content, categories, featured, catalog] = await Promise.all([
    fetchHomeContent(),
    fetchCategories().catch(() => []),
    fetchProducts({ featured: true, pageSize: 8 }).catch(() => null),
    fetchProducts({ pageSize: 1 }).catch(() => null),
  ]);

  const hotspots = resolveHotspots(categories);
  const totalProducts = catalog?.total ?? 0;
  const categoriesCount = flattenCategories(categories).length;

  // Если избранных товаров нет, показываем первые позиции каталога:
  // пустой блок «чаще всего заказывают» выглядит как поломка.
  const featuredItems =
    featured && featured.items.length > 0
      ? featured.items.slice(0, 8)
      : ((await fetchProducts({ pageSize: 8 }).catch(() => null))?.items ?? []);

  return (
    <>
      <Hero
        content={content}
        hotspots={hotspots}
        totalProducts={totalProducts}
        categoriesCount={categoriesCount}
      />
      <CategoryGrid categories={categories} totalProducts={totalProducts} />
      <PromoCards />
      <FeaturedProducts products={featuredItems} />
      <Advantages content={content} />
      <AboutBlock content={content} />
    </>
  );
}
