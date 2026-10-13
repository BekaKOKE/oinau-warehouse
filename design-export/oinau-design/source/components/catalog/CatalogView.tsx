/**
 * Экран каталога — общий для `/catalog` и `/catalog/[category]`.
 *
 * Серверный компонент: выдача рендерится на сервере, поэтому ссылка
 * с фильтрами открывается сразу нужной страницей и индексируется.
 * Клиентскими остаются только элементы управления.
 */

import { ApiError, describeError } from '@/lib/api/client';
import { fetchProducts } from '@/lib/api/catalog';
import type { CategoryNode } from '@oinau/api-types';

import { ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { SearchBar } from '@/components/layout/SearchBar';
import { catalogHref, toProductQuery, type CatalogFilters } from '@/lib/catalog-params';
import { CatalogFilters as FiltersPanel } from './CatalogFilters';
import { CatalogToolbar } from './CatalogToolbar';
import { CategoryTabs } from './CategoryTabs';
import { Pagination } from './Pagination';
import { ProductGrid } from './ProductGrid';
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
}: {
  filters: CatalogFilters;
  categories: CategoryNode[];
  title: string;
  description?: string | null;
  activeSlug?: string;
  basePath?: string;
  totalProducts: number;
  breadcrumbs?: React.ReactNode;
}) {
  const lockCategory = Boolean(activeSlug);

  let page: Awaited<ReturnType<typeof fetchProducts>> | null = null;
  let error: string | null = null;
  try {
    page = await fetchProducts(toProductQuery(filters));
  } catch (caught) {
    // 404 здесь означал бы несуществующий раздел — его ловит страница.
    error = caught instanceof ApiError ? caught.message : describeError(caught);
  }

  const categoryName = activeSlug
    ? undefined
    : categories
        .flatMap((node) => node.children ?? [])
        .find((node) => node.slug === filters.category)?.name;

  return (
    <>
      <div className={styles.head}>
        <div className={styles.headInner}>
          {breadcrumbs}
          <div className={styles.headRow}>
            <div>
              <h1 className={styles.title}>{title}</h1>
              {description ? <p className={styles.subtitle}>{description}</p> : null}
            </div>
            <SearchBar
              tone="light"
              className={styles.headSearch}
              defaultValue={filters.search ?? ''}
              placeholder="Артикул или название"
            />
          </div>
          <CategoryTabs
            categories={categories}
            activeSlug={activeSlug}
            totalProducts={totalProducts}
          />
        </div>
      </div>

      <div className={styles.layout}>
        <FiltersPanel filters={filters} basePath={basePath} lockCategory={lockCategory} />

        <div className={styles.results}>
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
            <>
              <CatalogToolbar
                filters={filters}
                total={0}
                categoryName={categoryName}
                basePath={basePath}
                lockCategory={lockCategory}
              />
              <EmptyState
                title="По вашему запросу ничего не найдено"
                text="Попробуйте изменить фильтры или поискать по артикулу. Если нужной позиции нет в каталоге — пришлите спецификацию, подберём аналог."
                action={
                  <>
                    <ButtonLink href={basePath} variant="outline">
                      Сбросить фильтры
                    </ButtonLink>
                    <ButtonLink href="/contacts">Отправить спецификацию</ButtonLink>
                  </>
                }
              />
            </>
          ) : (
            <>
              <CatalogToolbar
                filters={filters}
                total={page.total}
                categoryName={categoryName}
                basePath={basePath}
                lockCategory={lockCategory}
              />
              <ProductGrid products={page.items} />
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
    </>
  );
}
