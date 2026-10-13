'use client';

/**
 * Остатки по товарам: одна строка — один товар, внутри — склады.
 *
 * Фильтры, сортировка и страницы считаются на backend (GET /admin/stock):
 * каталог целиком не выгружается. Итоги, свободный остаток и публичный
 * статус приходят готовыми — экран их не пересчитывает.
 */

import { useMemo, useState } from 'react';

import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Field, Input, Select } from '@/components/ui/Field';
import { Card } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { stockApi, warehousesApi } from '@/lib/api/endpoints';
import type {
  ProductStockListItem,
  PublicAvailability,
  StockEntry,
  StockListSort,
  StockSource,
} from '@/lib/api/types';
import { formatQuantity } from '@/lib/decimal';
import { formatCount, formatDateTime, plural, unitLabel } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';
import { AVAILABILITY, enumOptions } from '@/lib/labels';
import {
  availableTone,
  DEFAULT_STOCK_FILTERS,
  parseStockFilters,
  serializeStockFilters,
  STOCK_SORT,
  stockListQuery,
  SYNC_SOURCE,
  syncSourceMeta,
} from '@/lib/stock';

import { StockDrawer } from './StockDrawer';
import styles from './Stock.module.css';

const PAGE_SIZE = 24;

type Numbers = { quantity: string; reserved: string; available: string };

/** Цифры строки: по выбранному складу или итоги по активным складам. */
function numbersOf(row: ProductStockListItem, warehouseId: string): Numbers | null {
  if (!warehouseId) {
    return {
      quantity: row.total_quantity,
      reserved: row.total_reserved,
      available: row.total_available,
    };
  }
  const entry = (row.entries ?? []).find((item) => String(item.warehouse_id) === warehouseId);
  return entry
    ? { quantity: entry.quantity, reserved: entry.reserved, available: entry.available }
    : null;
}

