'use client';

/**
 * Раздел «Интеграции»: что включено и как прошёл последний обмен.
 *
 * Это страница состояния, а не пульт: отсюда ничего не включается и не
 * перезапускается. Настройки живут в переменных окружения, и менять их
 * из браузера было бы способом выключить уведомления одним кликом.
 *
 * Реквизитов здесь нет ни одного — backend их и не отдаёт. Показываются
 * только «настроено / не настроено», число получателей и счётчики.
 */

import Link from 'next/link';

import { RequirePermission } from '@/components/session/AuthGate';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { integrationApi } from '@/lib/api/endpoints';
import type { IntegrationChannel, IntegrationSyncSummary } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { formatCount, formatDateTime, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';

import styles from './Integration.module.css';

const CHANNEL_LABELS: Record<string, string> = {
  telegram: 'Telegram',
  email: 'Электронная почта',
};

/** Почему канал выключен. Значения приходят из backend. */
const REASON_LABELS: Record<string, string> = {
  disabled_globally: 'Уведомления выключены настройкой',
  not_configured: 'Реквизиты не заданы',
  no_recipients: 'Получатели не указаны',
};

const ENTITY_LABELS: Record<string, string> = {
  product: 'Товары',
  price: 'Цены',
  stock: 'Остатки',
};

const SYNC_STATUS: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  success: { label: 'Успешно', tone: 'success' },
  partial: { label: 'Частично', tone: 'warning' },
  failed: { label: 'Не применён', tone: 'danger' },
};

export function IntegrationScreen() {
  return (
    <RequirePermission all={[Permission.SETTINGS_WRITE]}>
      <IntegrationPanel />
    </RequirePermission>
  );
}

function ChannelCard({ channel }: { channel: IntegrationChannel }) {
  const label = CHANNEL_LABELS[channel.channel] ?? channel.channel;
  return (
    <div className={styles.channel}>
      <div className={styles.channelTop}>
        <span className={styles.channelName}>{label}</span>
        {channel.enabled ? (
          <Badge tone="success" dot>
            Включён
          </Badge>
        ) : (
          <Badge tone="neutral" dot>
            Выключен
          </Badge>
        )}
      </div>
      <span className={styles.muted}>
        {channel.enabled
          ? `${formatCount(channel.recipients)} ${plural(channel.recipients, ['получатель', 'получателя', 'получателей'])}`
          : (REASON_LABELS[channel.reason ?? ''] ?? channel.reason ?? '—')}
      </span>
    </div>
  );
}

function SyncRow({ sync }: { sync: IntegrationSyncSummary }) {
  const meta = SYNC_STATUS[sync.status] ?? { label: sync.status, tone: 'neutral' as const };
  return (
    <div className={styles.syncRow}>
      <div className={styles.syncMain}>
        <span className={styles.strong}>{ENTITY_LABELS[sync.entity] ?? sync.entity}</span>
        <span className={styles.muted}>{formatDateTime(sync.created_at)}</span>
      </div>
      <Badge tone={meta.tone} dot>
        {meta.label}
      </Badge>
      <span className={styles.counters}>
        принято <b className="num">{formatCount(sync.received)}</b>
        {' · '}
        изменено <b className="num">{formatCount(sync.updated + sync.created)}</b>
        {sync.failed > 0 ? (
          <>
            {' · '}
            <span className={styles.failed}>
              ошибок <b className="num">{formatCount(sync.failed)}</b>
            </span>
          </>
        ) : null}
      </span>
    </div>
  );
}

function IntegrationPanel() {
  const status = useQuery((signal) => integrationApi.status({ signal }), []);
  const data = status.data;

  if (status.status === 'error') {
    return (
      <>
        <PageHeader title="Интеграции" />
        <Card>
          <ErrorState error={status.error} onRetry={status.reload} />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Интеграции"
        description="Состояние каналов уведомлений и обмена с учётной системой. Настройки задаются переменными окружения — отсюда они не меняются."
        actions={
          <Button size="sm" icon="refresh" onClick={status.reload} disabled={status.isRefreshing}>
            Обновить
          </Button>
        }
      />

      <Card
        title="Уведомления"
        description="Куда уходят сообщения о новых заявках и письма клиентам."
      >
        {data ? (
          <div className={styles.channels}>
            {data.channels.map((channel) => (
              <ChannelCard key={channel.channel} channel={channel} />
            ))}
          </div>
        ) : (
          <Skeleton height={72} />
        )}
      </Card>

      <Card
        title="Очередь отправки"
        description="События ждут в базе, а не в памяти: отказ канала не теряет уведомление."
      >
        {data ? (
          <div className={styles.metrics}>
            <Metric label="Ожидают" value={data.outbox.pending} />
            <Metric label="Отправлено" value={data.outbox.sent} />
            <Metric label="Пропущено" value={data.outbox.skipped} hint="Канал был выключен" />
            <Metric label="Не доставлено" value={data.outbox.failed} tone="danger" />
          </div>
        ) : (
          <Skeleton height={72} />
        )}
      </Card>

      <Card
        title="Обмен с 1С"
        description="Контракт обмена реализован, но до сверки со спецификацией 1С боевой обмен выключен."
        actions={
          <Link href="/audit?entity=product&actor=1c" className={styles.cardLink}>
            Изменения из 1С <Icon name="arrowRight" size={14} />
          </Link>
        }
      >
        {!data ? (
          <Skeleton height={96} />
        ) : (
          <div className={styles.stack}>
            <div className={styles.inline}>
              {data.one_c_enabled ? (
                <Badge tone="success" dot>
                  Обмен включён
                </Badge>
              ) : (
                <Badge tone="neutral" dot>
                  Обмен выключен
                </Badge>
              )}
              <span className={styles.muted}>
                {formatCount(data.api_keys_active)}{' '}
                {plural(data.api_keys_active, [
                  'действующий ключ',
                  'действующих ключа',
                  'действующих ключей',
                ])}
              </span>
            </div>

            {data.last_syncs.length === 0 ? (
              <EmptyState
                icon="info"
                title="Обменов ещё не было"
                description="Здесь появятся результаты выгрузок из учётной системы."
                compact
              />
            ) : (
              <div className={styles.syncList}>
                {data.last_syncs.map((sync) => (
                  <SyncRow key={sync.entity} sync={sync} />
                ))}
              </div>
            )}

            {data.last_failure ? (
              <div className={styles.failureNote}>
                <Icon name="alert" size={14} />
                Последний сбой:{' '}
                {ENTITY_LABELS[data.last_failure.entity] ?? data.last_failure.entity},{' '}
                {formatDateTime(data.last_failure.created_at)} — ошибок{' '}
                {formatCount(data.last_failure.failed)}
              </div>
            ) : null}
          </div>
        )}
      </Card>
    </>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: 'danger';
}) {
  return (
    <div className={styles.metric}>
      <span
        className={`${styles.metricValue} ${tone === 'danger' && value > 0 ? styles.failed : ''}`}
      >
        <span className="num">{formatCount(value)}</span>
      </span>
      <span className={styles.metricLabel}>{label}</span>
      {hint ? <span className={styles.metricHint}>{hint}</span> : null}
    </div>
  );
}
