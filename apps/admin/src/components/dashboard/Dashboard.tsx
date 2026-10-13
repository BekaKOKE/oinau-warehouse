'use client';

/**
 * Главный экран: что требует внимания прямо сейчас.
 *
 * Каждый блок грузится и падает независимо: у менеджера нет права
 * на каталог, у контент-менеджера — на заявки, и отказ одного запроса
 * не должен гасить весь экран. Блоки, на которые нет прав, не
 * запрашиваются вовсе.
 *
 * Показывается только то, что действительно отдаёт backend: счётчики
 * каталога — из сводки GET /admin/catalog/summary, счётчики заявок —
 * из поля `total` обычных списков (page_size=1). Своих метрик экран
 * не считает и аналитикой не является.
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useId, type ReactNode } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { EnumBadge } from '@/components/ui/Badge';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { StatCard } from '@/components/ui/StatCard';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { catalogApi, contentApi, productsApi, requestsApi } from '@/lib/api/endpoints';
import type {
  ContentSectionSummary,
  ProductListRow,
  RequestListItem,
  RequestStatus,
} from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { sectionMeta } from '@/lib/content/sections';
import { formatMoney } from '@/lib/decimal';
import { formatCount, formatDateTime, formatRelative, plural } from '@/lib/format';
import { useQuery, type QueryResult } from '@/lib/hooks/useQuery';
import { PRODUCT_STATUS, REQUEST_STATUS } from '@/lib/labels';
import { visibleNav } from '@/lib/navigation';

import styles from './Dashboard.module.css';

function greeting(date: Date): string {
  const hour = Number(
    new Intl.DateTimeFormat('ru-RU', {
      hour: 'numeric',
      hourCycle: 'h23',
      timeZone: 'Asia/Almaty',
    }).format(date),
  );
  if (hour < 5) return 'Доброй ночи';
  if (hour < 12) return 'Доброе утро';
  if (hour < 18) return 'Добрый день';
  return 'Добрый вечер';
}

function useTotal(fetcher: (signal: AbortSignal) => Promise<{ total: number }>, enabled: boolean) {
  return useQuery(async (signal) => (await fetcher(signal)).total, [], { enabled });
}

function statProps<T>(query: QueryResult<T>, value: number | undefined, enabled: boolean) {
  return {
    value,
    loading: enabled && query.status === 'loading',
    failed: query.status === 'error',
  };
}

function requestCountQuery(status: RequestStatus) {
  return (signal: AbortSignal) => requestsApi.list({ status, page_size: 1 }, { signal });
}

/** Счётчик сводки: подпись, число и — где это осмысленно — ссылка. */
function Metric({
  label,
  value,
  href,
  hint,
  loading,
}: {
  label: string;
  value: number | undefined;
  href?: string;
  hint?: string;
  loading: boolean;
}) {
  const body = (
    <>
      <span className={styles.metricValue}>
        {loading || value === undefined ? (
          <Skeleton width={44} height={20} />
        ) : (
          <span className="num">{formatCount(value)}</span>
        )}
      </span>
      <span className={styles.metricLabel}>{label}</span>
      {hint ? <span className={styles.metricHint}>{hint}</span> : null}
    </>
  );
  return href ? (
    <Link href={href} className={`${styles.metric} ${styles.metricLink}`}>
      {body}
    </Link>
  ) : (
    <div className={styles.metric}>{body}</div>
  );
}

/** Группа счётчиков сводки с заголовком, доступным как имя области. */
function MetricGroup({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className={styles.metricGroup} aria-labelledby={id}>
      <h3 id={id} className={styles.metricGroupTitle}>
        {title}
      </h3>
      <div className={styles.metrics}>{children}</div>
    </section>
  );
}

