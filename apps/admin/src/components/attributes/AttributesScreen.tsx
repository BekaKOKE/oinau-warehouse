'use client';

/**
 * Характеристики: таблица с поиском и страницами, карточка — в боковой
 * панели. Тип значения показывается бейджем и после создания не меняется.
 */

import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Field, Input, Select } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { attributesApi } from '@/lib/api/endpoints';
import type { AttributeRead } from '@/lib/api/types';
import { VALUE_TYPE_META } from '@/lib/attributeForm';
import { Permission } from '@/lib/auth/permissions';
import { formatCount, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';

import { AttributeDrawer } from './AttributeDrawer';
import styles from './Attributes.module.css';

const PAGE_SIZE = 24;

type Filters = { search: string; active: '' | 'true' | 'false'; page: number };

function parse(params: URLSearchParams): Filters {
  const active = params.get('is_active');
  const page = Number.parseInt(params.get('page') ?? '', 10);
  return {
    search: (params.get('search') ?? '').slice(0, 100),
    active: active === 'true' || active === 'false' ? active : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function serialize(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.active) params.set('is_active', filters.active);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

const ACTIVE_OPTIONS = [
  { value: 'true', label: 'Активные' },
  { value: 'false', label: 'Отключённые' },
];

export function TypeBadge({ attribute }: { attribute: Pick<AttributeRead, 'value_type'> }) {
  const tone =
    attribute.value_type === 'OPTION'
      ? 'accent'
      : attribute.value_type === 'NUMBER'
        ? 'info'
        : 'neutral';
  return <Badge tone={tone}>{VALUE_TYPE_META[attribute.value_type].label}</Badge>;
}

function CategoriesCell({ attribute }: { attribute: AttributeRead }) {
  const list = attribute.categories ?? [];
  if (list.length === 0) return <span className={styles.muted}>Не назначена</span>;
  const shown = list
    .slice(0, 2)
    .map((item) => item.name)
    .join(', ');
  return (
    <span title={list.map((item) => item.name).join(', ')}>
      {shown}
      {list.length > 2 ? <span className={styles.muted}> +{list.length - 2}</span> : null}
    </span>
  );
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function AttributesScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <AttributesPanel />
    </RequirePermission>
  );
}

function AttributesPanel() {
  const router = useRouter();
  const { can } = useSession();
  const canWrite = can(Permission.CATALOG_WRITE);
  const { filters, apply, searchInput, setSearchInput } = useUrlFilters({ parse, serialize });
  const [open, setOpen] = useState<AttributeRead | 'new' | null>(null);

  const query = useMemo(
    () => ({
      search: filters.search.trim() || undefined,
      is_active: filters.active ? filters.active === 'true' : undefined,
      page: filters.page,
      page_size: PAGE_SIZE,
    }),
    [filters],
  );
  const list = useQuery((signal) => attributesApi.list(query, { signal }), [JSON.stringify(query)]);
  const active = Boolean(filters.search.trim() || filters.active);

  const columns: Column<AttributeRead>[] = [
    {
      key: 'name',
      header: 'Характеристика',
      cell: (row) => (
        <div className={styles.stack}>
          <button type="button" className={styles.nameButton} onClick={() => setOpen(row)}>
            {row.unit ? `${row.name}, ${row.unit}` : row.name}
          </button>
          <span className={`mono ${styles.muted}`}>{row.code}</span>
        </div>
      ),
    },
    { key: 'type', header: 'Тип', cell: (row) => <TypeBadge attribute={row} /> },
    {
      key: 'options',
      header: 'Варианты',
      align: 'right',
      hideOnMobile: true,
      cell: (row) =>
        row.value_type === 'OPTION' ? (
          <span className="num">{formatCount(row.options?.length ?? 0)}</span>
        ) : (
          <span className={styles.muted}>—</span>
        ),
    },
    {
      key: 'categories',
      header: 'Категории',
      hideOnMobile: true,
      cell: (row) => <CategoriesCell attribute={row} />,
    },
    {
      key: 'usage',
      header: 'У товаров',
      align: 'right',
      hideOnMobile: true,
      cell: (row) => <span className="num">{formatCount(row.usage_count)}</span>,
    },
    {
      key: 'flags',
      header: 'Статус',
      cell: (row) => (
        <div className={styles.flags}>
          {row.is_active ? (
            <Badge tone="success">Активна</Badge>
          ) : (
            <Badge tone="neutral">Отключена</Badge>
          )}
          {row.is_filterable ? <Badge tone="info">Фильтр</Badge> : null}
          {!row.is_visible ? <Badge tone="warning">Скрыта на сайте</Badge> : null}
        </div>
      ),
    },
  ];

  const data = list.data;

  return (
    <>
      <PageHeader
        title="Характеристики"
        description={
          data
            ? `${formatCount(data.total)} ${plural(data.total, ['характеристика', 'характеристики', 'характеристик'])}`
            : 'Параметры товаров и варианты значений'
        }
        actions={
          canWrite ? (
            <Button variant="primary" icon="plus" onClick={() => setOpen('new')}>
              Новая характеристика
            </Button>
          ) : null
        }
      />
      <Card flush>
        <form className={styles.filters} role="search" onSubmit={(event) => event.preventDefault()}>
          <Field label="Поиск" className={styles.search}>
            <Input
              type="search"
              placeholder="Название или код"
              maxLength={100}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </Field>
          <Field label="Статус">
            <Select
              options={ACTIVE_OPTIONS}
              placeholder="Все"
              value={filters.active}
              onChange={(event) => apply({ active: event.target.value as Filters['active'] })}
            />
          </Field>
        </form>
        <DataTable
          caption="Характеристики"
          columns={columns}
          rows={data?.items}
          rowKey={(row) => row.id}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={(row) => setOpen(row)}
          empty={
            active ? (
              <EmptyState icon="search" title="Ничего не найдено" compact />
            ) : (
              <EmptyState
                icon="attributes"
                title="Характеристик пока нет"
                description={
                  canWrite ? 'Создайте первую — например, «Диаметр» или «Материал».' : undefined
                }
                compact
              />
            )
          }
          renderMobile={(row) => (
            <div className={styles.mobileCard}>
              <div className={styles.mobileTop}>
                <span className={styles.strong}>
                  {row.unit ? `${row.name}, ${row.unit}` : row.name}
                </span>
                <TypeBadge attribute={row} />
              </div>
              <span className={`mono ${styles.muted}`}>{row.code}</span>
              <span className={styles.muted}>
                <CategoriesCell attribute={row} /> · у товаров: {formatCount(row.usage_count)}
                {row.value_type === 'OPTION' ? ` · вариантов: ${row.options?.length ?? 0}` : ''}
              </span>
            </div>
          )}
        />
        {data ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={PAGE_SIZE}
            disabled={list.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>

      {open !== null ? (
        <AttributeDrawer
          key={open === 'new' ? 'new' : open.id}
          attribute={open === 'new' ? null : open}
          canWrite={canWrite}
          onClose={() => setOpen(null)}
          onChanged={(saved) => {
            list.reload();
            if (saved) setOpen(saved);
          }}
          onDeleted={() => {
            setOpen(null);
            list.reload();
          }}
          onOpenCategory={(id) => router.push(`/categories?id=${id}`)}
        />
      ) : null}
    </>
  );
}
