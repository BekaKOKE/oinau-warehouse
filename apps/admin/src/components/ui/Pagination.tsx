'use client';

import { formatCount } from '@/lib/format';

import { Button } from './Button';
import styles from './Pagination.module.css';

type PaginationProps = {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
};

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  disabled,
}: PaginationProps) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav className={styles.pagination} aria-label="Страницы">
      <span className={styles.summary}>
        <span className="num">
          {formatCount(from)}–{formatCount(to)}
        </span>{' '}
        из <span className="num">{formatCount(total)}</span>
      </span>
      <div className={styles.controls}>
        <Button
          size="sm"
          variant="secondary"
          icon="chevronLeft"
          aria-label="Предыдущая страница"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(page - 1)}
        />
        <span className={styles.page}>
          <span className="num">{page}</span> / <span className="num">{Math.max(pages, 1)}</span>
        </span>
        <Button
          size="sm"
          variant="secondary"
          icon="chevronRight"
          aria-label="Следующая страница"
          disabled={disabled || page >= pages}
          onClick={() => onPageChange(page + 1)}
        />
      </div>
    </nav>
  );
}
