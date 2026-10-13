/**
 * Главная кабинета: приветствие, сводка, последние заявки, профиль
 * и быстрые действия.
 *
 * Сводка собирается из тех же эндпоинтов, что и разделы: отдельного
 * «dashboard API» нет, и цифры не могут разойтись со списками.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import type { CustomerRequestPage, ProjectPage } from '@oinau/api-types';

import { useFavorites } from '@/components/favorites/FavoritesProvider';
import { ButtonLink } from '@/components/ui/Button';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { fetchCustomerRequests, fetchProjects } from '@/lib/api/customer';
import {
  describeCabinetError,
  describeRequestStatus,
  formatDate,
  formatMoney,
} from '@/lib/cabinet/format';
import { formatCount, plural } from '@/lib/format';
import { PageHead, StatusBadge } from './CabinetUi';
import { useCustomerSession } from './CustomerSessionProvider';
import styles from './Cabinet.module.css';

type Summary = { requests: CustomerRequestPage; projects: ProjectPage };

function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return 'Доброй ночи';
  if (hour < 12) return 'Доброе утро';
  if (hour < 18) return 'Добрый день';
  return 'Добрый вечер';
}

export function CabinetDashboard() {
  const { profile, unreadCount } = useCustomerSession();
  const { count: favoritesCount, ready: favoritesReady } = useFavorites();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [hello, setHello] = useState('Здравствуйте');

  useEffect(() => {
    // Время суток — только в браузере: иначе серверный и клиентский
    // рендер разошлись бы в часовом поясе.
    setHello(greeting());
  }, []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      fetchCustomerRequests({ page: 1, pageSize: 5 }),
      fetchProjects({ page: 1, pageSize: 1 }),
    ])
      .then(([requests, projects]) => {
        if (!cancelled) setSummary({ requests, projects });
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describeCabinetError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (!profile) return null;

  const stats = [
    {
      href: '/cabinet/requests',
      label: 'Заявки',
      value: summary ? formatCount(summary.requests.total) : null,
    },
    {
      href: '/cabinet/projects',
      label: 'Проекты',
      value: summary ? formatCount(summary.projects.total) : null,
    },
    {
      href: '/cabinet/favorites',
      label: 'Избранное',
      value: favoritesReady ? formatCount(favoritesCount) : null,
    },
    {
      href: '/cabinet/notifications',
      label: 'Непрочитанные',
      value: formatCount(unreadCount),
      accent: unreadCount > 0,
    },
  ];

  return (
    <>
      <PageHead
        eyebrow="Личный кабинет"
        title={`${hello}, ${profile.contact_name}`}
        lead={
          profile.company_name
            ? `${profile.company_name} · заявки, проекты и избранное в одном месте.`
            : 'Заявки, проекты и избранное в одном месте.'
        }
        actions={
          <ButtonLink href="/catalog" size="md">
            Перейти в каталог
          </ButtonLink>
        }
      />

      <div className={styles.stats}>
        {stats.map((stat) => (
          <Link
            key={stat.href}
            href={stat.href}
            className={`${styles.stat} ${stat.accent ? styles.statAccent : ''}`}
          >
            <span className={styles.statLabel}>{stat.label}</span>
            {stat.value === null ? (
              <Skeleton height="30px" width="48px" />
            ) : (
              <span className={styles.statValue}>{stat.value}</span>
            )}
          </Link>
        ))}
      </div>

      <div className={styles.dashboardGrid}>
        <section className={styles.panel} aria-labelledby="recent-requests">
          <div className={styles.panelHead}>
            <h2 id="recent-requests" className={styles.panelTitle}>
              Последние заявки
            </h2>
            <Link href="/cabinet/requests" className={styles.textLink}>
              Все заявки
            </Link>
          </div>

          {error ? (
            <ErrorState
              title="Не удалось загрузить заявки"
              text={error}
              action={
                <button
                  type="button"
                  className={styles.textButton}
                  onClick={() => setAttempt((value) => value + 1)}
                >
                  Повторить
                </button>
              }
            />
          ) : !summary ? (
            <div className={styles.rowsSkeleton}>
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} height="52px" />
              ))}
            </div>
          ) : summary.requests.items.length === 0 ? (
            <EmptyState
              title="Заявок пока нет"
              text="Соберите позиции в каталоге и отправьте заявку — она появится здесь."
              action={
                <ButtonLink href="/catalog" variant="outline">
                  Открыть каталог
                </ButtonLink>
              }
            />
          ) : (
            <ul className={styles.compactList}>
              {summary.requests.items.map((request) => {
                const status = describeRequestStatus(request.status);
                return (
                  <li key={request.number}>
                    <Link
                      href={`/cabinet/requests/${encodeURIComponent(request.number)}`}
                      className={styles.compactRow}
                    >
                      <span className={styles.compactMain}>
                        <span className={styles.mono}>{request.number}</span>
                        <span className={styles.muted}>
                          {formatDate(request.created_at)} · {formatCount(request.items_count)}{' '}
                          {plural(request.items_count, ['позиция', 'позиции', 'позиций'])}
                        </span>
                      </span>
                      <span className={styles.compactSide}>
                        <StatusBadge label={status.label} tone={status.tone} />
                        <span className={styles.amount}>
                          {formatMoney(request.total_estimate, request.currency)}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <div className={styles.sideColumn}>
          <section className={styles.panel} aria-labelledby="profile-summary">
            <div className={styles.panelHead}>
              <h2 id="profile-summary" className={styles.panelTitle}>
                Профиль
              </h2>
              <Link href="/cabinet/profile" className={styles.textLink}>
                Изменить
              </Link>
            </div>
            <dl className={styles.details}>
              <div>
                <dt>Контактное лицо</dt>
                <dd>{profile.contact_name}</dd>
              </div>
              {profile.company_name ? (
                <div>
                  <dt>Компания</dt>
                  <dd>{profile.company_name}</dd>
                </div>
              ) : null}
              <div>
                <dt>Email</dt>
                <dd className={styles.breakAll}>{profile.email}</dd>
              </div>
              <div>
                <dt>Телефон</dt>
                <dd>{profile.phone}</dd>
              </div>
              <div>
                <dt>Регион</dt>
                <dd>{profile.region?.name ?? '—'}</dd>
              </div>
            </dl>
          </section>

          <section className={styles.panel} aria-labelledby="quick-actions">
            <h2 id="quick-actions" className={styles.panelTitle}>
              Быстрые действия
            </h2>
            <div className={styles.quickActions}>
              <Link href="/cabinet/projects?create=1" className={styles.quickAction}>
                <span className={styles.quickActionTitle}>Новый проект</span>
                <span className={styles.muted}>Соберите позиции под объект</span>
              </Link>
              <Link href="/cabinet/favorites" className={styles.quickAction}>
                <span className={styles.quickActionTitle}>Избранное</span>
                <span className={styles.muted}>Сохранённые товары</span>
              </Link>
              <Link href="/cabinet/notifications" className={styles.quickAction}>
                <span className={styles.quickActionTitle}>Уведомления</span>
                <span className={styles.muted}>
                  {unreadCount > 0 ? `Непрочитанных: ${formatCount(unreadCount)}` : 'Всё прочитано'}
                </span>
              </Link>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