export function Dashboard() {
  const { user, can, permissions } = useSession();
  const router = useRouter();
  const canRequests = can(Permission.REQUEST_READ);
  const canCatalog = can(Permission.CATALOG_READ);
  const canContent = can(Permission.CONTENT_WRITE);

  const newRequests = useTotal(requestCountQuery('NEW'), canRequests);
  const inProgress = useTotal(requestCountQuery('IN_PROGRESS'), canRequests);
  // Одна сводка вместо нескольких списков с page_size=1: товары,
  // заполненность карточек, наличие и категории приходят вместе.
  const summary = useQuery((signal) => catalogApi.summary({ signal }), [], {
    enabled: canCatalog,
  });

  const recentRequests = useQuery(
    (signal) => requestsApi.list({ sort: 'newest', page_size: 6 }, { signal }),
    [],
    { enabled: canRequests },
  );
  const recentProducts = useQuery(
    (signal) => productsApi.list({ sort: 'updated', page_size: 6 }, { signal }),
    [],
    { enabled: canCatalog },
  );
  const sections = useQuery((signal) => contentApi.list({ signal }), [], { enabled: canContent });

  const catalog = summary.data;
  const summaryLoading = canCatalog && summary.status === 'loading';

  const requestColumns: Column<RequestListItem>[] = [
    {
      key: 'number',
      header: 'Заявка',
      cell: (row) => (
        <div className={styles.cellStack}>
          <Link href={`/requests/${row.id}`} className={`mono ${styles.nowrap}`}>
            {row.number}
          </Link>
          <span className={`${styles.muted} ${styles.nowrap}`}>
            {formatRelative(row.created_at)}
          </span>
        </div>
      ),
    },
    {
      key: 'customer',
      header: 'Клиент',
      cell: (row) => (
        <div className={styles.cellStack}>
          <span>{row.customer_name}</span>
          {row.company ? <span className={styles.muted}>{row.company}</span> : null}
        </div>
      ),
    },
    {
      key: 'total',
      header: 'Сумма',
      align: 'right',
      hideOnMobile: true,
      cell: (row) =>
        row.total_estimate ? (
          formatMoney(row.total_estimate, row.currency)
        ) : (
          <span className={styles.muted}>—</span>
        ),
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (row) => <EnumBadge value={row.status} meta={REQUEST_STATUS} />,
    },
  ];

  const productColumns: Column<ProductListRow>[] = [
    {
      key: 'name',
      header: 'Товар',
      cell: (row) => (
        <div className={styles.cellStack}>
          <Link href={`/products/${row.id}`}>{row.name}</Link>
          <span className={`${styles.muted} mono`}>{row.sku}</span>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (row) => <EnumBadge value={row.status} meta={PRODUCT_STATUS} />,
    },
    {
      key: 'updated',
      header: 'Изменён',
      align: 'right',
      hideOnMobile: true,
      cell: (row) => (
        <span className={`${styles.muted} ${styles.nowrap}`}>{formatRelative(row.updated_at)}</span>
      ),
    },
  ];

  const quickLinks = visibleNav(permissions)
    .flatMap((group) => group.items)
    .filter((item) => item.href !== '/');

  const newCount = newRequests.data;

  // Незаполненные разделы (updated_at пуст) оказываются в конце списка.
  const changedAt = (section: ContentSectionSummary) =>
    section.updated_at ? Date.parse(section.updated_at) : 0;
  const recentSections: ContentSectionSummary[] = [...(sections.data ?? [])].sort(
    (a, b) => changedAt(b) - changedAt(a),
  );

  return (
    <div className={styles.page}>
      <PageHeader
        title={`${greeting(new Date())}${user ? `, ${user.full_name.split(' ')[0]}` : ''}`}
        description={
          canRequests && newCount !== undefined
            ? newCount > 0
              ? `${formatCount(newCount)} ${plural(newCount, ['новая заявка ждёт', 'новые заявки ждут', 'новых заявок ждут'])} обработки.`
              : 'Новых заявок нет — всё обработано.'
            : 'Сводка по каталогу и заявкам.'
        }
      />

      {canRequests || canCatalog ? (
        <div className={styles.stats}>
          {canRequests ? (
            <>
              <StatCard
                label="Новые заявки"
                icon="requests"
                tone="cyan"
                href="/requests?status=NEW"
                {...statProps(newRequests, newRequests.data, canRequests)}
              />
              <StatCard
                label="Заявки в работе"
                icon="refresh"
                tone="blue"
                href="/requests?status=IN_PROGRESS"
                {...statProps(inProgress, inProgress.data, canRequests)}
              />
            </>
          ) : null}
          {canCatalog ? (
            <>
              <StatCard
                label="Активные товары"
                icon="products"
                tone="navy"
                href="/products?is_active=true"
                hint={
                  catalog
                    ? `${formatCount(catalog.products.publicly_visible)} видны на сайте`
                    : null
                }
                {...statProps(summary, catalog?.products.active, canCatalog)}
              />
              <StatCard
                label="Категории"
                icon="categories"
                tone="green"
                href={can(Permission.CATALOG_WRITE) ? '/categories' : undefined}
                {...statProps(summary, catalog?.categories.active, canCatalog)}
              />
            </>
          ) : null}
        </div>
      ) : null}

      {canCatalog ? (
        <Card
          title="Каталог"
          description="Счётчики по неудалённым товарам."
          actions={
            <Link href="/products" className={styles.cardLink}>
              Все товары <Icon name="arrowRight" size={14} />
            </Link>
          }
        >
          {summary.status === 'error' ? (
            <ErrorState error={summary.error} onRetry={summary.reload} compact />
          ) : (
            <div className={styles.metricGroups}>
              <MetricGroup title="Требует внимания">
                <Metric
                  label="Без изображений"
                  value={catalog?.content.without_images}
                  loading={summaryLoading}
                  hint={
                    catalog && catalog.content.without_ready_images > catalog.content.without_images
                      ? `${formatCount(catalog.content.without_ready_images)} без готовых`
                      : undefined
                  }
                />
                <Metric
                  label="Без цены"
                  value={catalog?.content.without_price}
                  loading={summaryLoading}
                  hint={
                    catalog
                      ? `${formatCount(catalog.content.price_on_request)} по запросу`
                      : undefined
                  }
                />
                <Metric
                  label="Черновики"
                  value={catalog?.products.draft}
                  href="/products?status=DRAFT"
                  loading={summaryLoading}
                />
                <Metric
                  label="Отключены"
                  value={catalog?.products.inactive}
                  href="/products?is_active=false"
                  loading={summaryLoading}
                />
              </MetricGroup>
              <MetricGroup title="Наличие на сайте">
                <Metric
                  label="В наличии"
                  value={catalog?.availability.in_stock}
                  href="/stock?availability=IN_STOCK"
                  loading={summaryLoading}
                />
                <Metric
                  label="Нет в наличии"
                  value={catalog?.availability.out_of_stock}
                  href="/stock?availability=OUT_OF_STOCK"
                  loading={summaryLoading}
                />
                <Metric
                  label="Под заказ"
                  value={catalog?.availability.on_request}
                  href="/stock?availability=ON_REQUEST"
                  loading={summaryLoading}
                />
                <Metric
                  label="Задано вручную"
                  value={catalog?.availability.overridden}
                  loading={summaryLoading}
                  hint="Переопределён показ наличия"
                />
              </MetricGroup>
            </div>
          )}
        </Card>
      ) : null}

      <div className={styles.grid}>
        {canRequests ? (
          <Card
            title="Последние заявки"
            flush
            actions={
              <Link href="/requests" className={styles.cardLink}>
                Все заявки <Icon name="arrowRight" size={14} />
              </Link>
            }
          >
            <DataTable
              columns={requestColumns}
              rows={recentRequests.data?.items}
              rowKey={(row) => row.id}
              loading={recentRequests.status === 'loading'}
              error={recentRequests.error}
              onRetry={recentRequests.reload}
              onRowClick={(row) => router.push(`/requests/${row.id}`)}
              skeletonRows={5}
              empty={<EmptyState title="Заявок пока нет" compact />}
              caption="Последние заявки"
              renderMobile={(row) => (
                <div className={styles.mobileCard}>
                  <div className={styles.mobileTop}>
                    <Link href={`/requests/${row.id}`} className="mono">
                      {row.number}
                    </Link>
                    <EnumBadge value={row.status} meta={REQUEST_STATUS} />
                  </div>
                  <span>{row.customer_name}</span>
                  <span className={styles.muted}>{formatRelative(row.created_at)}</span>
                </div>
              )}
            />
          </Card>
        ) : null}

        {canCatalog ? (
          <Card
            title="Недавно изменённые товары"
            flush
            actions={
              <Link href="/products" className={styles.cardLink}>
                Все товары <Icon name="arrowRight" size={14} />
              </Link>
            }
          >
            <DataTable
              columns={productColumns}
              rows={recentProducts.data?.items}
              rowKey={(row) => row.id}
              loading={recentProducts.status === 'loading'}
              error={recentProducts.error}
              onRetry={recentProducts.reload}
              onRowClick={(row) => router.push(`/products/${row.id}`)}
              skeletonRows={5}
              empty={<EmptyState title="Товаров пока нет" compact />}
              caption="Недавно изменённые товары"
              renderMobile={(row) => (
                <div className={styles.mobileCard}>
                  <div className={styles.mobileTop}>
                    <Link href={`/products/${row.id}`}>{row.name}</Link>
                    <EnumBadge value={row.status} meta={PRODUCT_STATUS} />
                  </div>
                  <span className={`${styles.muted} mono`}>{row.sku}</span>
                  <span className={styles.muted}>{formatRelative(row.updated_at)}</span>
                </div>
              )}
            />
          </Card>
        ) : null}
      </div>

      {canContent ? (
        <Card
          title="Разделы сайта"
          actions={
            <Link href="/content" className={styles.cardLink}>
              Все разделы <Icon name="arrowRight" size={14} />
            </Link>
          }
        >
          {sections.status === 'error' ? (
            <ErrorState error={sections.error} onRetry={sections.reload} compact />
          ) : sections.status === 'loading' ? (
            <Skeleton height={64} />
          ) : (
            <ul className={styles.sections}>
              {recentSections.map((section) => (
                <li key={section.key}>
                  <Link href={`/content/${section.key}`} className={styles.section}>
                    <span className={styles.sectionName}>{sectionMeta(section.key).label}</span>
                    <span className={styles.muted}>
                      {section.is_configured
                        ? `изменён ${formatDateTime(section.updated_at)}`
                        : 'не заполнен'}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}

      {quickLinks.length > 0 ? (
        <Card title="Быстрые переходы">
          <ul className={styles.quickLinks}>
            {quickLinks.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className={styles.quickLink}>
                  <span className={styles.quickIcon}>
                    <Icon name={item.icon} size={16} />
                  </span>
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
