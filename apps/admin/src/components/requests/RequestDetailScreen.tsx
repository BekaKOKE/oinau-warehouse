'use client';

/**
 * Карточка заявки.
 *
 * Порядок блоков — порядок работы менеджера: статус, кто клиент, что
 * просят, на какую сумму, переписка, история. На широком экране статус
 * и история уходят в правую колонку, на телефоне всё идёт одной лентой
 * в том же порядке.
 */

import Link from 'next/link';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { EnumBadge } from '@/components/ui/Badge';
import { ButtonLink } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState, ErrorState, PageLoader } from '@/components/ui/States';
import { requestsApi } from '@/lib/api/endpoints';
import type { RequestComment, RequestDetail } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { isNotFound } from '@/lib/errors';
import { formatDateTime, formatRelative } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { REQUEST_KIND, REQUEST_SOURCE, REQUEST_STATUS } from '@/lib/labels';
import { telHref } from '@/lib/requests';

import { RequestAttachments } from './RequestAttachments';
import { RequestComments } from './RequestComments';
import { RequestHistory } from './RequestHistory';
import { RequestItems } from './RequestItems';
import { RequestStatusPanel } from './RequestStatusPanel';
import styles from './RequestDetail.module.css';

const BREADCRUMBS = [{ label: 'Заявки', href: '/requests' }];

function NotFound() {
  return (
    <>
      <PageHeader title="Заявка не найдена" breadcrumbs={BREADCRUMBS} />
      <Card>
        <EmptyState
          icon="requests"
          title="Такой заявки нет"
          description="Возможно, ссылка устарела или заявка удалена."
          action={
            <ButtonLink href="/requests" icon="chevronLeft">
              К списку заявок
            </ButtonLink>
          }
        />
      </Card>
    </>
  );
}

function CustomerCard({ request }: { request: RequestDetail }) {
  return (
    <dl className={styles.facts}>
      <div>
        <dt>Контактное лицо</dt>
        <dd className={styles.strong}>{request.customer_name}</dd>
      </div>
      {request.company ? (
        <div>
          <dt>Компания</dt>
          <dd>{request.company}</dd>
        </div>
      ) : null}
      <div>
        <dt>Телефон</dt>
        <dd>
          <a href={telHref(request.phone)} className="num">
            {request.phone}
          </a>
        </dd>
      </div>
      {request.email ? (
        <div>
          <dt>Email</dt>
          <dd>
            <a href={`mailto:${request.email}`}>{request.email}</a>
          </dd>
        </div>
      ) : null}
      {request.bin ? (
        <div>
          <dt>БИН</dt>
          <dd className="num">{request.bin}</dd>
        </div>
      ) : null}
      <div>
        <dt>Регион</dt>
        <dd>{request.region?.name ?? '—'}</dd>
      </div>
      <div>
        <dt>Источник</dt>
        <dd>
          {REQUEST_SOURCE[request.source]} · {REQUEST_KIND[request.kind]}
        </dd>
      </div>
      {request.page_url ? (
        <div className={styles.factWide}>
          <dt>Страница, с которой отправлена</dt>
          <dd className={styles.pageUrl}>{request.page_url}</dd>
        </div>
      ) : null}
      {request.comment ? (
        <div className={styles.factWide}>
          <dt>Комментарий клиента</dt>
          <dd className={styles.clientComment}>{request.comment}</dd>
        </div>
      ) : null}
    </dl>
  );
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function RequestDetailScreen({ id }: { id: number }) {
  return (
    <RequirePermission all={[Permission.REQUEST_READ]}>
      <RequestDetailPanel id={id} />
    </RequirePermission>
  );
}

function RequestDetailPanel({ id }: { id: number }) {
  const { can } = useSession();
  const canWrite = can(Permission.REQUEST_WRITE);
  const valid = Number.isInteger(id) && id > 0;
  const query = useQuery((signal) => requestsApi.get(id, { signal }), [id], { enabled: valid });

  if (!valid) return <NotFound />;
  if (query.status === 'error' && isNotFound(query.error)) return <NotFound />;
  if (query.status === 'error' && !query.data) {
    return (
      <>
        <PageHeader title="Заявка" breadcrumbs={BREADCRUMBS} />
        <Card>
          <ErrorState error={query.error} onRetry={query.reload} />
        </Card>
      </>
    );
  }
  if (!query.data) return <PageLoader label="Загружаем заявку…" />;

  const request = query.data;
  const setRequest = query.setData;
  const addComment = (comment: RequestComment) =>
    setRequest({ ...request, comments: [...(request.comments ?? []), comment] });

  return (
    <>
      <PageHeader
        breadcrumbs={[...BREADCRUMBS, { label: request.number }]}
        title={<span className="mono">{request.number}</span>}
        meta={
          <>
            <EnumBadge value={request.status} meta={REQUEST_STATUS} />
            <span className={styles.muted}>
              Создана {formatDateTime(request.created_at)} · изменена{' '}
              {formatRelative(request.updated_at)}
            </span>
          </>
        }
        actions={
          <Link href="/requests" className={styles.backLink}>
            <Icon name="chevronLeft" size={14} /> К списку
          </Link>
        }
      />

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <div className={styles.customer}>
            <Card title="Клиент">
              <CustomerCard request={request} />
            </Card>
            {request.attachments && request.attachments.length > 0 ? (
              <Card
                title="Файлы клиента"
                description="Спецификация или ТЗ к запросу КП. Файлы открываются только скачиванием."
              >
                <RequestAttachments requestId={request.id} attachments={request.attachments} />
              </Card>
            ) : null}
          </div>

          <div className={styles.items}>
            <Card title="Состав заявки" flush>
              <RequestItems request={request} />
            </Card>
          </div>

          <div className={styles.commentsArea}>
            <Card title="Комментарии" description="Внутренние заметки видят только сотрудники.">
              <RequestComments
                requestId={request.id}
                comments={request.comments ?? []}
                canWrite={canWrite}
                onAdded={addComment}
                onMissing={query.reload}
              />
            </Card>
          </div>
        </div>

        <div className={styles.sideColumn}>
          <div className={styles.status}>
            <Card title="Статус">
              <RequestStatusPanel
                request={request}
                canWrite={canWrite}
                onUpdated={setRequest}
                onMissing={query.reload}
              />
            </Card>
          </div>

          <div className={styles.history}>
            <Card title="История статусов">
              <RequestHistory entries={request.status_history ?? []} />
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
