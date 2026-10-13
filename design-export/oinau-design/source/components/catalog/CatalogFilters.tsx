/**
 * Фильтры каталога.
 *
 * Только те фильтры, которые понимает backend: наличие и диапазон цены.
 * Поля вроде «материал» или «цвет» публичный API фасетами не отдаёт,
 * и рисовать их значило бы обещать несуществующую выборку.
 *
 * Любое изменение переписывает URL, а не локальное состояние: выдачу
 * должно быть можно переслать ссылкой и вернуть кнопкой «назад».
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';

import { Button, ButtonLink } from '@/components/ui/Button';
import { fieldStyles } from '@/components/ui/Field';
import {
  AVAILABILITY_LABELS,
  catalogHref,
  type CatalogFilters as Filters,
} from '@/lib/catalog-params';
import styles from './CatalogFilters.module.css';

const AVAILABILITY_OPTIONS = Object.keys(AVAILABILITY_LABELS) as Array<
  keyof typeof AVAILABILITY_LABELS
>;

export function CatalogFilters({
  filters,
  basePath = '/catalog',
  /** На странице категории раздел задан маршрутом и в фильтрах не повторяется. */
  lockCategory = false,
  currencySign = '₸',
}: {
  filters: Filters;
  basePath?: string;
  lockCategory?: boolean;
  currencySign?: string;
}) {
  const router = useRouter();
  const headingId = useId();
  const [open, setOpen] = useState(false);
  const [minPrice, setMinPrice] = useState(filters.minPrice ?? '');
  const [maxPrice, setMaxPrice] = useState(filters.maxPrice ?? '');

  // Значения приходят из URL: после перехода «назад» поля обязаны
  // показывать то, что реально применено.
  useEffect(() => {
    setMinPrice(filters.minPrice ?? '');
    setMaxPrice(filters.maxPrice ?? '');
  }, [filters.minPrice, filters.maxPrice]);

  function apply(next: Partial<Filters>) {
    router.push(
      catalogHref({ ...filters, page: 1, ...next }, { basePath, keepCategory: !lockCategory }),
    );
  }

  const hasFilters = Boolean(
    filters.availability ||
    filters.minPrice ||
    filters.maxPrice ||
    filters.search ||
    (!lockCategory && filters.category),
  );

  return (
    <aside className={styles.panel} aria-labelledby={headingId}>
      <div className={styles.head}>
        <h2 className={styles.title} id={headingId}>
          Фильтры
        </h2>
        {hasFilters ? (
          <ButtonLink
            href={catalogHref({}, { basePath })}
            variant="ghost"
            size="sm"
            className={styles.reset}
          >
            Сбросить
          </ButtonLink>
        ) : null}
        <button
          type="button"
          className={styles.mobileToggle}
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={`${headingId}-body`}
        >
          {open ? 'Скрыть' : 'Показать'}
        </button>
      </div>

      <div
        id={`${headingId}-body`}
        className={`${styles.collapsible} ${open ? styles.collapsibleOpen : ''}`}
      >
        <fieldset className={styles.group} style={{ border: 0, margin: 0, padding: 0 }}>
          <legend className={styles.groupTitle}>Наличие</legend>
          <div className={styles.options}>
            {AVAILABILITY_OPTIONS.map((value) => (
              <label key={value} className={fieldStyles.checkboxRow}>
                <input
                  className={fieldStyles.checkbox}
                  type="radio"
                  name="availability"
                  checked={filters.availability === value}
                  onChange={() => apply({ availability: value })}
                />
                {AVAILABILITY_LABELS[value]}
              </label>
            ))}
            <label className={fieldStyles.checkboxRow}>
              <input
                className={fieldStyles.checkbox}
                type="radio"
                name="availability"
                checked={!filters.availability}
                onChange={() => apply({ availability: undefined })}
              />
              Любое
            </label>
          </div>
        </fieldset>

        <form
          className={styles.group}
          onSubmit={(event) => {
            event.preventDefault();
            apply({ minPrice: minPrice || undefined, maxPrice: maxPrice || undefined });
          }}
        >
          <span className={styles.groupTitle}>Цена, {currencySign}</span>
          <div className={styles.priceRow}>
            <input
              className={fieldStyles.control}
              type="number"
              min="0"
              step="1"
              inputMode="numeric"
              placeholder="от"
              aria-label={`Цена от, ${currencySign}`}
              value={minPrice}
              onChange={(event) => setMinPrice(event.target.value)}
            />
            <input
              className={fieldStyles.control}
              type="number"
              min="0"
              step="1"
              inputMode="numeric"
              placeholder="до"
              aria-label={`Цена до, ${currencySign}`}
              value={maxPrice}
              onChange={(event) => setMaxPrice(event.target.value)}
            />
          </div>
          <Button type="submit" variant="outline" size="sm" block className={styles.apply}>
            Применить
          </Button>
        </form>

        <div className={styles.note}>
          <p className={styles.noteTitle}>Не нашли позицию?</p>
          <p className={styles.noteText}>
            Пришлите спецификацию — подберём аналоги и рассчитаем стоимость.
          </p>
          <ButtonLink href="/contacts" size="sm" block className={styles.noteAction}>
            Написать нам
          </ButtonLink>
        </div>
      </div>
    </aside>
  );
}
