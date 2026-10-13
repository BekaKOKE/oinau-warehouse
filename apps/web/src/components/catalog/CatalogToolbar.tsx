/**
 * Панель над выдачей: сортировка, сколько найдено, снятие фильтров
 * и запрос КП.
 *
 * Сортировка — как в макете, рядом кнопок. Каждая из них — ссылка:
 * порядок попадает в URL и в серверный рендер. На телефоне ряд не
 * помещается, там тот же выбор — обычным `<select>`.
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';

import { badgeStyles } from '@/components/ui/AvailabilityBadge';
import { SORT_LABELS, activeChips, catalogHref, type CatalogFilters } from '@/lib/catalog-params';
import { fieldStyles } from '@/components/ui/Field';
import { productCountLabel } from '@/lib/format';
import styles from './Catalog.module.css';

const SORT_VALUES = Object.keys(SORT_LABELS) as Array<keyof typeof SORT_LABELS>;

/** Короткие подписи для ряда кнопок; полные — в выпадающем списке. */
const SORT_SHORT: Record<keyof typeof SORT_LABELS, string> = {
  relevance: 'Популярные',
  price_asc: 'Дешевле',
  price_desc: 'Дороже',
  newest: 'Новинки',
  name: 'А–Я',
  sku: 'Артикул',
};

const SORT_ORDER: Array<keyof typeof SORT_LABELS> = [
  'relevance',
  'price_asc',
  'price_desc',
  'newest',
  'name',
  'sku',
];

export function CatalogToolbar({
  filters,
  total,
  categoryName,
  basePath = '/catalog',
  lockCategory = false,
  currencySign = '₸',
  quoteAction,
  attrLabels = {},
}: {
  filters: CatalogFilters;
  total: number;
  categoryName?: string;
  basePath?: string;
  lockCategory?: boolean;
  currencySign?: string;
  quoteAction?: ReactNode;
  /** Подписи фильтров по характеристикам для плашек. */
  attrLabels?: Record<string, string>;
}) {
  const router = useRouter();
  const chips = activeChips(
    filters,
    lockCategory ? undefined : categoryName,
    currencySign,
    attrLabels,
  );
  const viewHref = (view: CatalogFilters['view']) =>
    catalogHref({ ...filters, view, page: 1 }, { basePath, keepCategory: !lockCategory });
  const sortHref = (sort: CatalogFilters['sort']) =>
    catalogHref({ ...filters, sort, page: 1 }, { basePath, keepCategory: !lockCategory });

  return (
    <div className={styles.toolbarWrap}>
      <div className={styles.toolbar}>
        <span className={styles.sortLabel} aria-hidden="true">
          Сортировка
        </span>
        <nav className={styles.sortButtons} aria-label="Порядок товаров">
          {SORT_ORDER.map((value) => {
            const active = filters.sort === value;
            return (
              <Link
                key={value}
                href={sortHref(value)}
                className={active ? `${styles.sortButton} ${styles.sortActive}` : styles.sortButton}
                aria-current={active ? 'true' : undefined}
                title={SORT_LABELS[value]}
              >
                {SORT_SHORT[value]}
              </Link>
            );
          })}
        </nav>

        <label className={styles.sortSelectWrap}>
          <span className="visuallyHidden">Сортировка</span>
          <select
            className={`${fieldStyles.control} ${styles.sortSelect}`}
            value={filters.sort}
            onChange={(event) =>
              router.push(sortHref(event.target.value as CatalogFilters['sort']))
            }
          >
            {SORT_VALUES.map((value) => (
              <option key={value} value={value}>
                {SORT_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <p className={styles.foundCount} aria-live="polite">
          Найдено {productCountLabel(total)}
        </p>

        <nav className={styles.viewToggle} aria-label="Вид списка">
          {(['grid', 'table'] as const).map((view) => (
            <Link
              key={view}
              href={viewHref(view)}
              className={
                filters.view === view
                  ? `${styles.viewButton} ${styles.viewActive}`
                  : styles.viewButton
              }
              aria-current={filters.view === view ? 'true' : undefined}
            >
              {view === 'table' ? 'Таблица' : 'Плитка'}
            </Link>
          ))}
        </nav>

        {quoteAction ? <div className={styles.quote}>{quoteAction}</div> : null}
      </div>

      {chips.length > 0 ? (
        <ul className={styles.chips} aria-label="Активные фильтры">
          {chips.map((chip) => (
            <li key={chip.key}>
              <Link
                href={catalogHref(chip.next, { basePath, keepCategory: !lockCategory })}
                className={badgeStyles.pill}
                aria-label={`Снять фильтр: ${chip.label}`}
              >
                {chip.label}
                <span aria-hidden="true">✕</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
