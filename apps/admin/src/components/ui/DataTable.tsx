'use client';

/**
 * Таблица данных.
 *
 * Колонки описываются декларативно, состояние (загрузка, пусто, ошибка)
 * рисуется внутри таблицы, чтобы шапка и фильтры не прыгали при каждом
 * запросе. При обновлении прежние строки остаются на экране приглушёнными.
 */

import type { ReactNode } from 'react';

import { EmptyState, ErrorState, Skeleton } from './States';
import styles from './DataTable.module.css';

export type Column<Row> = {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  align?: 'left' | 'right' | 'center';
  width?: string;
  /** Скрывать колонку на узких экранах. */
  hideOnMobile?: boolean;
};

type DataTableProps<Row> = {
  columns: readonly Column<Row>[];
  rows: readonly Row[] | undefined;
  rowKey: (row: Row) => string | number;
  loading?: boolean;
  refreshing?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: ReactNode;
  onRowClick?: (row: Row) => void;
  rowClassName?: (row: Row) => string | undefined;
  skeletonRows?: number;
  caption?: string;
  /**
   * Карточка строки для узких экранов. Если задана, на ширине до 720px
   * вместо таблицы показывается список карточек — без горизонтальной
   * прокрутки. Скрытая копия исключена из дерева доступности (display: none).
   */
  renderMobile?: (row: Row) => ReactNode;
};

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  loading = false,
  refreshing = false,
  error,
  onRetry,
  empty,
  onRowClick,
  rowClassName,
  skeletonRows = 6,
  caption,
  renderMobile,
}: DataTableProps<Row>) {
  const cellClass = (column: Column<Row>) =>
    [styles[column.align ?? 'left'], column.hideOnMobile ? styles.hideOnMobile : '']
      .filter(Boolean)
      .join(' ');

  let body: ReactNode;
  if (error && !rows) {
    body = (
      <tr>
        <td colSpan={columns.length}>
          <ErrorState error={error} onRetry={onRetry} compact />
        </td>
      </tr>
    );
  } else if (loading && !rows) {
    body = Array.from({ length: skeletonRows }, (_, index) => (
      <tr key={`skeleton-${index}`} aria-hidden="true">
        {columns.map((column) => (
          <td key={column.key} className={cellClass(column)}>
            <Skeleton width={index % 2 ? '70%' : '85%'} />
          </td>
        ))}
      </tr>
    ));
  } else if (rows && rows.length === 0) {
    body = (
      <tr>
        <td colSpan={columns.length}>
          {empty ?? <EmptyState title="Ничего не найдено" compact />}
        </td>
      </tr>
    );
  } else {
    body = (rows ?? []).map((row) => (
      <tr
        key={rowKey(row)}
        className={[onRowClick ? styles.clickable : '', rowClassName?.(row)]
          .filter(Boolean)
          .join(' ')}
        onClick={
          onRowClick
            ? (event) => {
                // Клик по ссылке или кнопке внутри строки — их собственное действие.
                if ((event.target as HTMLElement).closest('a, button, input, select, label'))
                  return;
                onRowClick(row);
              }
            : undefined
        }
      >
        {columns.map((column) => (
          <td key={column.key} className={cellClass(column)}>
            {column.cell(row)}
          </td>
        ))}
      </tr>
    ));
  }

  const table = (
    <div className={`${styles.wrapper} ${renderMobile ? styles.desktopOnly : ''}`}>
      <table
        className={`${styles.table} ${refreshing && rows ? styles.refreshing : ''}`}
        aria-busy={loading || refreshing || undefined}
      >
        {caption ? <caption className="visually-hidden">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cellClass(column)}
                style={column.width ? { width: column.width } : undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );

  if (!renderMobile) return table;

  let mobile: ReactNode;
  if (error && !rows) {
    mobile = (
      <li>
        <ErrorState error={error} onRetry={onRetry} compact />
      </li>
    );
  } else if (loading && !rows) {
    mobile = Array.from({ length: Math.min(skeletonRows, 4) }, (_, index) => (
      <li key={`skeleton-${index}`} className={styles.mobileItem} aria-hidden="true">
        <Skeleton width="60%" />
        <Skeleton width="85%" />
      </li>
    ));
  } else if (rows && rows.length === 0) {
    mobile = <li>{empty ?? <EmptyState title="Ничего не найдено" compact />}</li>;
  } else {
    mobile = (rows ?? []).map((row) => (
      <li
        key={rowKey(row)}
        className={`${styles.mobileItem} ${onRowClick ? styles.clickable : ''}`}
        onClick={
          onRowClick
            ? (event) => {
                if ((event.target as HTMLElement).closest('a, button, input, select, label'))
                  return;
                onRowClick(row);
              }
            : undefined
        }
      >
        {renderMobile(row)}
      </li>
    ));
  }

  return (
    <>
      {table}
      <ul
        className={`${styles.mobileList} ${refreshing && rows ? styles.refreshing : ''}`}
        data-testid="mobile-list"
      >
        {mobile}
      </ul>
    </>
  );
}
