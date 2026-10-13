/**
 * Список заявок клиента с постраничной навигацией.
 *
 * На широком экране — таблица, на телефоне те же строки складываются
 * в карточки: горизонтальная прокрутка таблицы на 360 px неудобна.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import type { CustomerRequestPage } from '@oinau/api-types';

import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { CABINET_PAGE_SIZE, fetchCustomerRequests } from '@/lib/api/customer';
import {
  describeCabinetError,
  describeRequestSource,
  describeRequestStatus,
  formatMoney,
  formatShortDate,
} from '@/lib/cabinet/format';
import { formatCount } from '@/lib/format';
import { CabinetPagination, PageHead, RowsSkeleton, StatusBadge } from './CabinetUi';
import styles from './Cabinet.module.css';

export function RequestsList({ page }: { page: number }) {
  const [data, setData] = useState<CustomerRequestPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchCustomerRequests({ page, pageSize: CABINET_PAGE_SIZE })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describeCabinetError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [page, attempt]);

  return (
    <>
      <PageHead
        title="Заявки"
        lead="Заявки, отправленные из кабинета: статус, сумма и ответы менеджера."
        actions={
          <ButtonLink href="/catalog" variant="outline">
            Новая заявка
          </ButtonLink>
        }
      />

      {error ? (
        <ErrorState
          title="Не удалось загрузить заявки"
          text={error}
          action={<Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>}
        />
      ) : !data ? (
        <RowsSkeleton rows={5} />
      ) : data.items.length === 0 ? (
        <EmptyState
          title={page > 1 ? 'На этой странице заявок нет' : 'Заявок пока нет'}
          text="Добавьте товары в заявку из каталога и отправьте её, находясь в кабинете."
          action={
            page > 1 ? (
              <ButtonLink href="/cabinet/requests" variant="outline">
                К первой странице
              </ButtonLink>
            ) : (
              <ButtonLink href="/catalog">Перейти в каталог</ButtonLink>
            )
          }
        />
      ) : (
        <>
          <div className={styles.tablePanel}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Номер</th>
                  <th scope="col">Дата</th>
                  <th scope="col">Статус</th>
                  <th scope="col" className={styles.numeric}>
                    Позиций
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Сумма
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((request) => {
                  const status = describeRequestStatus(request.status);
                  const source = describeRequestSource(request.source);
                  const href = `/cabinet/requests/${encodeURIComponent(request.number)}`;
                  return (
                    <tr key={request.number}>
                      <td data-label="Номер">
                        <Link href={href} className={styles.rowLink}>
                          {request.number}
                        </Link>
                        {source || request.project ? (
                          <span className={styles.rowSub}>
                            {[source, request.project?.name].filter(Boolean).join(' · ')}
                          </span>
                        ) : null}
                      </td>
                      <td data-label="Дата">{formatShortDate(request.created_at)}</td>
                      <td data-label="Статус">
                        <StatusBadge label={status.label} tone={status.tone} />
                      </td>
                      <td data-label="Позиций" className={styles.numeric}>
                        {formatCount(request.items_count)}
                      </td>
                      <td data-label="Сумма" className={`${styles.numeric} ${styles.amount}`}>
                        {formatMoney(request.total_estimate, request.currency)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <CabinetPagination
            basePath="/cabinet/requests"
            page={data.page}
            pages={data.pages}
            total={data.total}
            shown={data.items.length}
          />
        </>
      )}
    </>
  );
}
