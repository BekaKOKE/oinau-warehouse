/**
 * Уведомления: все или только непрочитанные, отметка по одному и все сразу.
 *
 * Счётчик в меню и шапке обновляется из ответа backend, а не пересчётом
 * на клиенте: у клиента может быть открыта только одна страница списка.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import type { CustomerNotification, NotificationPage } from '@oinau/api-types';

import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState } from '@/components/ui/States';
import {
  CABINET_PAGE_SIZE,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '@/lib/api/customer';
import { NOTIFICATION_TYPE, describeCabinetError, formatDateTime } from '@/lib/cabinet/format';
import { formatCount } from '@/lib/format';
import { CabinetPagination, PageHead, RowsSkeleton } from './CabinetUi';
import { useCustomerSession } from './CustomerSessionProvider';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

function requestNumber(notification: CustomerNotification): string | null {
  const value = notification.payload?.request_number;
  return typeof value === 'string' && value ? value : null;
}

export function NotificationsList({ page, unreadOnly }: { page: number; unreadOnly: boolean }) {
  const toast = useToast();
  const { unreadCount, setUnreadCount, refreshUnread } = useCustomerSession();
  const [data, setData] = useState<NotificationPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [markingAll, setMarkingAll] = useState(false);
  const [marking, setMarking] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchNotifications({ page, pageSize: CABINET_PAGE_SIZE, unread: unreadOnly })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describeCabinetError(caught));
      });
    void refreshUnread();
    return () => {
      cancelled = true;
    };
  }, [page, unreadOnly, attempt, refreshUnread]);

  async function handleMarkRead(notification: CustomerNotification) {
    setMarking(notification.uuid);
    try {
      const updated = await markNotificationRead(notification.uuid);
      setData((current) =>
        current
          ? {
              ...current,
              items: unreadOnly
                ? current.items.filter((item) => item.uuid !== updated.uuid)
                : current.items.map((item) => (item.uuid === updated.uuid ? updated : item)),
            }
          : current,
      );
      if (!notification.is_read) setUnreadCount(Math.max(unreadCount - 1, 0));
    } catch (caught) {
      toast.error(describeCabinetError(caught));
    } finally {
      setMarking(null);
    }
  }

  async function handleMarkAll() {
    setMarkingAll(true);
    try {
      const result = await markAllNotificationsRead();
      setUnreadCount(result.unread);
      toast.success('Все уведомления отмечены прочитанными');
      setAttempt((value) => value + 1);
    } catch (caught) {
      toast.error(describeCabinetError(caught));
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <>
      <PageHead
        title="Уведомления"
        lead={
          unreadCount > 0 ? `Непрочитанных: ${formatCount(unreadCount)}` : 'Новых уведомлений нет'
        }
        actions={
          <Button
            variant="outline"
            onClick={handleMarkAll}
            disabled={markingAll || unreadCount === 0}
            aria-busy={markingAll}
          >
            {markingAll ? 'Отмечаем…' : 'Отметить все прочитанными'}
          </Button>
        }
      />

      <div className={styles.segmented} role="group" aria-label="Фильтр уведомлений">
        <Link
          href="/cabinet/notifications"
          className={`${styles.segment} ${unreadOnly ? '' : styles.segmentActive}`}
          aria-current={unreadOnly ? undefined : 'page'}
        >
          Все
        </Link>
        <Link
          href="/cabinet/notifications?unread=1"
          className={`${styles.segment} ${unreadOnly ? styles.segmentActive : ''}`}
          aria-current={unreadOnly ? 'page' : undefined}
        >
          Непрочитанные
          {unreadCount > 0 ? (
            <span className={styles.segmentCount}>{formatCount(unreadCount)}</span>
          ) : null}
        </Link>
      </div>

      {error ? (
        <ErrorState
          title="Не удалось загрузить уведомления"
          text={error}
          action={<Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>}
        />
      ) : !data ? (
        <RowsSkeleton rows={4} height="88px" />
      ) : data.items.length === 0 ? (
        <EmptyState
          title={unreadOnly ? 'Непрочитанных уведомлений нет' : 'Уведомлений пока нет'}
          text="Здесь появятся изменения статусов заявок и ответы менеджера."
          action={
            unreadOnly ? (
              <ButtonLink href="/cabinet/notifications" variant="outline">
                Показать все
              </ButtonLink>
            ) : undefined
          }
        />
      ) : (
        <>
          <ul className={styles.notifications}>
            {data.items.map((notification) => {
              const number = requestNumber(notification);
              return (
                <li
                  key={notification.uuid}
                  className={`${styles.notification} ${
                    notification.is_read ? '' : styles.notificationUnread
                  }`}
                >
                  <span className={styles.notificationDot} aria-hidden="true" />
                  <div className={styles.notificationBody}>
                    <p className={styles.notificationMeta}>
                      <span>{NOTIFICATION_TYPE[notification.type] ?? 'Уведомление'}</span>
                      <span aria-hidden="true">·</span>
                      <time dateTime={notification.created_at}>
                        {formatDateTime(notification.created_at)}
                      </time>
                      {notification.is_read ? null : (
                        <span className="visuallyHidden">, не прочитано</span>
                      )}
                    </p>
                    <p className={styles.notificationTitle}>{notification.title}</p>
                    <p className={styles.notificationText}>{notification.message}</p>
                    {number ? (
                      <Link
                        href={`/cabinet/requests/${encodeURIComponent(number)}`}
                        className={styles.textLink}
                        onClick={() => {
                          if (!notification.is_read) void handleMarkRead(notification);
                        }}
                      >
                        Открыть заявку {number}
                      </Link>
                    ) : null}
                  </div>
                  {notification.is_read ? (
                    <span className={styles.notificationRead}>Прочитано</span>
                  ) : (
                    <Button
                      size="sm"
                      variant="secondary"
                      block={false}
                      onClick={() => handleMarkRead(notification)}
                      disabled={marking === notification.uuid}
                      aria-label={`Отметить прочитанным: ${notification.title}`}
                    >
                      Прочитано
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
          <CabinetPagination
            basePath="/cabinet/notifications"
            page={data.page}
            pages={data.pages}
            total={data.total}
            shown={data.items.length}
            extraQuery={{ unread: unreadOnly ? '1' : undefined }}
          />
        </>
      )}
    </>
  );
}
