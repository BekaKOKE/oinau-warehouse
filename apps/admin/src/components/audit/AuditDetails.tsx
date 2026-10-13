'use client';

/**
 * Карточка записи журнала.
 *
 * Показывает ровно то, что отдал backend: ничего не достраивается и не
 * догружается. Значения полей выводятся как текст — журнал читают,
 * а не исполняют.
 */

import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { EmptyState } from '@/components/ui/States';
import type { AuditLogEntry } from '@/lib/api/types';
import {
  auditActionLabel,
  auditActionTone,
  auditActorLabel,
  auditEntityHref,
  auditEntityLabel,
  changeRows,
} from '@/lib/audit';
import { formatDateTime } from '@/lib/format';

import styles from './Audit.module.css';

type AuditDetailsProps = {
  entry: AuditLogEntry | null;
  onClose: () => void;
  /** Фильтр «все записи одного запроса» — по клику на request_id. */
  onFilterRequest?: (requestId: string) => void;
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={styles.detailRow}>
      <dt className={styles.detailLabel}>{label}</dt>
      <dd className={styles.detailValue}>{children}</dd>
    </div>
  );
}

export function AuditDetails({ entry, onClose, onFilterRequest }: AuditDetailsProps) {
  const rows = entry ? changeRows(entry.changes ?? {}) : [];
  const href = entry ? auditEntityHref(entry) : null;

  return (
    <Dialog
      open={entry !== null}
      onClose={onClose}
      variant="drawer"
      size="md"
      title={entry ? auditActionLabel(entry.action) : ''}
      description={entry ? formatDateTime(entry.created_at) : undefined}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      {entry ? (
        <div className={styles.details}>
          <dl className={styles.detailList}>
            <Row label="Действие">
              <span className={styles.inline}>
                <Badge tone={auditActionTone(entry.action)} dot>
                  {auditActionLabel(entry.action)}
                </Badge>
                <code className={styles.code}>{entry.action}</code>
              </span>
            </Row>
            <Row label="Объект">
              <span className={styles.inline}>
                <span>{auditEntityLabel(entry.entity_type)}</span>
                {entry.entity_id != null ? (
                  href ? (
                    <Link href={href} className={styles.inline}>
                      #{entry.entity_id} <Icon name="arrowRight" size={13} />
                    </Link>
                  ) : (
                    <span className={styles.muted}>#{entry.entity_id}</span>
                  )
                ) : null}
              </span>
            </Row>
            <Row label="Кто">
              {entry.user ? (
                <span className={styles.stack}>
                  <span>{entry.user.full_name}</span>
                  <span className={styles.muted}>{entry.user.email}</span>
                </span>
              ) : (
                <Badge tone="neutral">{auditActorLabel(entry.actor)}</Badge>
              )}
            </Row>
            {entry.user ? <Row label="Источник">{auditActorLabel(entry.actor)}</Row> : null}
            <Row label="Запись">
              <span className={styles.muted}>#{entry.id}</span>
            </Row>
            {entry.request_id ? (
              <Row label="Запрос">
                {onFilterRequest ? (
                  <button
                    type="button"
                    className={styles.linkButton}
                    onClick={() => onFilterRequest(entry.request_id ?? '')}
                    title="Показать все записи этого запроса"
                  >
                    <code className={styles.code}>{entry.request_id}</code>
                  </button>
                ) : (
                  <code className={styles.code}>{entry.request_id}</code>
                )}
              </Row>
            ) : null}
          </dl>

          <h3 className={styles.detailsTitle}>Изменения</h3>
          {rows.length === 0 ? (
            <EmptyState
              icon="info"
              title="Подробностей нет"
              description="Для этого действия backend не записывает изменённые поля."
              compact
            />
          ) : (
            <table className={styles.changes}>
              <caption className="visually-hidden">Изменённые поля</caption>
              <thead>
                <tr>
                  <th scope="col">Поле</th>
                  <th scope="col">Было</th>
                  <th scope="col">Стало</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row">
                      <span className={styles.stack}>
                        <span>{row.label}</span>
                        {row.label !== row.key ? (
                          <code className={styles.codeMuted}>{row.key}</code>
                        ) : null}
                      </span>
                    </th>
                    {row.value !== undefined ? (
                      <td colSpan={2} className={row.secret ? styles.secret : undefined}>
                        <pre className={styles.value}>{row.value}</pre>
                      </td>
                    ) : (
                      <>
                        <td>
                          <pre className={`${styles.value} ${styles.before}`}>{row.before}</pre>
                        </td>
                        <td>
                          <pre className={styles.value}>{row.after}</pre>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}
    </Dialog>
  );
}
