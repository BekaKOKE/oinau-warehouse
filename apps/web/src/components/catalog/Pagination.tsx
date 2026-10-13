/**
 * Постраничная навигация.
 *
 * Ссылки, а не кнопки: страница каталога должна открываться сразу
 * нужной, индексироваться и работать в новой вкладке. Весь каталог
 * в браузер не тянется — API отдаёт по 24 позиции.
 */

import Link from 'next/link';

import { catalogHref, type CatalogFilters } from '@/lib/catalog-params';
import { formatCount } from '@/lib/format';
import styles from './Catalog.module.css';

/** Окно страниц вокруг текущей: 1 … 4 5 6 … 32. */
export function pageWindow(current: number, total: number): Array<number | 'gap'> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);

  const pages = new Set<number>([1, total, current]);
  for (const offset of [-1, 1]) {
    const candidate = current + offset;
    if (candidate > 1 && candidate < total) pages.add(candidate);
  }
  if (current <= 3) [2, 3, 4].forEach((page) => pages.add(page));
  if (current >= total - 2) [total - 3, total - 2, total - 1].forEach((page) => pages.add(page));

  const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const result: Array<number | 'gap'> = [];
  let previous = 0;
  for (const page of sorted) {
    if (previous && page - previous > 1) result.push('gap');
    result.push(page);
    previous = page;
  }
  return result;
}

export function Pagination({
  filters,
  page,
  pages,
  total,
  shown,
  basePath = '/catalog',
  lockCategory = false,
}: {
  filters: CatalogFilters;
  page: number;
  pages: number;
  total: number;
  shown: number;
  basePath?: string;
  lockCategory?: boolean;
}) {
  if (pages <= 1) return null;

  const href = (target: number) =>
    catalogHref({ ...filters, page: target }, { basePath, keepCategory: !lockCategory });

  return (
    <nav className={styles.pagination} aria-label="Страницы каталога">
      <div className={styles.pages}>
        <Link
          href={href(Math.max(page - 1, 1))}
          className={`${styles.page} ${page <= 1 ? styles.pageDisabled : ''}`}
          aria-disabled={page <= 1}
          aria-label="Предыдущая страница"
          rel="prev"
        >
          ‹
        </Link>

        {pageWindow(page, pages).map((item, index) =>
          item === 'gap' ? (
            <span key={`gap-${index}`} className={styles.pageGap} aria-hidden="true">
              …
            </span>
          ) : (
            <Link
              key={item}
              href={href(item)}
              className={`${styles.page} ${item === page ? styles.pageActive : ''}`}
              aria-current={item === page ? 'page' : undefined}
              aria-label={`Страница ${item}`}
            >
              {item}
            </Link>
          ),
        )}

        <Link
          href={href(Math.min(page + 1, pages))}
          className={`${styles.page} ${page >= pages ? styles.pageDisabled : ''}`}
          aria-disabled={page >= pages}
          aria-label="Следующая страница"
          rel="next"
        >
          ›
        </Link>
      </div>

      <p className={styles.pageInfo}>
        Показано {formatCount(shown)} из {formatCount(total)}
      </p>
    </nav>
  );
}
