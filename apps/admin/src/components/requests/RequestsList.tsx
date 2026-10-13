'use client';

/**
 * Список заявок.
 *
 * Фильтры живут в адресной строке: ссылка с дашборда
 * (/requests?status=NEW) открывает готовую выборку, «назад» возвращает
 * к ней же, а ссылку можно переслать коллеге.
 */

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Field, Input, Select } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';
import { regionsApi, requestsApi } from '@/lib/api/endpoints';
import type {
  RequestAdminSort,
  RequestListItem,
  RequestSource,
  RequestStatus,
} from '@/lib/api/types';
import { formatMoney } from '@/lib/decimal';
import { formatCount, formatDateTime, formatRelative, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { enumOptions, REQUEST_SOURCE, REQUEST_SOURCE_TONE, REQUEST_STATUS } from '@/lib/labels';
import {
  dateRangeError,
  DEFAULT_FILTERS,
  filtersFromParams,
  filtersToQuery,
  filtersToSearch,
  hasActiveFilters,
  REQUEST_PAGE_SIZE,
  REQUEST_SORT_LABELS,
  type RequestFilters,
} from '@/lib/requests';

import styles from './Requests.module.css';

const SEARCH_DELAY_MS = 350;

const STATUS_OPTIONS = enumOptions(REQUEST_STATUS);
const SOURCE_OPTIONS = enumOptions(REQUEST_SOURCE);
const SORT_OPTIONS = (Object.keys(REQUEST_SORT_LABELS) as RequestAdminSort[]).map((value) => ({
  value,
  label: REQUEST_SORT_LABELS[value],
}));

function itemsLabel(row: RequestListItem): string {
  if (row.kind === 'GENERAL' && row.items_count === 0) {
    // Звонок и запрос КП — это не «пустая» заявка: подпись говорит, что это.
    return REQUEST_SOURCE_TONE[row.source] ? REQUEST_SOURCE[row.source] : 'Общий запрос';
  }
  return `${formatCount(row.items_count)} ${plural(row.items_count, ['позиция', 'позиции', 'позиций'])}`;
}

/** Метка быстрого заказа рядом с составом; у корзины сайта её нет. */
function SourceBadge({ row }: { row: RequestListItem }) {
  const tone = REQUEST_SOURCE_TONE[row.source];
  if (!tone || row.items_count === 0) return null;
  return <Badge tone={tone}>{REQUEST_SOURCE[row.source]}</Badge>;
}

function Amount({ row }: { row: RequestListItem }) {
  return row.total_estimate ? (
    <span className="num">{formatMoney(row.total_estimate, row.currency)}</span>
  ) : (
    <span className={styles.muted} title="В заявке нет позиций с ценой">
      —
    </span>
  );
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function RequestsList() {
  return (
    <RequirePermission all={[Permission.REQUEST_READ]}>
      <RequestsPanel />
    </RequirePermission>
  );
}

function RequestsPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const paramsString = searchParams.toString();

  const [filters, setFilters] = useState<RequestFilters>(() =>
    filtersFromParams(new URLSearchParams(paramsString)),
  );
  const [searchInput, setSearchInput] = useState(filters.search);
  // На телефоне фильтры кроме поиска свёрнуты, чтобы список был виден сразу.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const lastWritten = useRef(filtersToSearch(filters));

  // Адрес изменился снаружи (переход по ссылке, «назад») — принимаем его.
  useEffect(() => {
    const fromUrl = filtersFromParams(new URLSearchParams(paramsString));
    if (filtersToSearch(fromUrl) === lastWritten.current) return;
    lastWritten.current = filtersToSearch(fromUrl);
    setFilters(fromUrl);
    setSearchInput(fromUrl.search);
  }, [paramsString]);

  // Актуальные фильтры для отложенного поиска: таймер не должен
  // применять значения из рендера, который был до смены статуса.
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const apply = (patch: Partial<RequestFilters>) => {
    // Любая смена фильтра возвращает на первую страницу.
    const next = { ...filtersRef.current, page: 1, ...patch };
    const search = filtersToSearch(next);
    filtersRef.current = next;
    lastWritten.current = search;
    setFilters(next);
    router.replace(`${pathname}${search}`, { scroll: false });
  };

  useEffect(() => {
    if (searchInput.trim() === filters.search.trim()) return;
    const timer = window.setTimeout(() => apply({ search: searchInput }), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
    // apply стабилен по смыслу: пересоздаётся на рендер, но читает актуальное состояние.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput, filters.search]);

  const rangeError = dateRangeError(filters);
  const query = useMemo(() => filtersToQuery(filters), [filters]);
  const requests = useQuery(
    (signal) => requestsApi.list(query, { signal }),
    [JSON.stringify(query)],
    {
      enabled: !rangeError,
    },
  );
  const regions = useQuery((signal) => regionsApi.list({ signal }), []);

  const regionOptions = (regions.data ?? []).map((region) => ({
    value: String(region.id),
    label: region.name,
  }));

  const columns: Column<RequestListItem>[] = [
    {
      key: 'number',
      header: 'Заявка',
      width: '180px',
      cell: (row) => (
        <div className={styles.stack}>
          <Link href={`/requests/${row.id}`} className={`mono ${styles.number}`}>
            {row.number}
          </Link>
          <span className={styles.muted} title={formatDateTime(row.created_at)}>
            {formatRelative(row.created_at)}
          </span>
        </div>
      ),
    },
    {
      key: 'customer',
      header: 'Клиент',
      cell: (row) => (
        <div className={styles.stack}>
          <span className={styles.strong}>{row.customer_name}</span>
          {row.company ? <span className={styles.muted}>{row.company}</span> : null}
        </div>
      ),
    },
    {
      key: 'contacts',
      header: 'Контакты',
      hideOnMobile: true,
      cell: (row) => (
        <div className={styles.stack}>
          <span className="num">{row.phone}</span>
          {row.email ? <span className={styles.muted}>{row.email}</span> : null}
        </div>
      ),
    },
    {
      key: 'region',
      header: 'Регион',
      hideOnMobile: true,
      cell: (row) => row.region?.name ?? <span className={styles.muted}>—</span>,
    },
    {
      key: 'items',
      header: 'Состав',
      hideOnMobile: true,
      cell: (row) => (
        <div className={styles.stack}>
          <span className={styles.nowrap}>{itemsLabel(row)}</span>
          <SourceBadge row={row} />
        </div>
      ),
    },
    {
      key: 'total',
      header: 'Сумма',
      align: 'right',
      cell: (row) => <Amount row={row} />,
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (row) => <EnumBadge value={row.status} meta={REQUEST_STATUS} />,
    },
  ];

  const data = requests.data;
  const active = hasActiveFilters(filters);

  return (
    <>
      <PageHeader
        title="Заявки"
        description={
          data
            ? `${formatCount(data.total)} ${plural(data.total, ['заявка', 'заявки', 'заявок'])}${active ? ' по фильтру' : ''}`
            : 'Заявки клиентов с сайта и из личного кабинета'
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
              placeholder="Номер, имя, телефон, email, компания"
              value={searchInput}
              maxLength={100}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </Field>
          <Field className={styles.extra} label="Статус">
            <Select
              options={STATUS_OPTIONS}
              placeholder="Все статусы"
              value={filters.status}
              onChange={(event) => apply({ status: event.target.value as RequestStatus | '' })}
            />
          </Field>
          <Field className={styles.extra} label="Источник">
            <Select
              options={SOURCE_OPTIONS}
              placeholder="Все источники"
              value={filters.source}
              onChange={(event) => apply({ source: event.target.value as RequestSource | '' })}
            />
          </Field>
          <Field className={styles.extra} label="Регион">
            <Select
              options={regionOptions}
              placeholder="Все регионы"
              value={filters.regionId}
              onChange={(event) => apply({ regionId: event.target.value })}
            />
          </Field>
          <Field className={styles.extra} label="Создана с" error={rangeError ?? undefined}>
            <Input
              type="date"
              value={filters.dateFrom}
              onChange={(event) => apply({ dateFrom: event.target.value })}
            />
          </Field>
          <Field className={styles.extra} label="по">
            <Input
              type="date"
              value={filters.dateTo}
              onChange={(event) => apply({ dateTo: event.target.value })}
            />
          </Field>
          <Field className={styles.extra} label="Сортировка">
            <Select
              options={SORT_OPTIONS}
              value={filters.sort}
              onChange={(event) => apply({ sort: event.target.value as RequestAdminSort })}
            />
          </Field>
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
                  apply({ ...DEFAULT_FILTERS, sort: filters.sort });
                }}
              >
                Сбросить
              </Button>
            </div>
          ) : null}
        </form>

        <DataTable
          caption="Заявки"
          columns={columns}
          rows={rangeError ? [] : data?.items}
          rowKey={(row) => row.id}
          loading={requests.status === 'loading'}
          refreshing={requests.isRefreshing}
          error={requests.status === 'error' ? requests.error : undefined}
          onRetry={requests.reload}
          onRowClick={(row) => router.push(`/requests/${row.id}`)}
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
                icon="requests"
                title="Заявок пока нет"
                description="Новые заявки с сайта появятся здесь."
                compact
              />
            )
          }
          renderMobile={(row) => (
            <>
              <div className={styles.mobileTop}>
                <Link href={`/requests/${row.id}`} className={`mono ${styles.number}`}>
                  {row.number}
                </Link>
                <EnumBadge value={row.status} meta={REQUEST_STATUS} />
              </div>
              <div className={styles.stack}>
                <span className={styles.strong}>{row.customer_name}</span>
                {row.company ? <span className={styles.muted}>{row.company}</span> : null}
              </div>
              <div className={styles.mobileBottom}>
                <span className={styles.muted}>
                  {formatRelative(row.created_at)} · {itemsLabel(row)}
                </span>
                <Amount row={row} />
              </div>
            </>
          )}
        />

        {data && !rangeError ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={REQUEST_PAGE_SIZE}
            disabled={requests.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>
    </>
  );
}
