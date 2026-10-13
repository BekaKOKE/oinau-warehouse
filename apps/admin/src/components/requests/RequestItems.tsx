'use client';

/**
 * Состав заявки — снапшот на момент отправки.
 *
 * Цена, название и единица берутся из позиции заявки, а не из текущего
 * каталога: товар могли переименовать, переоценить или удалить, а заявка
 * обязана показывать то, что видел клиент. Суммы не пересчитываются —
 * их посчитал backend при создании.
 */

import Link from 'next/link';

import { useSession } from '@/components/session/SessionProvider';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { EmptyState } from '@/components/ui/States';
import type { RequestDetail, RequestItem } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { formatMoney, formatQuantity } from '@/lib/decimal';
import { unitLabel } from '@/lib/format';
import { PRICING_TYPE } from '@/lib/labels';

import styles from './RequestDetail.module.css';

function UnitPrice({ item, currency }: { item: RequestItem; currency: string }) {
  if (item.unit_price === null || item.unit_price === undefined) {
    return <span className={styles.muted}>{PRICING_TYPE[item.pricing_type]}</span>;
  }
  return (
    <span className="num">
      {formatMoney(item.unit_price, currency)}
      <span className={styles.muted}> / {unitLabel(item.unit)}</span>
    </span>
  );
}

function LineTotal({ item, currency }: { item: RequestItem; currency: string }) {
  return item.line_total ? (
    <span className={`num ${styles.strong}`}>{formatMoney(item.line_total, currency)}</span>
  ) : (
    <span className={styles.muted}>—</span>
  );
}

/** Цвет позиции — снапшот из заявки; у позиции без цвета ничего не выводится. */
function Color({ item }: { item: RequestItem }) {
  if (!item.color_name) return null;
  return <span className={styles.color}>Цвет: {item.color_name}</span>;
}

export function RequestItems({ request }: { request: RequestDetail }) {
  const { can } = useSession();
  const canOpenProduct = can(Permission.CATALOG_READ);
  const items = request.items ?? [];

  const name = (item: RequestItem) =>
    item.product_id && canOpenProduct ? (
      <Link href={`/products/${item.product_id}`}>{item.name}</Link>
    ) : (
      <span>{item.name}</span>
    );

  const columns: Column<RequestItem>[] = [
    {
      key: 'product',
      header: 'Товар',
      cell: (item) => (
        <div className={styles.stack}>
          {name(item)}
          <span className={`mono ${styles.muted}`}>{item.sku}</span>
          <Color item={item} />
        </div>
      ),
    },
    {
      key: 'quantity',
      header: 'Количество',
      align: 'right',
      cell: (item) => (
        <span className="num">
          {formatQuantity(item.quantity)} {unitLabel(item.unit)}
        </span>
      ),
    },
    {
      key: 'price',
      header: 'Цена',
      align: 'right',
      cell: (item) => <UnitPrice item={item} currency={request.currency} />,
    },
    {
      key: 'total',
      header: 'Сумма',
      align: 'right',
      cell: (item) => <LineTotal item={item} currency={request.currency} />,
    },
  ];

  const withoutPrice = items.filter((item) => !item.line_total).length;

  return (
    <>
      <DataTable
        caption="Позиции заявки"
        columns={columns}
        rows={items}
        rowKey={(item) => item.id}
        empty={
          <EmptyState
            icon="requests"
            title="Позиций нет"
            description="Это общий запрос: клиент описал задачу в комментарии."
            compact
          />
        }
        renderMobile={(item) => (
          <>
            <div className={styles.stack}>
              {name(item)}
              <span className={`mono ${styles.muted}`}>{item.sku}</span>
              <Color item={item} />
            </div>
            <div className={styles.mobileRow}>
              <span className="num">
                {formatQuantity(item.quantity)} {unitLabel(item.unit)} ×{' '}
                <UnitPrice item={item} currency={request.currency} />
              </span>
              <LineTotal item={item} currency={request.currency} />
            </div>
          </>
        )}
      />
      {items.length > 0 ? (
        <div className={styles.totals}>
          <div className={styles.totalRow}>
            <span>Итого по заявке</span>
            <span className={`num ${styles.totalValue}`}>
              {request.total_estimate ? formatMoney(request.total_estimate, request.currency) : '—'}
            </span>
          </div>
          {withoutPrice > 0 ? (
            <p className={styles.muted}>
              {withoutPrice === items.length
                ? 'Цены всех позиций — по запросу: сумму назначает менеджер.'
                : `Без учёта позиций с ценой по запросу (${withoutPrice}).`}
            </p>
          ) : null}
          <p className={styles.muted}>
            Цены зафиксированы на момент отправки заявки и не меняются вместе с каталогом.
          </p>
        </div>
      ) : null}
    </>
  );
}
