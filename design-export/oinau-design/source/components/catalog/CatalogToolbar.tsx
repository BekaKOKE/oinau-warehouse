/**
 * Панель над выдачей: сколько найдено, снятие фильтров, сортировка.
 *
 * Сортировка — обычный `<select>`, который переписывает URL: так она
 * попадает в ссылку и в серверный рендер.
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { badgeStyles } from '@/components/ui/AvailabilityBadge';
import { SORT_LABELS, activeChips, catalogHref, type CatalogFilters } from '@/lib/catalog-params';
import { fieldStyles } from '@/components/ui/Field';
import { productCountLabel } from '@/lib/format';
import styles from './Catalog.module.css';

const SORT_VALUES = Object.keys(SORT_LABELS) as Array<keyof typeof SORT_LABELS>;

export function CatalogToolbar({
  filters,
  total,
  categoryName,
  basePath = '/catalog',
  lockCategory = false,
  currencySign = '₸',
}: {
  filters: CatalogFilters;
  total: number;
  categoryName?: string;
  basePath?: string;
  lockCategory?: boolean;
  currencySign?: string;
}) {
  const router = useRouter();
  const chips = activeChips(filters, lockCategory ? undefined : categoryName, currencySign);

  return (
    <div className={styles.toolbar}>
      <div className={styles.found}>
        <p className={styles.foundCount} aria-live="polite">
          Найдено {productCountLabel(total)}
        </p>
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

      <label className={fieldStyles.checkboxRow}>
        <span className={fieldStyles.label}>Сортировка</span>
        <select
          className={fieldStyles.control}
          style={{ width: 'auto', minWidth: 210 }}
          value={filters.sort}
          onChange={(event) =>
            router.push(
              catalogHref(
                { ...filters, sort: event.target.value as CatalogFilters['sort'], page: 1 },
                { basePath, keepCategory: !lockCategory },
              ),
            )
          }
        >
          {SORT_VALUES.map((value) => (
            <option key={value} value={value}>
              {SORT_LABELS[value]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
