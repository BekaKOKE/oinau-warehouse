/**
 * Панель «Подбор»: разделы, наличие, диапазон цены и характеристики.
 *
 * Только те фильтры, которые понимает backend. Характеристики (цвет,
 * материал, ...) — фасеты раздела из API: значения и счётчики считает
 * сервер, витрина их не придумывает.
 *
 * Любое изменение переписывает URL, а не локальное состояние: выдачу
 * должно быть можно переслать ссылкой и вернуть кнопкой «назад».
 *
 * Разделы (`categorySlot`) видны всегда; на телефоне наличие и цена
 * сворачиваются под кнопку «Фильтры».
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useId, useState, type ReactNode } from 'react';

import type { CategoryFacet } from '@oinau/api-types';

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
  categorySlot,
  facets = [],
}: {
  filters: Filters;
  basePath?: string;
  lockCategory?: boolean;
  currencySign?: string;
  categorySlot?: ReactNode;
  facets?: CategoryFacet[];
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

  function toggleAttr(value: string) {
    const current = filters.attrs ?? [];
    apply({
      attrs: current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    });
  }

  const hasFilters = Boolean(
    (filters.attrs ?? []).length > 0 ||
    filters.availability ||
    filters.minPrice ||
    filters.maxPrice ||
    filters.search ||
    (!lockCategory && filters.category),
  );

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <div className={styles.head}>
        <h2 className={styles.title} id={headingId}>
          Подбор
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
      </div>

      {categorySlot ? (
        <div className={`${styles.group} ${styles.categories}`}>
          <p className={styles.groupTitle}>Категория</p>
          {categorySlot}
        </div>
      ) : null}

      <button
        type="button"
        className={styles.mobileToggle}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={`${headingId}-body`}
      >
        {open ? 'Скрыть фильтры' : 'Фильтры'}
      </button>

      <div
        id={`${headingId}-body`}
        className={`${styles.collapsible} ${open ? styles.collapsibleOpen : ''}`}
      >
        <fieldset className={`${styles.group} ${styles.fieldset}`}>
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

        {facets.map((facet) => (
          <fieldset key={facet.code} className={`${styles.group} ${styles.fieldset}`}>
            <legend className={styles.groupTitle}>
              {facet.name}
              {facet.unit ? `, ${facet.unit}` : ''}
            </legend>
            <div className={styles.options}>
              {(facet.options ?? []).map((option) => {
                const value = `${facet.code}:${option.slug}`;
                return (
                  <label key={value} className={fieldStyles.checkboxRow}>
                    <input
                      className={fieldStyles.checkbox}
                      type="checkbox"
                      checked={(filters.attrs ?? []).includes(value)}
                      onChange={() => toggleAttr(value)}
                    />
                    {option.name}
                    <span className={styles.optionCount}>{option.count}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        ))}

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
              className={`${fieldStyles.control} ${styles.priceInput}`}
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
              className={`${fieldStyles.control} ${styles.priceInput}`}
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
          <Button type="submit" variant="dark" size="md" block className={styles.apply}>
            Применить
          </Button>
        </form>
      </div>
    </section>
  );
}