function lastChange(row: ProductStockListItem): { label: string; value: string } | null {
  const synced = (row.entries ?? [])
    .map((entry) => entry.synced_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .pop();
  if (synced) return { label: 'Синхронизация', value: formatDateTime(synced) };
  if (row.stock_updated_at)
    return { label: 'Изменено', value: formatDateTime(row.stock_updated_at) };
  return null;
}

function Sources({ entries }: { entries: readonly StockEntry[] }) {
  const sources = [...new Set(entries.map((entry) => entry.sync_source).filter(Boolean))];
  if (sources.length === 0) return <span className={styles.muted}>Нет данных</span>;
  return (
    <span className={styles.inline}>
      {sources.map((source) => {
        const meta = syncSourceMeta(source);
        return (
          <Badge key={source} tone={meta.tone}>
            {meta.label}
          </Badge>
        );
      })}
    </span>
  );
}

function AvailablePill({ value, unit }: { value: string; unit: string }) {
  return (
    <span className={`${styles.availablePill} ${styles[`tone-${availableTone(value)}`]}`}>
      {formatQuantity(value)} {unitLabel(unit)}
    </span>
  );
}

function PublicStatus({ row }: { row: ProductStockListItem }) {
  return (
    <span className={styles.inline}>
      <EnumBadge value={row.public_availability} meta={AVAILABILITY} />
      {row.stock_display_override ? (
        <Badge tone="warning" title="Статус на сайте задан вручную и не зависит от остатков">
          Вручную
        </Badge>
      ) : null}
    </span>
  );
}

function WarehouseLines({ row, warehouseId }: { row: ProductStockListItem; warehouseId: string }) {
  const entries = row.entries ?? [];
  if (entries.length === 0) return <span className={styles.muted}>Складов нет</span>;
  return (
    <ul className={styles.warehouseList}>
      {entries.map((entry) => (
        <li
          key={entry.warehouse_id}
          className={`${styles.warehouseLine} ${
            String(entry.warehouse_id) === warehouseId ? styles.warehouseLineFocus : ''
          }`}
        >
          <span>{entry.warehouse_name}</span>
          <span className={styles.qty}>
            {formatQuantity(entry.available)} {unitLabel(row.unit)}
          </span>
          {entry.warehouse_is_active ? null : <Badge tone="warning">Отключён</Badge>}
        </li>
      ))}
    </ul>
  );
}

export function StockList() {
  const { filters, apply, searchInput, setSearchInput } = useUrlFilters({
    parse: parseStockFilters,
    serialize: serializeStockFilters,
  });
  const [open, setOpen] = useState<ProductStockListItem | null>(null);

  const query = useMemo(() => stockListQuery(filters, PAGE_SIZE), [filters]);
  const list = useQuery((signal) => stockApi.list(query, { signal }), [JSON.stringify(query)]);
  const warehouses = useQuery((signal) => warehousesApi.listAll({ signal }), []);

  const warehouseOptions = (warehouses.data ?? []).map((warehouse) => ({
    value: String(warehouse.id),
    label: warehouse.is_active ? warehouse.name : `${warehouse.name} (отключён)`,
  }));
  const selectedWarehouse = (warehouses.data ?? []).find(
    (warehouse) => String(warehouse.id) === filters.warehouseId,
  );
  const active = Boolean(
    filters.search.trim() || filters.warehouseId || filters.source || filters.availability,
  );

  const numbersCell = (row: ProductStockListItem, key: keyof Numbers) => {
    const numbers = numbersOf(row, filters.warehouseId);
    if (!numbers) return <span className={styles.muted}>—</span>;
    if (key === 'available') return <AvailablePill value={numbers.available} unit={row.unit} />;
    return (
      <span className={styles.qty}>
        {formatQuantity(numbers[key])} {unitLabel(row.unit)}
      </span>
    );
  };

  const columns: Column<ProductStockListItem>[] = [
    {
      key: 'product',
      header: 'Товар',
      cell: (row) => (
        <div className={styles.stack}>
          <button type="button" className={styles.nameButton} onClick={() => setOpen(row)}>
            {row.name ?? row.sku}
          </button>
          <span className={`mono ${styles.muted}`}>{row.sku}</span>
          {row.external_id ? (
            <span className={`mono ${styles.muted}`} title="Внешний код товара (1С)">
              1С: {row.external_id}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: 'category',
      header: 'Категория',
      hideOnMobile: true,
      cell: (row) =>
        row.primary_category ? (
          <span>{row.primary_category.name}</span>
        ) : (
          <span className={styles.muted}>Без категории</span>
        ),
    },
    {
      key: 'warehouses',
      header: 'Склады (свободно)',
      hideOnMobile: true,
      cell: (row) => <WarehouseLines row={row} warehouseId={filters.warehouseId} />,
    },
    {
      key: 'quantity',
      header: 'Остаток',
      align: 'right',
      cell: (row) => numbersCell(row, 'quantity'),
    },
    {
      key: 'reserved',
      header: 'Резерв',
      align: 'right',
      cell: (row) => numbersCell(row, 'reserved'),
    },
    {
      key: 'available',
      header: 'Свободно',
      align: 'right',
      cell: (row) => numbersCell(row, 'available'),
    },
    {
      key: 'source',
      header: 'Источник',
      hideOnMobile: true,
      cell: (row) => {
        const change = lastChange(row);
        return (
          <div className={styles.stack}>
            <Sources entries={row.entries ?? []} />
            {change ? (
              <span className={styles.muted}>
                {change.label}: {change.value}
              </span>
            ) : null}
          </div>
        );
      },
    },
    {
      key: 'public',
      header: 'На сайте',
      cell: (row) => <PublicStatus row={row} />,
    },
  ];

  const data = list.data;
  const scope = selectedWarehouse
    ? `Остаток, резерв и свободно — по складу «${selectedWarehouse.name}»${
        selectedWarehouse.is_active ? '' : ' (склад отключён и не входит в наличие)'
      }.`
    : 'Остаток, резерв и свободно — итог по активным складам.';

  return (
    <>
      <Card flush>
        <form className={styles.filters} role="search" onSubmit={(event) => event.preventDefault()}>
          <Field label="Поиск" className={styles.search}>
            <Input
              type="search"
              placeholder="Название, артикул или код 1С"
              maxLength={100}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </Field>
          <Field label="Склад">
            <Select
              options={warehouseOptions}
              placeholder="Все склады"
              value={filters.warehouseId}
              onChange={(event) => apply({ warehouseId: event.target.value })}
            />
          </Field>
          <Field label="Источник">
            <Select
              options={enumOptions(SYNC_SOURCE)}
              placeholder="Любой"
              value={filters.source}
              onChange={(event) => apply({ source: event.target.value as StockSource | '' })}
            />
          </Field>
          <Field label="Наличие на сайте">
            <Select
              options={enumOptions(AVAILABILITY)}
              placeholder="Любое"
              value={filters.availability}
              onChange={(event) =>
                apply({ availability: event.target.value as PublicAvailability | '' })
              }
            />
          </Field>
          <Field label="Сортировка">
            <Select
              options={enumOptions(STOCK_SORT)}
              value={filters.sort}
              onChange={(event) => apply({ sort: event.target.value as StockListSort })}
            />
          </Field>
        </form>
        <div className={styles.filtersFooter}>
          <span>
            {data
              ? `${formatCount(data.total)} ${plural(data.total, ['товар', 'товара', 'товаров'])}. `
              : null}
            {scope}
          </span>
          {active ? (
            <Button
              size="sm"
              variant="ghost"
              icon="close"
              onClick={() => {
                setSearchInput('');
                apply({ ...DEFAULT_STOCK_FILTERS, sort: filters.sort });
              }}
            >
              Сбросить фильтры
            </Button>
          ) : null}
        </div>
        <DataTable
          caption="Остатки"
          columns={columns}
          rows={data?.items}
          rowKey={(row) => row.product_id}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={(row) => setOpen(row)}
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
                icon="stock"
                title="Товаров пока нет"
                description="Остатки появятся, когда в каталоге будут товары."
                compact
              />
            )
          }
          renderMobile={(row) => {
            const numbers = numbersOf(row, filters.warehouseId);
            return (
              <div className={styles.mobileCard}>
                <div className={styles.mobileTop}>
                  <div className={styles.stack}>
                    <span className={styles.strong}>{row.name ?? row.sku}</span>
                    <span className={`mono ${styles.muted}`}>
                      {row.sku}
                      {row.primary_category ? ` · ${row.primary_category.name}` : ''}
                    </span>
                  </div>
                  <PublicStatus row={row} />
                </div>
                {numbers ? (
                  <dl className={styles.metrics}>
                    <div className={`${styles.metric} ${styles.metricSmall}`}>
                      <dt>Остаток</dt>
                      <dd>{formatQuantity(numbers.quantity)}</dd>
                    </div>
                    <div className={`${styles.metric} ${styles.metricSmall}`}>
                      <dt>Резерв</dt>
                      <dd>{formatQuantity(numbers.reserved)}</dd>
                    </div>
                    <div
                      className={`${styles.metric} ${styles.metricSmall} ${styles.metricAvailable} ${
                        styles[`tone-${availableTone(numbers.available)}`]
                      }`}
                    >
                      <dt>Свободно</dt>
                      <dd>
                        {formatQuantity(numbers.available)} {unitLabel(row.unit)}
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <span className={styles.muted}>На выбранном складе строки нет</span>
                )}
                <Sources entries={row.entries ?? []} />
              </div>
            );
          }}
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

      {open ? (
        <StockDrawer
          key={open.product_id}
          item={open}
          onClose={() => setOpen(null)}
          onChanged={list.reload}
        />
      ) : null}
    </>
  );
}
