import type { Metadata } from 'next';

import { CatalogView } from '@/components/catalog/CatalogView';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { fetchCategories, fetchProducts } from '@/lib/api/catalog';
import { parseCatalogParams, type CatalogSearchParams } from '@/lib/catalog-params';
import { buildMetadata } from '@/lib/seo';

type PageProps = { searchParams: Promise<CatalogSearchParams> };

export async function generateMetadata({ searchParams }: PageProps): Promise<Metadata> {
  const filters = parseCatalogParams(await searchParams);
  const searching = Boolean(filters.search);

  return buildMetadata({
    title: searching ? `Поиск: ${filters.search}` : 'Каталог комплектующих',
    description:
      'Канаты, крепления, сиденья качелей, втулки, горки и метизы для детских ' +
      'и спортивных площадок. Наличие, цены и минимальные партии.',
    path: '/catalog',
    // Страницы поиска и постраничная выдача в индексе не нужны:
    // они плодят дубли одной и той же выдачи.
    noindex: searching || filters.page > 1 || Boolean(filters.availability),
  });
}

export default async function CatalogPage({ searchParams }: PageProps) {
  const filters = parseCatalogParams(await searchParams);
  const [categories, catalog] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchProducts({ pageSize: 1 }).catch(() => null),
  ]);

  return (
    <CatalogView
      filters={filters}
      categories={categories}
      title="Каталог комплектующих"
      description="Надёжные решения для детских и спортивных площадок. Наличие и цены обновляются из складского учёта."
      totalProducts={catalog?.total ?? 0}
      breadcrumbs={<Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Каталог' }]} />}
    />
  );
}
