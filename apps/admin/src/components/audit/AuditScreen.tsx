'use client';

/**
 * Раздел «Аудит»: журнал изменений только для чтения.
 *
 * Право — существующее `audit.read` (ADMIN и SUPERADMIN). Журнал
 * пишут сервисы доменов; отсюда он не изменяется и не удаляется.
 *
 * Поиска по журналу backend не поддерживает — вместо него фильтры,
 * объявленные в GET /admin/audit: раздел, действие, кто, период.
 */

import Link from 'next/link';
import { useMemo, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Field, Input, Select } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { auditApi, usersApi } from '@/lib/api/endpoints';
import type { AuditLogEntry } from '@/lib/api/types';
import {
  actionOptions,
  actorOptions,
  AUDIT_PAGE_SIZE,
  auditActionLabel,
  auditActionTone,
  auditActorLabel,
  auditDateRangeError,
  auditEntityHref,
  auditEntityLabel,
  auditListQuery,
  changesSummary,
  DEFAULT_AUDIT_FILTERS,
  entityOptions,
  hasActiveAuditFilters,
  parseAuditFilters,
  serializeAuditFilters,
} from '@/lib/audit';
import { Permission } from '@/lib/auth/permissions';
import { formatCount, formatDateTime, formatRelative, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';

import { AuditDetails } from './AuditDetails';
import styles from './Audit.module.css';

/**
 * Запросы живут внутри `RequirePermission`: роли без права не нужен ни
 * запрос, ни гарантированный 403 в консоли.
 */
export function AuditScreen() {
  return (
    <RequirePermission all={[Permission.AUDIT_READ]}>
      <AuditPanel />
    </RequirePermission>
  );
}

function Who({ entry }: { entry: AuditLogEntry }) {
  if (entry.user) {
    return (
      <span className={styles.stack}>
        <span className={styles.strong}>{entry.user.full_name}</span>
        <span className={`${styles.muted} ${styles.break}`}>{entry.user.email}</span>
      </span>
    );
  }
  return <Badge tone="neutral">{auditActorLabel(entry.actor)}</Badge>;
}

function EntityCell({ entry }: { entry: AuditLogEntry }) {
  const href = auditEntityHref(entry);
  return (
    <span className={styles.stack}>
      <span>{auditEntityLabel(entry.entity_type)}</span>
      {entry.entity_id != null ? (
        href ? (
          <Link href={href} className={styles.objectLink}>
            #{entry.entity_id}
            <Icon name="arrowRight" size={12} />
          </Link>
        ) : (
          <span className={styles.muted}>#{entry.entity_id}</span>
        )
      ) : null}
    </span>
  );
}

function AuditPanel() {
  const { can } = useSession();
  const { filters, apply } = useUrlFilters({
    parse: parseAuditFilters,
    serialize: serializeAuditFilters,
  });
  const [open, setOpen] = useState<AuditLogEntry | null>(null);

  const rangeError = auditDateRangeError(filters);
  const query = useMemo(() => auditListQuery(filters), [filters]);
  const list = useQuery((signal) => auditApi.list(query, { signal }), [JSON.stringify(query)], {
    enabled: !rangeError,
  });

  // Список сотрудников для фильтра «Кто» — только если роль вправе его
  // читать. У ADMIN и SUPERADMIN право есть; менять условие под аудит
  // нельзя — это был бы заведомый 403.
  const canListUsers = can(Permission.USER_MANAGE);
  const staff = useQuery((signal) => usersApi.list({ page_size: 60 }, { signal }), [], {
    enabled: canListUsers,
  });

  const data = list.data;
  const active = hasActiveAuditFilters(filters);

  const columns: Column<AuditLogEntry>[] = [
    {
      key: 'created',
      header: 'Когда',
      width: '17%',
      cell: (entry) => (
        <span className={styles.stack}>
          <span className={styles.nowrap}>{formatDateTime(entry.created_at)}</span>
          <span className={`${styles.muted} ${styles.nowrap}`}>
            {formatRelative(entry.created_at)}
          </span>
        </span>
      ),
    },
    {
      key: 'action',
      header: 'Действие',
      cell: (entry) => (
        <span className={styles.stack}>
          <Badge tone={auditActionTone(entry.action)} dot>
            {auditActionLabel(entry.action)}
          </Badge>
          <code className={styles.codeMuted}>{entry.action}</code>
        </span>
      ),
    },
    { key: 'object', header: 'Объект', cell: (entry) => <EntityCell entry={entry} /> },
    { key: 'who', header: 'Кто', cell: (entry) => <Who entry={entry} /> },
    {
      key: 'changes',
      header: 'Изменения',
      hideOnMobile: true,
      cell: (entry) => {
        const summary = changesSummary(entry.changes ?? {});
        return summary ? (
          <span className={styles.summary}>{summary}</span>
        ) : (
          <span className={styles.muted}>—</span>
        );
      },
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (entry) => (
        <Button size="sm" variant="ghost" onClick={() => setOpen(entry)}>
          Подробно
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Аудит"
        description="Журнал изменений: кто, что и когда изменил. Журнал только для чтения — записи не редактируются и не удаляются."
      />

      <Card flush>
        <form
          className={styles.filters}
          role="search"
          aria-label="Фильтр журнала"
          onSubmit={(event) => event.preventDefault()}
        >
          <Field label="Раздел">
            <Select
              options={entityOptions()}
              placeholder="Все разделы"
              value={filters.entityType}
              onChange={(event) =>
                // Действие принадлежит разделу: при смене раздела
                // прежний выбор действия стал бы заведомо пустой выборкой.
                apply({ entityType: event.target.value, action: '' })
              }
            />
          </Field>
          <Field label="Действие">
            <Select
              options={actionOptions(filters.entityType)}
              placeholder="Любое"
              value={filters.action}
              onChange={(event) => apply({ action: event.target.value })}
            />
          </Field>
          <Field label="Источник">
            <Select
              options={actorOptions()}
              placeholder="Любой"
              value={filters.actor}
              onChange={(event) => apply({ actor: event.target.value })}
            />
          </Field>
          {canListUsers ? (
            <Field label="Сотрудник">
              <Select
                options={(staff.data?.items ?? []).map((user) => ({
                  value: user.uuid,
                  label: user.full_name,
                }))}
                placeholder="Любой"
                value={filters.userUuid}
                onChange={(event) => apply({ userUuid: event.target.value })}
              />
            </Field>
          ) : null}
          <Field label="С даты" error={rangeError ?? undefined}>
            <Input
              type="date"
              value={filters.dateFrom}
              onChange={(event) => apply({ dateFrom: event.target.value })}
            />
          </Field>
          <Field label="по">
            <Input
              type="date"
              value={filters.dateTo}
              onChange={(event) => apply({ dateTo: event.target.value })}
            />
          </Field>
        </form>

        <div className={styles.filtersFooter}>
          <span className={styles.inline}>
            {rangeError
              ? 'Уточните период'
              : data
                ? `${formatCount(data.total)} ${plural(data.total, ['запись', 'записи', 'записей'])}`
                : 'Загрузка…'}
            {filters.entityId ? (
              <button
                type="button"
                className={styles.chip}
                onClick={() => apply({ entityId: '' })}
                title="Снять фильтр по объекту"
              >
                объект #{filters.entityId}
                <Icon name="close" size={12} />
              </button>
            ) : null}
            {filters.requestId ? (
              <button
                type="button"
                className={styles.chip}
                onClick={() => apply({ requestId: '' })}
                title="Снять фильтр по запросу"
              >
                запрос {filters.requestId}
                <Icon name="close" size={12} />
              </button>
            ) : null}
          </span>
          {active ? (
            <Button
              size="sm"
              variant="ghost"
              icon="close"
              onClick={() => apply(DEFAULT_AUDIT_FILTERS)}
            >
              Сбросить фильтры
            </Button>
          ) : null}
        </div>

        <DataTable
          caption="Журнал аудита"
          columns={columns}
          rows={rangeError ? [] : data?.items}
          rowKey={(entry) => entry.id}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={(entry) => setOpen(entry)}
          skeletonRows={8}
          empty={
            rangeError ? (
              <EmptyState
                icon="alert"
                title="Период задан наоборот"
                description="Дата «с» должна быть не позже даты «по»."
                compact
              />
            ) : active ? (
              <EmptyState
                icon="search"
                title="Записей не найдено"
                description="Измените условия фильтра или сбросьте его."
                compact
              />
            ) : (
              <EmptyState
                icon="audit"
                title="Журнал пуст"
                description="Здесь появятся изменения каталога, заявок, контента и учётных записей."
                compact
              />
            )
          }
          renderMobile={(entry) => (
            <div className={styles.mobileCard}>
              <div className={styles.mobileTop}>
                <Badge tone={auditActionTone(entry.action)} dot>
                  {auditActionLabel(entry.action)}
                </Badge>
                <span className={`${styles.muted} ${styles.nowrap}`}>
                  {formatDateTime(entry.created_at)}
                </span>
              </div>
              <div className={styles.mobileRow}>
                <EntityCell entry={entry} />
                <Who entry={entry} />
              </div>
              {changesSummary(entry.changes ?? {}) ? (
                <span className={styles.summary}>{changesSummary(entry.changes ?? {})}</span>
              ) : null}
              <Button size="sm" variant="secondary" onClick={() => setOpen(entry)}>
                Подробно
              </Button>
            </div>
          )}
        />

        {data && !rangeError ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={AUDIT_PAGE_SIZE}
            disabled={list.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>

      <AuditDetails
        entry={open}
        onClose={() => setOpen(null)}
        onFilterRequest={(requestId) => {
          setOpen(null);
          apply({ requestId });
        }}
      />
    </>
  );
}
