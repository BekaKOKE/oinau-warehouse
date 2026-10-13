/**
 * Экран каталога — общий для `/catalog` и `/catalog/[category]`.
 *
 * Как в макете: слева панель «Подбор» (разделы, наличие, цена), справа
 * панель сортировки, сетка товаров и страницы. Серверный компонент:
 * выдача рендерится на сервере, поэтому ссылка с фильтрами открывается
 * сразу нужной страницей и индексируется. Клиентскими остаются только
 * элементы управления.
 */

import { ApiError, describeError } from '@/lib/api/client';
import { fetchProducts } from '@/lib/api/catalog';
import Link from 'next/link';

import type { CategoryFacet, CategoryNode } from '@oinau/api-types';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { catalogHref, toProductQuery, type CatalogFilters } from '@/lib/catalog-params';
import { formatCount, productCountLabel } from '@/lib/format';
import { CatalogFilters as FiltersPanel } from './CatalogFilters';
import { CatalogToolbar } from './CatalogToolbar';
import { CategoryTabs } from './CategoryTabs';
import { Pagination } from './Pagination';
import { ProductGrid } from './ProductGrid';
import { ProductTableLoader } from './ProductTableLoader';
import styles from './Catalog.module.css';

export async function CatalogView({
  filters,
  categories,
  title,
  description,
  activeSlug,
  basePath = '/catalog',
  totalProducts,
  breadcrumbs,
  facets = [],
  subcategories = [],
}: {
  filters: CatalogFilters;
  categories: CategoryNode[];
  title: string;
  description?: string | null;
  activeSlug?: string;
  basePath?: string;
  totalProducts: number;
  breadcrumbs?: React.ReactNode;
  /** Фильтры раздела по характеристикам. */
  facets?: CategoryFacet[];
  /** Подразделы — строкой над таблицей товаров. */
  subcategories?: CategoryNode[];
}) {
  const lockCategory = Boolean(activeSlug);

  const query = toProductQuery(filters);
  let page: Awaited<ReturnType<typeof fetchProducts>> | null = null;
  let error: string | null = null;
  try {
    page = await fetchProducts(query);
  } catch (caught) {
    // 404 здесь означал бы несуществующий раздел — его ловит страница.
    error = caught instanceof ApiError ? caught.message : describeError(caught);
  }

  const categoryName = activeSlug
    ? undefined
    : categories
        .flatMap((node) => node.children ?? [])
        .find((node) => node.slug === filters.category)?.name;

  const quoteSubject = activeSlug ? `по разделу «${title}»` : 'по каталогу';
  const attrLabels = Object.fromEntries(
    facets.flatMap((facet) =>
      (facet.options ?? []).map((option) => [
        `${facet.code}:${option.slug}`,
        `${facet.name}: ${option.name}`,
      ]),
    ),
  );

  return (
    <div className={`container ${styles.view}`}>
      {breadcrumbs}

      <header className={styles.head}>
        <h1 className={styles.title}>{title}</h1>
        {description || page ? (
          <p className={styles.subtitle}>
            {page ? <strong>{productCountLabel(page.total)}. </strong> : null}
            {description}
          </p>
        ) : null}
      </header>

      <div className={styles.layout}>
        <aside className={styles.sidebar} aria-label="Подбор товаров">
          <FiltersPanel
            filters={filters}
            basePath={basePath}
            lockCategory={lockCategory}
            facets={facets}
            categorySlot={
              <CategoryTabs
                categories={categories}
                activeSlug={activeSlug}
                totalProducts={totalProducts}
              />
            }
          />

          <div className={styles.help}>
            <p className={styles.helpTitle}>Не нашли позицию?</p>
            <p className={styles.helpText}>
              Пришлите спецификацию — подберём аналоги и рассчитаем стоимость.
            </p>
            <QuickOrderButton
              variant="dark"
              size="sm"
              block
              options={{
                mode: 'QUOTE',
                comment: `Прошу коммерческое предложение ${quoteSubject}.`,
              }}
            >
              Отправить спецификацию
            </QuickOrderButton>
          </div>
        </aside>

        <div className={styles.results}>
          {subcategories.length > 0 ? (
            <nav className={styles.subcategories} aria-label="Подразделы">
              {subcategories.map((child) => (
                <Link
                  key={child.slug}
                  href={`/catalog/${child.slug}`}
                  className={styles.subcategory}
                >
                  {child.name}
                  <span className={styles.subcategoryCount}>
                    {formatCount(child.product_count ?? 0)}
                  </span>
                </Link>
              ))}
            </nav>
          ) : null}

          <CatalogToolbar
            attrLabels={attrLabels}
            filters={filters}
            total={page?.total ?? 0}
            categoryName={categoryName}
            basePath={basePath}
            lockCategory={lockCategory}
            quoteAction={
              <QuickOrderButton
                variant="primaryOutline"
                size="sm"
                options={{
                  mode: 'QUOTE',
                  comment: `Прошу коммерческое предложение ${quoteSubject}.`,
                }}
              >
                {activeSlug ? 'Запросить КП на раздел' : 'Запросить КП'}
              </QuickOrderButton>
            }
          />

          {error ? (
            <ErrorState
              title="Не удалось загрузить каталог"
              text={error}
              action={
                <ButtonLink href={catalogHref(filters, { basePath, keepCategory: !lockCategory })}>
                  Повторить
                </ButtonLink>
              }
            />
          ) : !page || page.items.length === 0 ? (
            <EmptyState
              title="По вашему запросу ничего не найдено"
              text="Попробуйте изменить фильтры или поискать по артикулу. Если нужной позиции нет в каталоге — пришлите спецификацию, подберём аналог."
              action={
                <>
                  <ButtonLink href={basePath} variant="outline">
                    Сбросить фильтры
                  </ButtonLink>
                  <QuickOrderButton
                    options={{
                      mode: 'QUOTE',
                      comment: filters.search
                        ? `Не нашёл в каталоге: «${filters.search}».`
                        : undefined,
                    }}
                  >
                    Отправить спецификацию
                  </QuickOrderButton>
                </>
              }
            />
          ) : (
            <>
              {filters.view === 'grid' ? (
                <ProductGrid products={page.items} />
              ) : (
                <ProductTableLoader
                  // Новый набор фильтров — новая таблица, а не дописанная старая.
                  key={JSON.stringify(query)}
                  initialItems={page.items}
                  query={query}
                  page={page.page}
                  pages={page.pages}
                  total={page.total}
                />
              )}
              <Pagination
                filters={filters}
                page={page.page}
                pages={page.pages}
                total={page.total}
                shown={page.items.length}
                basePath={basePath}
                lockCategory={lockCategory}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
