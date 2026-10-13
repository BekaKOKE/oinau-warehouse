'use client';

/**
 * История импортов — таблица `import_jobs` backend.
 *
 * Показываются только те поля, которые отдаёт API: сам файл нигде не
 * хранится, автор приходит внутренним идентификатором и наружу не
 * выводится. Карточка импорта открывает полный отчёт с ошибками.
 */

import { useMemo, useState } from 'react';

import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Dialog } from '@/components/ui/Dialog';
import { Field, Select } from '@/components/ui/Field';
import { Card } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { importsApi } from '@/lib/api/endpoints';
import type { ImportJob, ImportJobStatus } from '@/lib/api/types';
import { formatBytes, formatCount, formatDateTime } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';
import { enumOptions, IMPORT_STATUS } from '@/lib/labels';
import {
  failureText,
  importListQuery,
  parseImportFilters,
  serializeImportFilters,
  summaryRows,
} from '@/lib/imports';

import { IssueList } from './IssueList';
import styles from './ImportExport.module.css';

const PAGE_SIZE = 10;

function Counts({ job }: { job: ImportJob }) {
  return (
    <span className={styles.historyCounts}>
      <span className={styles.createCount}>+{formatCount(job.products_created)}</span>
      <span className={styles.updateCount}>~{formatCount(job.products_updated)}</span>
      <span className={styles.muted}>={formatCount(job.products_unchanged)}</span>
    </span>
  );
}

function Problems({ job }: { job: ImportJob }) {
  const reason = failureText(job.failure_code);
  return (
    <span className={styles.inline}>
      {job.error_count > 0 ? <Badge tone="danger">{formatCount(job.error_count)} ош.</Badge> : null}
      {job.warning_count > 0 ? (
        <Badge tone="warning">{formatCount(job.warning_count)} пред.</Badge>
      ) : null}
      {reason ? (
        <span className={styles.muted} title={job.failure_code ?? undefined}>
          {reason}
        </span>
      ) : null}
      {job.error_count === 0 && job.warning_count === 0 && !reason ? (
        <span className={styles.muted}>—</span>
      ) : null}
    </span>
  );
}

function JobDetail({ uuid }: { uuid: string }) {
  const detail = useQuery((signal) => importsApi.get(uuid, { signal }), [uuid]);

  if (detail.status === 'loading' && !detail.data) {
    return (
      <div className={styles.detail}>
        <Skeleton height={18} width="60%" />
        <Skeleton height={60} />
      </div>
    );
  }
  if (detail.status === 'error' && !detail.data) {
    return <ErrorState error={detail.error} onRetry={detail.reload} compact />;
  }
  const job = detail.data;
  if (!job) return null;

  return (
    <div className={styles.detail}>
      <dl className={styles.detailList}>
        <dt>Файл</dt>
        <dd>
          {job.filename} · {formatBytes(job.file_size)}
        </dd>
        <dt>Загружен</dt>
        <dd>{formatDateTime(job.created_at)}</dd>
        <dt>Статус</dt>
        <dd>
          <EnumBadge value={job.status} meta={IMPORT_STATUS} />
        </dd>
        {job.committed_at ? (
          <>
            <dt>Применён</dt>
            <dd>{formatDateTime(job.committed_at)}</dd>
          </>
        ) : null}
        {job.failure_code ? (
          <>
            <dt>Причина</dt>
            <dd>{failureText(job.failure_code)}</dd>
          </>
        ) : null}
        <dt>Строк</dt>
        <dd>{formatCount(job.rows_total)}</dd>
      </dl>

      <div className={styles.summaryGrid}>
        {summaryRows(job.summary).map((row) => (
          <div key={row.key} className={styles.summaryCard}>
            <span className={styles.summaryTitle}>{row.label}</span>
            <span className={styles.summaryNumbers}>
              <span className={styles.createCount}>
                создано <b>{formatCount(row.create)}</b>
              </span>
              <span className={styles.updateCount}>
                изменено <b>{formatCount(row.update)}</b>
              </span>
            </span>
          </div>
        ))}
      </div>

      <IssueList title="Ошибки" items={job.errors ?? []} total={job.error_count} tone="error" />
      <IssueList
        title="Предупреждения"
        items={job.warnings ?? []}
        total={job.warning_count}
        tone="warning"
        defaultOpen={false}
      />
    </div>
  );
}

