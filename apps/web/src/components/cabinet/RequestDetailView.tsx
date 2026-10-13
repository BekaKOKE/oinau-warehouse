/**
 * Карточка заявки клиента.
 *
 * Позиции — снимок на момент отправки: название и цена не меняются
 * задним числом, даже если товар потом переименовали. Комментарии —
 * только те, что менеджер отметил видимыми клиенту: backend не отдаёт
 * внутренние, и здесь выводится ровно поле `comments`, ничего больше.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import type { CustomerRequestDetail } from '@oinau/api-types';

import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { ApiError } from '@/lib/api/client';
import { fetchCustomerRequest } from '@/lib/api/customer';
import {
  describeCabinetError,
  describeRequestSource,
  describeRequestStatus,
  formatDate,
  formatDateTime,
  formatMoney,
  formatUnitPrice,
} from '@/lib/cabinet/format';
import { formatQuantity, unitLabel } from '@/lib/format';
import { StatusBadge } from './CabinetUi';
import styles from './Cabinet.module.css';

export function RequestDetailView({ number }: { number: string }) {
  const [request, setRequest] = useState<CustomerRequestDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchCustomerRequest(number)
      .then((result) => {
        if (!cancelled) setRequest(result);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof ApiError && (caught.status === 404 || caught.status === 422)) {
          setNotFound(true);
        } else {
          setError(describeCabinetError(caught));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [number, attempt]);

  const back = (
    <Link href="/cabinet/requests" className={styles.backLink}>
      ← Все заявки
    </Link>
  );

  if (notFound) {
    return (
      <>
        {back}
        <EmptyState
          title="Заявка не найдена"
          text="Проверьте номер. В кабинете видны только заявки, отправленные из вашего аккаунта."
          action={<ButtonLink href="/cabinet/requests">К списку заявок</ButtonLink>}
        />
      </>
    );
  }

  if (error) {
    return (
      <>
        {back}
        <ErrorState
          title="Не удалось загрузить заявку"
          text={error}
          action={<Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>}
        />
      </>
    );
  }

  if (!request) {
    return (
      <>
        {back}
        <div className={styles.rowsSkeleton} aria-busy="true" aria-label="Загрузка заявки">
          <Skeleton height="40px" width="50%" />
          <Skeleton height="96px" />
          <Skeleton height="260px" />
        </div>
      </>
    );
  }

  const status = describeRequestStatus(request.status);
  const source = describeRequestSource(request.source);

  return (
    <>
      {back}
      <header className={styles.pageHead}>
        <div className={styles.pageHeadText}>
          <p className={styles.eyebrow}>{source ? `Заявка · ${source}` : 'Заявка'}</p>
          <h1 className={`${styles.pageTitle} ${styles.mono}`}>{request.number}</h1>
          <p className={styles.pageLead}>
            Отправлена {formatDate(request.created_at)}
            {request.updated_at !== request.created_at
              ? ` · обновлена ${formatDate(request.updated_at)}`
              : ''}
          </p>
        </div>
        <div className={styles.pageActions}>
          <StatusBadge label={status.label} tone={status.tone} />
        </div>
      </header>

      <div className={styles.summaryStrip}>
        <div>
          <span className={styles.statLabel}>Сумма</span>
          <span className={styles.summaryValue}>
            {formatMoney(request.total_estimate, request.currency)}
          </span>
        </div>
        <div>
          <span className={styles.statLabel}>Позиций</span>
          <span className={styles.summaryValue}>{request.items_count}</span>
        </div>
        <div>
          <span className={styles.statLabel}>Проект</span>
          {request.project ? (
            <Link href={`/cabinet/projects/${request.project.uuid}`} className={styles.summaryLink}>
              {request.project.name}
            </Link>
          ) : (
            <span className={styles.summaryValueMuted}>Без проекта</span>
          )}
        </div>
      </div>

      <section className={styles.panel} aria-labelledby="request-items">
        <h2 id="request-items" className={styles.panelTitle}>
          Товары
        </h2>
        <div className={styles.tableScroll}>
          <table className={`${styles.table} ${styles.itemsTable}`}>
            <thead>
              <tr>
                <th scope="col">Товар</th>
                <th scope="col" className={styles.numeric}>
                  Количество
                </th>
                <th scope="col" className={styles.numeric}>
                  Цена
                </th>
                <th scope="col" className={styles.numeric}>
                  Сумма
                </th>
              </tr>
            </thead>
            <tbody>
              {request.items.map((item) => (
                <tr key={`${item.sku}:${item.color ?? ''}`}>
                  <td data-label="Товар">
                    <span className={styles.itemName}>{item.name}</span>
                    {item.color_name ? (
                      <span className={styles.rowSub}>Цвет: {item.color_name}</span>
                    ) : null}
                    <span className={`${styles.rowSub} ${styles.mono}`}>{item.sku}</span>
                  </td>
                  <td data-label="Количество" className={`${styles.numeric} ${styles.mono}`}>
                    {formatQuantity(item.quantity)} {unitLabel(item.unit)}
                  </td>
                  <td data-label="Цена" className={`${styles.numeric} ${styles.mono}`}>
                    {formatUnitPrice(item.unit_price, request.currency, item.pricing_type)}
                  </td>
                  <td data-label="Сумма" className={`${styles.numeric} ${styles.amount}`}>
                    {formatMoney(item.line_total, request.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={3}>
                  Итого
                </th>
                <td className={`${styles.numeric} ${styles.amount}`}>
                  {formatMoney(request.total_estimate, request.currency)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        <p className={styles.panelNote}>
          Сумма предварительная: окончательную цену и наличие подтверждает менеджер.
        </p>
      </section>

      <div className={styles.twoColumns}>
        <section className={styles.panel} aria-labelledby="request-comments">
          <h2 id="request-comments" className={styles.panelTitle}>
            Ответы менеджера
          </h2>
          {request.comments.length === 0 ? (
            <p className={styles.muted}>Пока ответов нет — менеджер свяжется с вами.</p>
          ) : (
            <ol className={styles.comments}>
              {request.comments.map((comment, index) => (
                <li key={`${comment.created_at}-${index}`} className={styles.comment}>
                  <p className={styles.commentMeta}>
                    OINAU PRO · {formatDateTime(comment.created_at)}
                  </p>
                  <p className={styles.commentBody}>{comment.body}</p>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className={styles.panel} aria-labelledby="request-history">
          <h2 id="request-history" className={styles.panelTitle}>
            История статусов
          </h2>
          {request.status_history.length === 0 ? (
            <p className={styles.muted}>Статус ещё не менялся.</p>
          ) : (
            <ol className={styles.timeline}>
              {request.status_history.map((step, index) => {
                const described = describeRequestStatus(step.status);
                return (
                  <li key={`${step.created_at}-${index}`}>
                    <span className={styles.timelineDot} aria-hidden="true" />
                    <span className={styles.timelineLabel}>{described.label}</span>
                    <span className={styles.muted}>{formatDateTime(step.created_at)}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      </div>

      <section className={styles.panel} aria-labelledby="request-contacts">
        <h2 id="request-contacts" className={styles.panelTitle}>
          Контакты в заявке
        </h2>
        <dl className={`${styles.details} ${styles.detailsGrid}`}>
          <div>
            <dt>Контактное лицо</dt>
            <dd>{request.customer_name}</dd>
          </div>
          <div>
            <dt>Телефон</dt>
            <dd>{request.phone}</dd>
          </div>
          {request.email ? (
            <div>
              <dt>Email</dt>
              <dd className={styles.breakAll}>{request.email}</dd>
            </div>
          ) : null}
          {request.company ? (
            <div>
              <dt>Компания</dt>
              <dd>{request.company}</dd>
            </div>
          ) : null}
          <div>
            <dt>Регион</dt>
            <dd>{request.region?.name ?? '—'}</dd>
          </div>
          {request.comment ? (
            <div className={styles.detailsWide}>
              <dt>Ваш комментарий</dt>
              <dd className={styles.preLine}>{request.comment}</dd>
            </div>
          ) : null}
        </dl>
      </section>
    </>
  );
}
