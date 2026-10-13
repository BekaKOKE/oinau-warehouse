'use client';

/**
 * Список товаров.
 *
 * Фильтрация, сортировка и страницы — на backend: каталог не выгружается
 * в браузер. Цена, обложка и наличие приходят в строке списка
 * (GET /admin/products) одним запросом на страницу.
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Checkbox, Field, Input, Select } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { categoriesApi, productsApi } from '@/lib/api/endpoints';
import type { ProductAdminSort, ProductListRow, ProductStatus } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { formatCount, formatRelative, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';
import { AVAILABILITY, enumOptions, PRODUCT_STATUS } from '@/lib/labels';
import { listPrice } from '@/lib/pricing';
import {
  categoryOptions,
  DEFAULT_PRODUCT_FILTERS,
  flattenCategoryTree,
  hasActiveProductFilters,
  PRODUCT_PAGE_SIZE,
  PRODUCT_SORT_LABELS,
  productFiltersFromParams,
  productFiltersToQuery,
  productFiltersToSearch,
  type TriState,
} from '@/lib/products';

import { ProductThumb } from './ProductThumb';
import styles from './Products.module.css';

const STATUS_OPTIONS = enumOptions(PRODUCT_STATUS);
const SORT_OPTIONS = (Object.keys(PRODUCT_SORT_LABELS) as ProductAdminSort[]).map((value) => ({
  value,
  label: PRODUCT_SORT_LABELS[value],
}));
const ACTIVE_OPTIONS = [
  { value: 'true', label: 'Активные' },
  { value: 'false', label: 'Неактивные' },
];
const FEATURED_OPTIONS = [
  { value: 'true', label: 'Избранные' },
  { value: 'false', label: 'Не избранные' },
];

function Flags({ row }: { row: ProductListRow }) {
  return (
    <div className={styles.flags}>
      {row.deleted_at ? (
        <Badge tone="danger">Удалён</Badge>
      ) : row.is_active ? (
        <Badge tone="success">Активен</Badge>
      ) : (
        <Badge tone="neutral">Неактивен</Badge>
      )}
      {row.is_featured ? <Badge tone="accent">Избранный</Badge> : null}
    </div>
  );
}

function Price({ row }: { row: ProductListRow }) {
  const label = listPrice(row.pricing_type, row.min_price, row.currency);
  const missing = row.pricing_type !== 'ON_REQUEST' && !row.min_price;
  return <span className={missing ? styles.warnText : 'num'}>{label}</span>;
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function ProductsList() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <ProductsPanel />
    </RequirePermission>
  );
}

function ProductsPanel() {
  const router = useRouter();
  const { can } = useSession();
  const canWrite = can(Permission.CATALOG_WRITE);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const { filters, apply, searchInput, setSearchInput } = useUrlFilters({
    parse: productFiltersFromParams,
    serialize: productFiltersToSearch,
  });

  const query = useMemo(() => productFiltersToQuery(filters), [filters]);
  const products = useQuery(
    (signal) => productsApi.list(query, { signal }),
    [JSON.stringify(query)],
  );
  const tree = useQuery((signal) => categoriesApi.tree({ signal }), []);
  const categories = useMemo(
    () => categoryOptions(flattenCategoryTree(tree.data ?? [])),
    [tree.data],
  );

  const columns: Column<ProductListRow>[] = [
    {
      key: 'image',
      header: <span className="visually-hidden">Фото</span>,
      width: '56px',
      cell: (row) => <ProductThumb url={row.main_image_url} count={row.images_count} />,
    },
    {
      key: 'name',
      header: 'Товар',
      cell: (row) => (
        <div className={styles.stack}>
          <Link href={`/products/${row.id}`} className={styles.name}>
            {row.name}
          </Link>
          <span className={styles.muted}>
            <span className="mono">{row.sku}</span>
            {row.external_id ? (
              <>
                {' '}
                · 1С: <span className="mono">{row.external_id}</span>
              </>
            ) : null}
          </span>
        </div>
      ),
    },
    {
      key: 'category',
      header: 'Категория',
      hideOnMobile: true,
      cell: (row) =>
        row.primary_category ? (
          <span>
            {row.primary_category.name}
            {row.categories_count > 1 ? (
              <span className={styles.muted}> +{row.categories_count - 1}</span>
            ) : null}
          </span>
        ) : (
          <span className={styles.warnText}>Без категории</span>
        ),
    },
    { key: 'price', header: 'Цена', align: 'right', cell: (row) => <Price row={row} /> },
    {
      key: 'availability',
      header: 'Наличие',
      hideOnMobile: true,
      cell: (row) => (
        <span title={row.stock_display_override ? 'Задано вручную' : 'По остаткам'}>
          <EnumBadge value={row.public_availability} meta={AVAILABILITY} />
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (row) => (
        <div className={styles.stack}>
          <EnumBadge value={row.status} meta={PRODUCT_STATUS} />
          <Flags row={row} />
        </div>
      ),
    },
    {
      key: 'updated',
      header: 'Изменён',
      hideOnMobile: true,
      cell: (row) => (
        <span className={`${styles.muted} ${styles.nowrap}`}>{formatRelative(row.updated_at)}</span>
      ),
    },
  ];

  const data = products.data;
  const active = hasActiveProductFilters(filters);

  return (
    <>
      <PageHeader
        title="Товары"
        description={
          data
            ? `${formatCount(data.total)} ${plural(data.total, ['товар', 'товара', 'товаров'])}${active ? ' по фильтру' : ''}`
            : 'Карточки каталога, цены, изображения и наличие'
        }
        actions={
          canWrite ? (
            <ButtonLink href="/products/new" variant="primary" icon="plus">
              Новый товар
            </ButtonLink>
          ) : null
        }
      />

      <Card flush>
        <form
          className={`${styles.filters} ${filtersOpen ? styles.filtersOpen : ''}`}
          role="search"
          onSubmit={(event) => event.preventDefault()}
        >
          <Field label="Поиск" className={styles.searchField}>
            <Input
              type="search"
              placeholder="Название, артикул или slug"
              maxLength={100}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </Field>
          <Field label="Статус" className={styles.extra}>
            <Select
              options={STATUS_OPTIONS}
              placeholder="Все статусы"
              value={filters.status}
              onChange={(event) => apply({ status: event.target.value as ProductStatus | '' })}
            />
          </Field>
          <Field label="Активность" className={styles.extra}>
            <Select
              options={ACTIVE_OPTIONS}
              placeholder="Все"
              value={filters.active}
              onChange={(event) => apply({ active: event.target.value as TriState })}
            />
          </Field>
          <Field label="Избранные" className={styles.extra}>
            <Select
              options={FEATURED_OPTIONS}
              placeholder="Все"
              value={filters.featured}
              onChange={(event) => apply({ featured: event.target.value as TriState })}
            />
          </Field>
          <Field label="Категория" className={styles.extra}>
            <Select
              options={categories}
              placeholder="Все категории"
              value={filters.categoryId}
              onChange={(event) => apply({ categoryId: event.target.value })}
            />
          </Field>
          <Field label="Код 1С (external_id)" className={styles.extra}>
            <Input
              key={filters.externalId}
              maxLength={64}
              placeholder="Точно, Enter — найти"
              defaultValue={filters.externalId}
              // Точный фильтр: применяется по Enter или уходу из поля,
              // а не на каждый символ (частичный код ничего не найдёт).
              onBlur={(event) => {
                if (event.target.value.trim() !== filters.externalId) {
                  apply({ externalId: event.target.value.trim() });
                }
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  apply({ externalId: event.currentTarget.value.trim() });
                }
              }}
            />
          </Field>
          <Field label="Сортировка" className={styles.extra}>
            <Select
              options={SORT_OPTIONS}
              value={filters.sort}
              onChange={(event) => apply({ sort: event.target.value as ProductAdminSort })}
            />
          </Field>
          <div className={`${styles.checkCell} ${styles.extra}`}>
            <Checkbox
              label="Показать удалённые"
              checked={filters.includeDeleted}
              onChange={(event) => apply({ includeDeleted: event.target.checked })}
            />
          </div>
          <div className={styles.toggleCell}>
            <Button
              variant="secondary"
              icon="menu"
              aria-expanded={filtersOpen}
              onClick={() => setFiltersOpen((open) => !open)}
            >
              {filtersOpen ? 'Скрыть фильтры' : 'Фильтры'}
            </Button>
          </div>
          {active ? (
            <div className={styles.resetCell}>
              <Button
                variant="ghost"
                icon="close"
                onClick={() => {
                  setSearchInput('');
                  apply({ ...DEFAULT_PRODUCT_FILTERS, sort: filters.sort });
                }}
              >
                Сбросить
              </Button>
            </div>
          ) : null}
        </form>

        <DataTable
          caption="Товары"
          columns={columns}
          rows={data?.items}
          rowKey={(row) => row.id}
          loading={products.status === 'loading'}
          refreshing={products.isRefreshing}
          error={products.status === 'error' ? products.error : undefined}
          onRetry={products.reload}
          onRowClick={(row) => router.push(`/products/${row.id}`)}
          rowClassName={(row) => (row.deleted_at ? styles.deletedRow : undefined)}
          skeletonRows={8}
          empty={
            active ? (
              <EmptyState
                icon="search"
                title="Ничего не найдено"
                description="Измените условия поиска или сбросьте фильтры."
                compact
              />
            ) : (
              <EmptyState
                icon="products"
                title="Товаров пока нет"
                description={
                  canWrite ? 'Создайте первый товар или загрузите каталог из Excel.' : undefined
                }
                compact
                action={
                  canWrite ? (
                    <ButtonLink href="/products/new" variant="primary" icon="plus" size="sm">
                      Новый товар
                    </ButtonLink>
                  ) : null
                }
              />
            )
          }
          renderMobile={(row) => (
            <div className={styles.mobileCard}>
              <ProductThumb url={row.main_image_url} count={row.images_count} />
              <div className={styles.mobileBody}>
                <Link href={`/products/${row.id}`} className={styles.name}>
                  {row.name}
                </Link>
                <span className={`${styles.muted} mono`}>{row.sku}</span>
                <div className={styles.mobileMeta}>
                  <EnumBadge value={row.status} meta={PRODUCT_STATUS} />
                  <EnumBadge value={row.public_availability} meta={AVAILABILITY} />
                  <Flags row={row} />
                </div>
                <Price row={row} />
              </div>
            </div>
          )}
        />

        {data ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={PRODUCT_PAGE_SIZE}
            disabled={products.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>
    </>
  );
}