export function ImportHistory({ refreshKey }: { refreshKey: number }) {
  const { filters, apply } = useUrlFilters({
    parse: parseImportFilters,
    serialize: serializeImportFilters,
  });
  const [open, setOpen] = useState<ImportJob | null>(null);

  const query = useMemo(() => importListQuery(filters, PAGE_SIZE), [filters]);
  const list = useQuery(
    (signal) => importsApi.history(query, { signal }),
    [JSON.stringify(query), refreshKey],
  );
  const data = list.data;

  const columns: Column<ImportJob>[] = [
    {
      key: 'created',
      header: 'Загружен',
      cell: (job) => (
        <div className={styles.stack}>
          <span className={styles.strong}>{formatDateTime(job.created_at)}</span>
          {job.committed_at ? (
            <span className={styles.muted}>применён {formatDateTime(job.committed_at)}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: 'file',
      header: 'Файл',
      cell: (job) => (
        <div className={styles.stack}>
          <span className={styles.strong}>{job.filename}</span>
          <span className={styles.muted}>{formatBytes(job.file_size)}</span>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (job) => <EnumBadge value={job.status} meta={IMPORT_STATUS} />,
    },
    {
      key: 'rows',
      header: 'Строк',
      align: 'right',
      hideOnMobile: true,
      cell: (job) => <span className="num">{formatCount(job.rows_total)}</span>,
    },
    {
      key: 'products',
      header: 'Товары (+ / ~ / =)',
      hideOnMobile: true,
      cell: (job) => <Counts job={job} />,
    },
    { key: 'problems', header: 'Замечания', cell: (job) => <Problems job={job} /> },
  ];

  return (
    <>
      <Card flush title="История импортов">
        <form
          className={styles.historyFilters}
          onSubmit={(event) => event.preventDefault()}
          aria-label="Фильтр истории"
        >
          <Field label="Статус">
            <Select
              options={enumOptions(IMPORT_STATUS)}
              placeholder="Любой"
              value={filters.status}
              onChange={(event) => apply({ status: event.target.value as ImportJobStatus | '' })}
            />
          </Field>
        </form>
        <DataTable
          caption="История импортов"
          columns={columns}
          rows={data?.items}
          rowKey={(job) => job.uuid}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={(job) => setOpen(job)}
          skeletonRows={4}
          empty={
            <EmptyState
              icon="import"
              title="Импортов пока не было"
              description="Здесь появятся загруженные файлы, их статус и результат."
              compact
            />
          }
          renderMobile={(job) => (
            <div className={styles.mobileCard}>
              <div className={styles.mobileTop}>
                <div className={styles.stack}>
                  <span className={styles.strong}>{job.filename}</span>
                  <span className={styles.muted}>{formatDateTime(job.created_at)}</span>
                </div>
                <EnumBadge value={job.status} meta={IMPORT_STATUS} />
              </div>
              <Counts job={job} />
              <Problems job={job} />
            </div>
          )}
        />
        {data ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={PAGE_SIZE}
            disabled={list.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>

      <Dialog
        open={open !== null}
        onClose={() => setOpen(null)}
        variant="drawer"
        size="lg"
        title="Импорт"
        description={open?.filename}
        footer={
          <Button variant="secondary" onClick={() => setOpen(null)}>
            Закрыть
          </Button>
        }
      >
        {open ? <JobDetail uuid={open.uuid} /> : null}
      </Dialog>
    </>
  );
}
