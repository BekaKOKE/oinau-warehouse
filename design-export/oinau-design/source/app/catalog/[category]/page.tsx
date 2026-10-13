import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { CatalogView } from '@/components/catalog/CatalogView';
import { Breadcrumbs, type Crumb } from '@/components/ui/Breadcrumbs';
import { fetchCategories, fetchCategory, fetchProducts } from '@/lib/api/catalog';
import { parseCatalogParams, type CatalogSearchParams } from '@/lib/catalog-params';
import { buildMetadata } from '@/lib/seo';

type PageProps = {
  params: Promise<{ category: string }>;
  searchParams: Promise<CatalogSearchParams>;
};

export async function generateMetadata({ params, searchParams }: PageProps): Promise<Metadata> {
  const { category: slug } = await params;
  const [category, query] = await Promise.all([fetchCategory(slug), searchParams]);
  if (!category)
    return buildMetadata({ title: 'Раздел не найден', path: `/catalog/${slug}`, noindex: true });

  const filters = parseCatalogParams(query);
  return buildMetadata({
    // SEO-заголовок из CMS имеет приоритет; своего текста витрина
    // не сочиняет.
    title: category.seo_title ?? category.name,
    description: category.seo_description ?? category.description,
    path: `/catalog/${slug}`,
    noindex: filters.page > 1 || Boolean(filters.search) || Boolean(filters.availability),
  });
}

export default async function CategoryPage({ params, searchParams }: PageProps) {
  const { category: slug } = await params;
  const [category, categories, catalog, query] = await Promise.all([
    fetchCategory(slug),
    fetchCategories().catch(() => []),
    fetchProducts({ pageSize: 1 }).catch(() => null),
    searchParams,
  ]);

  if (!category) notFound();

  const filters = parseCatalogParams(query, { category: slug });
  const crumbs: Crumb[] = [
    { href: '/', label: 'Главная' },
    { href: '/catalog', label: 'Каталог' },
    ...(category.breadcrumbs ?? []).map((item) => ({
      href: `/catalog/${item.slug}`,
      label: item.name,
    })),
    { label: category.name },
  ];

  return (
    <CatalogView
      filters={filters}
      categories={categories}
      title={category.name}
      description={category.description}
      activeSlug={slug}
      basePath={`/catalog/${slug}`}
      totalProducts={catalog?.total ?? 0}
      breadcrumbs={<Breadcrumbs items={crumbs} />}
    />
  );
}
