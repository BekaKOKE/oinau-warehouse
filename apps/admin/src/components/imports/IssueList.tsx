'use client';

/**
 * Ошибки и предупреждения предпросмотра.
 *
 * Список бывает длинным (backend возвращает до 500 записей), поэтому
 * он сворачивается целиком и раскрывается порциями: экран не должен
 * превращаться в километровую простыню из-за одной неверной колонки.
 */

import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import type { ImportIssue } from '@/lib/api/types';
import { formatCount, plural } from '@/lib/format';
import { issueKey, issueLocation } from '@/lib/imports';

import styles from './ImportExport.module.css';

const PAGE = 20;

type IssueListProps = {
  title: string;
  description?: string;
  items: readonly ImportIssue[];
  /** Сколько всего нашёл backend: в ответ попадают не все записи. */
  total: number;
  tone: 'error' | 'warning';
  defaultOpen?: boolean;
};

export function IssueList({
  title,
  description,
  items,
  total,
  tone,
  defaultOpen = true,
}: IssueListProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [visible, setVisible] = useState(PAGE);

  if (items.length === 0 && total === 0) return null;

  const shown = items.slice(0, visible);
  const hidden = items.length - shown.length;
  const notReturned = total - items.length;

  return (
    <section
      className={`${styles.issues} ${tone === 'error' ? styles.toneError : styles.toneWarning}`}
    >
      <div className={styles.issuesHeader}>
        <h3 className={styles.issuesTitle}>
          {title}
          <Badge tone={tone === 'error' ? 'danger' : 'warning'}>{formatCount(total)}</Badge>
        </h3>
        <Button
          size="sm"
          variant="ghost"
          icon={open ? 'chevronUp' : 'chevronDown'}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Свернуть' : 'Показать'}
        </Button>
      </div>
      {open ? (
        <>
          {description ? <p className={`${styles.issue} ${styles.muted}`}>{description}</p> : null}
          <ul className={styles.issuesList}>
            {shown.map((issue, index) => (
              <li key={issueKey(issue, index)} className={styles.issue}>
                <span className={styles.issueLocation}>{issueLocation(issue)}</span>
                <span>{issue.message}</span>
                {issue.value ? (
                  <span className={styles.issueValue}>Значение: {issue.value}</span>
                ) : null}
              </li>
            ))}
          </ul>
          {hidden > 0 || notReturned > 0 ? (
            <div className={styles.issuesFooter}>
              {hidden > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setVisible((value) => value + PAGE)}
                >
                  Показать ещё {formatCount(Math.min(hidden, PAGE))}
                </Button>
              ) : (
                <span className={styles.muted}>
                  Показаны первые {formatCount(items.length)}{' '}
                  {plural(items.length, ['запись', 'записи', 'записей'])} из {formatCount(total)}
                </span>
              )}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
